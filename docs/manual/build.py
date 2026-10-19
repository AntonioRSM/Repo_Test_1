"""Builds the self-contained manual: inlines the logo SVGs, icon and Lexend font.

Usage (from the repository root):  engine\\.venv\\Scripts\\python.exe docs\\manual\\build.py
Output: docs\\Manuale-RAG-Vault-Studio.html (works offline, no external requests).
"""

import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
OUT = HERE.parent / "Manuale-RAG-Vault-Studio.html"


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def logo(path: Path, label: str) -> str:
    # Official artwork extracted from the brand guidelines; never re-typeset.
    svg = path.read_text(encoding="utf-8")
    return svg.replace("<svg ", f'<svg role="img" aria-label="{label}" ', 1)


html = (HERE / "manuale.src.html").read_text(encoding="utf-8")
replacements = {
    "{{LOGO_POS}}": logo(ASSETS / "logo-positivo.svg", "workspace sm"),
    "{{LOGO_NEG}}": logo(ASSETS / "logo-negativo.svg", "workspace sm"),
    "{{ICON_PNG}}": data_uri(ASSETS / "icona.png", "image/png"),
    "{{FONT_WOFF2}}": data_uri(ASSETS / "lexend-latin.woff2", "font/woff2"),
}
for key, value in replacements.items():
    if key not in html:
        raise SystemExit(f"placeholder {key} missing from template")
    html = html.replace(key, value)

OUT.write_text(html, encoding="utf-8")
print(f"{OUT} ({OUT.stat().st_size // 1024} KB)")
