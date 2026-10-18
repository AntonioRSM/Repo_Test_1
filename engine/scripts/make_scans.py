"""Writes sample scanned documents (PNG, raster-only PDF, multi-page TIFF) for OCR testing."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)


def page(lines: list[str], size=(1654, 1100)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("arial.ttf", 40)
    bold = ImageFont.truetype("arialbd.ttf", 52)
    y = 80
    for i, line in enumerate(lines):
        draw.text((90, y), line, fill="black", font=bold if i == 0 else font)
        y += 80 if i else 110
    return image


page(
    [
        "Verbale di collaudo n. 2025/118",
        "Impianto: linea di confezionamento B, stabilimento di Forlì",
        "Esito: superato con prescrizioni",
        "Prescrizione: sostituire la guarnizione della valvola entro 15 giorni",
        "Responsabile: ing. Chiara Bellucci",
    ]
).save(out / "verbale_collaudo.png")

page(
    [
        "Fattura n. 4471 del 03/02/2025",
        "Cliente: Officine Meccaniche Sammarinesi S.r.l.",
        "Descrizione: manutenzione straordinaria pressa idraulica",
        "Imponibile: 1.800,00 EUR   IVA 22%: 396,00 EUR",
        "Totale da pagare: 2.196,00 EUR entro 30 giorni",
    ]
).save(out / "fattura_scansionata.pdf", "PDF", resolution=150)

frames = [
    page(["Modulo richiesta ferie", "Dipendente: Luca Gatti", "Periodo: dal 4 al 15 agosto 2025"]),
    page(["Approvazione", "Approvato dal responsabile: Marta Neri", "Data: 12 giugno 2025"]),
]
frames[0].save(out / "modulo_ferie.tiff", save_all=True, append_images=frames[1:])
print("scans written to", out)
