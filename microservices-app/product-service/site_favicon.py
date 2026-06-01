"""Favicon link tag (same SVG as control-plane monitor)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

_SVG = Path(__file__).resolve().parent / "site.svg"


def site_favicon_link_tag() -> str:
    svg = _SVG.read_text(encoding="utf-8").strip()
    uri = "data:image/svg+xml," + quote(svg)
    return f'  <link rel="icon" href="{uri}" type="image/svg+xml" sizes="any"/>'
