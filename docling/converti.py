#!/usr/bin/env python3
"""
Conversione massiva di un archivio documentale in Markdown con Docling,
pronto per l'indicizzazione in LightRAG.

Formati: PDF (nativi e scansionati, con OCR), DOCX/DOC, PPTX/PPT, XLSX/XLS,
ODT/ODS/ODP, RTF, HTML, EPUB, CSV, immagini, email .eml/.msg (con allegati).

Uso:
    python converti.py ORIGINALI MARKDOWN [--copia-in INPUTS_LIGHTRAG]

- Riprende da dove si era fermato (salta i file già convertiti e non modificati).
- I file che vanno in errore vengono copiati in MARKDOWN/_quarantena.
- Ogni file è annotato in MARKDOWN/registro_conversione.csv.
"""

from __future__ import annotations

import argparse
import csv
import email
import email.policy
import hashlib
import html
import json
import logging
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import ConversionStatus, FormatToExtensions, InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TesseractCliOcrOptions,
)
from docling.datamodel.settings import settings
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

log = logging.getLogger("converti")

# Formati gestiti da Docling che ha senso indicizzare in un archivio documentale.
FORMATI = [
    InputFormat.PDF, InputFormat.IMAGE, InputFormat.DOCX, InputFormat.DOC,
    InputFormat.PPTX, InputFormat.PPT, InputFormat.XLSX, InputFormat.XLS,
    InputFormat.ODT, InputFormat.ODS, InputFormat.ODP, InputFormat.RTF,
    InputFormat.HTML, InputFormat.MHTML, InputFormat.EPUB, InputFormat.CSV,
    InputFormat.MD, InputFormat.EMAIL,
]
ESTENSIONI = {"." + e for f in FORMATI for e in FormatToExtensions[f]} | {".htm", ".txt"}
CON_OCR = {"." + e for f in (InputFormat.PDF, InputFormat.IMAGE) for e in FormatToExtensions[f]}
EMAIL = {".eml", ".msg"}

FILE_STATO = ".stato_conversione.json"
FILE_REGISTRO = "registro_conversione.csv"
CARTELLA_QUARANTENA = "_quarantena"
CARTELLA_ALLEGATI = "_allegati_estratti"


# ---------------------------------------------------------------- converter

def crea_converter(ocr: str, lingue: list[str], forza_ocr: bool, timeout: float,
                   tesseract_cmd: str = "tesseract") -> DocumentConverter:
    # RapidOCR è il predefinito: nelle prove ha letto meglio di Tesseract testo e tabelle scansionate
    if ocr == "tesseract":
        ocr_opts = TesseractCliOcrOptions(lang=lingue, tesseract_cmd=tesseract_cmd)
    else:
        ocr_opts = RapidOcrOptions()
    ocr_opts.force_full_page_ocr = forza_ocr

    pdf = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=ocr_opts,
        do_table_structure=True,
        document_timeout=timeout,
        accelerator_options=AcceleratorOptions(device=AcceleratorDevice.AUTO),
    )
    pdf.table_structure_options.mode = TableFormerMode.ACCURATE
    pdf.table_structure_options.do_cell_matching = True

    return DocumentConverter(
        allowed_formats=FORMATI,
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pdf),
        },
    )


# ---------------------------------------------------------------- pulizia

# "Pag. 3", "Pagina 3 di 10", "Page 3 of 10", "3 / 10", "3"
RE_NUM_PAGINA = re.compile(
    r"^\s*(?:(?:pag(?:\.|ina)?|page|p\.)\s*\d{1,4}|\d{1,3})(?:\s*(?:di|of|/)\s*\d{1,4})?\s*$",
    re.IGNORECASE,
)


def pulisci(md: str, pagine: int) -> str:
    md = html.unescape(md.replace("<!-- image -->", ""))
    # parole spezzate dal trattino a fine riga: "contrat-\nto" -> "contratto"
    md = re.sub(r"(\w)-\n(\w)", r"\1\2", md)
    righe = md.split("\n")
    # intestazioni/piè di pagina: righe brevi identiche ripetute su molte pagine
    soglia = max(3, int(pagine * 0.5)) if pagine > 1 else 10**9
    conteggio = Counter(r.strip() for r in righe)
    ripetute = {
        r for r, n in conteggio.items()
        if n >= soglia and 0 < len(r) <= 80 and not r.startswith(("|", "#", "-", "*"))
    }
    righe = [r for r in righe if r.strip() not in ripetute and not RE_NUM_PAGINA.match(r)]
    md = "\n".join(righe)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def qualita_ok(md: str, pagine: int) -> bool:
    """Scarta output quasi vuoti o pieni di caratteri illeggibili (OCR fallito)."""
    testo = re.sub(r"\s+", "", md)
    if len(testo) < max(50, 80 * pagine):
        return False
    lettere = sum(c.isalnum() for c in testo)
    return lettere / len(testo) >= 0.55


def intestazione(origine: Path, radice: Path, pagine: int, allegato_di: str | None) -> str:
    st = origine.stat()
    righe = [
        f"Titolo: {Path(origine.name[3:] if allegato_di else origine.name).stem.replace('_', ' ').strip()}",
        f"Tipo: {origine.suffix.lstrip('.').upper()}",
        f"File originale: {f'{allegato_di} > {origine.name[3:]}' if allegato_di else origine.relative_to(radice).as_posix()}",
        f"Data file: {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d}",
    ]
    if pagine:
        righe.append(f"Pagine: {pagine}")
    if allegato_di:
        righe.append(f"Allegato di: {allegato_di}")
    return "\n".join(righe) + "\n\n---\n\n"


# ---------------------------------------------------------------- email

def estrai_allegati(file: Path, destinazione: Path) -> list[Path]:
    destinazione.mkdir(parents=True, exist_ok=True)
    estratti: list[tuple[str, bytes]] = []
    if file.suffix.lower() == ".eml":
        msg = email.message_from_bytes(file.read_bytes(), policy=email.policy.default)
        for parte in msg.iter_attachments():
            dati = parte.get_payload(decode=True)
            if dati:
                estratti.append((parte.get_filename() or "allegato", dati))
    else:
        from oxmsg import Message
        for a in Message.load(str(file)).attachments:
            if a.file_bytes:
                estratti.append((a.file_name or "allegato", a.file_bytes))

    percorsi = []
    for i, (nome, dati) in enumerate(estratti, 1):
        nome = re.sub(r'[\\/:*?"<>|]', "_", Path(nome).name) or f"allegato_{i}"
        p = destinazione / f"{i:02d}_{nome}"
        p.write_bytes(dati)
        percorsi.append(p)
    return percorsi


# ---------------------------------------------------------------- motore

class Convertitore:
    def __init__(self, args: argparse.Namespace):
        self.origine: Path = args.origine.resolve()
        self.uscita: Path = args.uscita.resolve()
        self.copia_in: Path | None = args.copia_in.resolve() if args.copia_in else None
        self.uscita.mkdir(parents=True, exist_ok=True)
        lingue = args.lingue.split("+")
        self.conv = crea_converter(args.ocr, lingue, False, args.timeout, args.tesseract_cmd)
        self.conv_ocr_forzato = crea_converter(args.ocr, lingue, True, args.timeout, args.tesseract_cmd)
        self.percorso_stato = self.uscita / FILE_STATO
        self.stato = json.loads(self.percorso_stato.read_text(encoding="utf-8")) if self.percorso_stato.exists() else {}
        self.percorso_registro = self.uscita / FILE_REGISTRO
        nuovo = not self.percorso_registro.exists()
        self.registro = self.percorso_registro.open("a", newline="", encoding="utf-8-sig")
        self.csv = csv.writer(self.registro, delimiter=";")
        if nuovo:
            self.csv.writerow(["data", "file", "esito", "pagine", "caratteri", "secondi", "note"])
        self.totali = Counter()

    def annota(self, file: str, esito: str, pagine=0, caratteri=0, secondi=0.0, note=""):
        self.csv.writerow([f"{datetime.now():%Y-%m-%d %H:%M:%S}", file, esito,
                           pagine, caratteri, f"{secondi:.1f}", note])
        self.registro.flush()
        self.totali[esito] += 1

    def salva_stato(self):
        tmp = self.percorso_stato.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.stato, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.percorso_stato)

    def esegui(self):
        file = sorted(
            p for p in self.origine.rglob("*")
            if p.is_file() and p.suffix.lower() in ESTENSIONI
            and not p.name.startswith(("~$", "."))
        )
        log.info("Trovati %d file da esaminare in %s", len(file), self.origine)
        for n, f in enumerate(file, 1):
            log.info("[%d/%d] %s", n, len(file), f.relative_to(self.origine))
            self.converti(f, self.origine, self.uscita, allegato_di=None)
        self.registro.close()
        log.info("Fine. Esiti: %s", dict(self.totali))
        log.info("Registro: %s", self.percorso_registro)

    def converti(self, f: Path, radice: Path, base_uscita: Path, allegato_di: str | None, profondita=0):
        rel = f.relative_to(radice)
        chiave = rel.as_posix() if allegato_di is None else f"{allegato_di}::{rel.as_posix()}"
        impronta = hashlib.sha256(f.read_bytes()).hexdigest()
        if self.stato.get(chiave, {}).get("hash") == impronta and self.stato[chiave]["esito"] != "ERRORE":
            self.totali["GIA_FATTO"] += 1
            return

        destinazione = base_uscita / rel.parent / (f.name + ".md")
        t0 = time.time()
        esito, note, pagine, md = "OK", "", 0, ""
        try:
            md, pagine, status = self._docling(self.conv, f)
            if f.suffix.lower() in CON_OCR and not qualita_ok(md, pagine):
                log.info("   qualità bassa, riprovo con OCR su tutta la pagina")
                md, pagine, status = self._docling(self.conv_ocr_forzato, f)
                esito = "OK_OCR_FORZATO"
            if status == ConversionStatus.PARTIAL_SUCCESS:
                esito, note = "PARZIALE", "conversione incompleta (timeout o pagine illeggibili)"
            if not qualita_ok(md, pagine):
                esito, note = "DA_VERIFICARE", "poco testo o testo illeggibile"

            destinazione.parent.mkdir(parents=True, exist_ok=True)
            destinazione.write_text(intestazione(f, radice, pagine, allegato_di) + md, encoding="utf-8")
            if self.copia_in and esito != "DA_VERIFICARE":
                copia = self.copia_in / destinazione.relative_to(self.uscita)
                copia.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destinazione, copia)
        except Exception as e:  # file protetti, corrotti, formati non leggibili
            esito, note = "ERRORE", f"{type(e).__name__}: {e}"[:300]
            quarantena = self.uscita / CARTELLA_QUARANTENA / chiave.replace("::", "__")
            quarantena.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, quarantena)
            log.warning("   ERRORE: %s", note)

        self.annota(chiave, esito, pagine, len(md), time.time() - t0, note)
        self.stato[chiave] = {"hash": impronta, "esito": esito}
        self.salva_stato()

        if f.suffix.lower() in EMAIL and esito != "ERRORE" and profondita < 3:
            self._allegati(f, chiave, destinazione, profondita)

    def _docling(self, conv: DocumentConverter, f: Path):
        r = conv.convert(f, raises_on_error=True)
        doc = r.document
        pagine = doc.num_pages() if doc.pages else 0
        return pulisci(doc.export_to_markdown(), pagine), pagine, r.status

    def _allegati(self, f: Path, chiave: str, md_email: Path, profondita: int):
        cartella = self.uscita / CARTELLA_ALLEGATI / chiave.replace("::", "__")
        try:
            allegati = estrai_allegati(f, cartella)
        except Exception as e:
            self.annota(chiave, "ERRORE_ALLEGATI", note=str(e)[:300])
            return
        base = md_email.parent / (f.name + "_allegati")
        for a in allegati:
            if a.suffix.lower() in ESTENSIONI:
                self.converti(a, cartella, base, allegato_di=chiave, profondita=profondita + 1)
            else:
                self.annota(f"{chiave}::{a.name}", "SALTATO", note="formato allegato non supportato")


def main():
    ap = argparse.ArgumentParser(description="Converte un archivio documentale in Markdown con Docling.")
    ap.add_argument("origine", type=Path, help="cartella con i file originali")
    ap.add_argument("uscita", type=Path, help="cartella dove scrivere i Markdown")
    ap.add_argument("--copia-in", type=Path, help="copia i Markdown validi qui (es. la cartella inputs di LightRAG)")
    ap.add_argument("--ocr", choices=["rapidocr", "tesseract"], default="rapidocr",
                    help="motore OCR (default rapidocr; tesseract richiede il programma installato)")
    ap.add_argument("--lingue", default="ita+eng", help="lingue OCR di Tesseract (default ita+eng)")
    ap.add_argument("--tesseract-cmd", default=os.environ.get("TESSERACT_CMD", "tesseract"),
                    help="percorso di tesseract (default: variabile TESSERACT_CMD o 'tesseract')")
    ap.add_argument("--timeout", type=float, default=900, help="secondi massimi per documento")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for rumoroso in ("docling", "docling_core", "RapidOCR", "rapidocr", "httpx"):
        logging.getLogger(rumoroso).setLevel(logging.WARNING)

    if not args.origine.is_dir():
        sys.exit(f"Cartella non trovata: {args.origine}")
    # usa i modelli scaricati con "docling-tools models download" invece di riscaricarli
    modelli = settings.cache_dir / "models"
    if settings.artifacts_path is None and modelli.is_dir():
        settings.artifacts_path = modelli
    try:
        Convertitore(args).esegui()
    except KeyboardInterrupt:
        log.info("Interrotto: al prossimo avvio riprende da dove si è fermato.")


if __name__ == "__main__":
    main()
