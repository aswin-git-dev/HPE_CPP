from __future__ import annotations

from typing import Any, Dict, List

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException


class K8sMonitorService:
    def __init__(self) -> None:
        self._core: client.CoreV1Api | None = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            config.load_incluster_config()
            self._core = client.CoreV1Api()
        except ConfigException:
            try:
                # Local/dev mode: try kubeconfig (e.g. ~/.kube/config)
                config.load_kube_config()
                self._core = client.CoreV1Api()
            except ConfigException:
                self._core = None

    def pods_by_namespace(self) -> Dict[str, List[Dict[str, Any]]]:
        if self._core is None:
            return {}

        result: Dict[str, List[Dict[str, Any]]] = {}
        pods = self._core.list_pod_for_all_namespaces(watch=False).items
        for p in pods:
            ns = p.metadata.namespace or "default"
            result.setdefault(ns, []).append(
                {
                    "name": p.metadata.name,
                    "phase": p.status.phase,
                    "node": p.spec.node_name,
                    "pod_ip": p.status.pod_ip,
                    "host_ip": p.status.host_ip,
                }
            )
        return result

    def cluster_architecture(self) -> Dict[str, Any]:
        """Nodes -> namespaces -> pods; plus services grouped by namespace (for architecture UI)."""
        if self._core is None:
            return {"nodes": [], "services_by_namespace": {}, "error": "not_in_cluster"}

        try:
            return self._cluster_architecture_inner()
        except ApiException as e:
            return {
                "nodes": [],
                "services_by_namespace": {},
                "error": "kubernetes_api",
                "message": f"{e.reason} (HTTP {e.status}). ClusterRole needs nodes + services list.",
            }

    def _cluster_architecture_inner(self) -> Dict[str, Any]:
        node_map: Dict[str, Dict[str, Any]] = {}
        for n in self._core.list_node(watch=False).items:
            name = n.metadata.name
            labels = n.metadata.labels or {}
            is_cp = any(
                k in labels
                for k in ("node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master")
            )
            role = "control-plane" if is_cp else "worker"
            hpe_name = labels.get("hpe/node-name") or ""
            hpe_group = labels.get("hpe/node-group") or ""
            node_map[name] = {
                "name": name,
                "role": role,
                "hpe_node_name": hpe_name,
                "hpe_node_group": hpe_group,
                "namespaces": {},  # type: ignore
            }

        unsched = "_unscheduled_"
        node_map[unsched] = {
            "name": "(unscheduled)",
            "role": "pending",
            "hpe_node_name": "",
            "hpe_node_group": "",
            "namespaces": {},
        }

        for p in self._core.list_pod_for_all_namespaces(watch=False).items:
            node = p.spec.node_name or unsched
            if node not in node_map:
                node_map[node] = {
                    "name": node,
                    "role": "unknown",
                    "hpe_node_name": "",
                    "hpe_node_group": "",
                    "namespaces": {},
                }
            ns = p.metadata.namespace or "default"
            labels = p.metadata.labels or {}
            app = labels.get("app") or labels.get("name") or ""
            pod_info = {
                "name": p.metadata.name,
                "app": app,
                "phase": p.status.phase or "Unknown",
            }
            bucket = node_map[node]["namespaces"]
            bucket.setdefault(ns, []).append(pod_info)

        def sort_key(nm: str) -> tuple:
            r = node_map[nm]["role"]
            pri = 0 if r == "control-plane" else (2 if r == "pending" else 1)
            return (pri, nm)

        nodes_out: List[Dict[str, Any]] = []
        for nm in sorted([k for k in node_map.keys() if k != unsched], key=sort_key):
            nodes_out.append(_finalize_node(node_map[nm]))
        if node_map[unsched]["namespaces"]:
            nodes_out.append(_finalize_node(node_map[unsched]))

        svc_by_ns: Dict[str, List[Dict[str, str]]] = {}
        for s in self._core.list_service_for_all_namespaces(watch=False).items:
            ns = s.metadata.namespace or "default"
            name = s.metadata.name
            if name == "kubernetes" and ns == "default":
                continue
            stype = s.spec.type or "ClusterIP"
            svc_by_ns.setdefault(ns, []).append({"name": name, "type": stype})
        for ns in svc_by_ns:
            svc_by_ns[ns].sort(key=lambda x: x["name"])

        return {"nodes": nodes_out, "services_by_namespace": svc_by_ns, "error": None, "message": None}


def _finalize_node(raw: Dict[str, Any]) -> Dict[str, Any]:
    ns_data = raw["namespaces"]
    namespaces: List[Dict[str, Any]] = []
    for ns in sorted(ns_data.keys()):
        namespaces.append({"name": ns, "pods": sorted(ns_data[ns], key=lambda p: p["name"])})
    out = {k: v for k, v in raw.items() if k != "namespaces"}
    out["namespaces"] = namespaces
    return out
