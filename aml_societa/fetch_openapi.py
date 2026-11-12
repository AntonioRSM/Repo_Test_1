#!/usr/bin/env python3
"""Adattatore dati OpenAPI per il report AML società.

Uso:
  python fetch_openapi.py --piva 01234567890 --profilo medium --out dati.json
  python fetch_openapi.py --fixture esempio --profilo light --out dati.json

Senza OPENAPI_API_KEY o con --fixture produce dati di esempio, marcati come tali.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config" / "openapi_endpoints.json").read_text(encoding="utf-8"))
FIXTURE = HERE / "config" / "fixture_workspace_srl.json"


def _get(path: str) -> dict:
    key = os.environ.get("OPENAPI_API_KEY")
    if not key:
        raise RuntimeError("OPENAPI_API_KEY non impostata")
    req = urllib.request.Request(CFG["base_url"] + path)
    req.add_header(CFG["auth_header"], CFG["auth_prefix"] + key)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=CFG["timeout_s"]) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_live(piva: str, profilo: str) -> dict:
    liv = CFG["livelli_ricerca"][profilo]
    raw, errori = {}, []
    for nome in liv["endpoints"]:
        tpl = CFG["endpoints"][nome]
        path = tpl.format(piva=piva, nome="", cf="")
        try:
            raw[nome] = _get(path)
        except Exception as e:  # l'errore di un endpoint non blocca il report
            errori.append({"endpoint": nome, "errore": str(e)})
    return {
        "fonte": "OpenAPI (live)",
        "generato_il": datetime.now(timezone.utc).isoformat(),
        "profilo": profilo,
        "raw": raw,
        "errori_fetch": errori,
    }


def fetch_fixture(profilo: str) -> dict:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["fonte"] = "DATI DI ESEMPIO - NON REALI"
    data["generato_il"] = datetime.now(timezone.utc).isoformat()
    data["profilo"] = profilo
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--piva")
    ap.add_argument("--profilo", choices=["light", "medium", "strong"], default="medium")
    ap.add_argument("--fixture", help="usa i dati di esempio")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.fixture or not os.environ.get("OPENAPI_API_KEY"):
        if not a.fixture:
            print("OPENAPI_API_KEY assente: uso i dati di esempio.", file=sys.stderr)
        dati = fetch_fixture(a.profilo)
    else:
        if not a.piva:
            ap.error("--piva obbligatoria con chiave OpenAPI")
        dati = fetch_live(a.piva, a.profilo)

    Path(a.out).write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scritto {a.out} ({dati['fonte']}, profilo {a.profilo})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
