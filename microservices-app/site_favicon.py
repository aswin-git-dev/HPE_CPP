"""Shared favicon markup for HPE microservices HTML pages (green clipboard SVG)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

_SITE_SVG = (
    Path(__file__).resolve().parent
    / "audit-service"
    / "app"
    / "static"
    / "icons"
    / "site.svg"
)


def site_favicon_link_tag() -> str:
    svg = _SITE_SVG.read_text(encoding="utf-8").strip()
    uri = "data:image/svg+xml," + quote(svg)
    return f'  <link rel="icon" href="{uri}" type="image/svg+xml" sizes="any"/>'
