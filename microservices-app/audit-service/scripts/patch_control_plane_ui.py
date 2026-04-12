"""Refresh bundled control-plane UI from k8s/sample-control-plane-ui.html (for Docker/minikube)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.control_plane_ui_build import write_bundled_static  # noqa: E402


def main() -> None:
    out = write_bundled_static()
    print("Wrote", out, "— GET /control-plane/ui uses repo k8s sample when present, else this file.")


if __name__ == "__main__":
    main()
