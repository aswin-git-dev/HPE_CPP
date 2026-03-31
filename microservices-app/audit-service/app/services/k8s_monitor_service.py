from __future__ import annotations

from typing import Any, Dict, List

from kubernetes import client, config
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
            # Local/dev mode without in-cluster credentials.
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
