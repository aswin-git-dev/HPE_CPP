#!/usr/bin/env python3
"""Patch kube-apiserver static pod manifest to add audit-log volume mount."""
import sys, re, pathlib

p = pathlib.Path("/etc/kubernetes/manifests/kube-apiserver.yaml")
if not p.exists():
    print("manifest not found")
    sys.exit(1)

text = p.read_text()

# Fix bad patch from previous attempt (remove wrongly placed lines)
bad = "    - mountPath: /var/log/kubernetes/audit\n      name: audit-log\n    volumeMounts:\n"
if bad in text:
    text = text.replace(bad, "    volumeMounts:\n")
    print("Removed bad patch")

# 1. Add command line args
if "--audit-log-path=/var/log/kubernetes/audit/audit.log" not in text:
    # Insert after kube-apiserver command
    args = (
        "    - --audit-log-path=/var/log/kubernetes/audit/audit.log\n"
        "    - --audit-log-maxage=7\n"
        "    - --audit-log-maxbackup=3\n"
        "    - --audit-log-maxsize=100\n"
    )
    # the command usually starts with a bunch of args:
    # spec:
    #   containers:
    #   - command:
    #     - kube-apiserver
    text = text.replace(
        "    - kube-apiserver\n",
        "    - kube-apiserver\n" + args,
        1
    )
    print("Added audit log arguments")
else:
    print("Arguments already present")

# 2. Add volumeMount
if "mountPath: /var/log/kubernetes/audit" in text and "name: audit-log" in text:
    print("volumeMount already correctly patched")
else:
    # Add volumeMount: insert after the first "volumeMounts:" line
    vm_entry = "    - mountPath: /var/log/kubernetes/audit\n      name: audit-log\n"
    text = text.replace(
        "    volumeMounts:\n    - mountPath:",
        "    volumeMounts:\n" + vm_entry + "    - mountPath:",
        1
    )
    print("Added volumeMount")

# 3. Add volume entry
if "name: audit-log" not in text.split("volumes:")[1] if "volumes:" in text else True:
    vol_entry = (
        "  - hostPath:\n"
        "      path: /var/log/kubernetes/audit\n"
        "      type: DirectoryOrCreate\n"
        "    name: audit-log\n"
    )
    text = text.replace("  volumes:\n  - hostPath:", "  volumes:\n" + vol_entry + "  - hostPath:", 1)
    print("Added volume")
else:
    print("Volume already present")

p.write_text(text)
print("DONE")
