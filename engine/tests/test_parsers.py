from pathlib import Path

from vault_engine.ocr import NoOcr, RapidOcrEngine
from vault_engine.parsers import parse_file

OCR = RapidOcrEngine()


def kinds(doc):
    return [b.kind for b in doc.blocks]


def test_docx_headings_tables_metadata(docs: Path):
    doc = parse_file(docs / "contratto.docx", NoOcr())
    assert doc.author == "Mario Rossi"
    assert doc.title == "Contratto di fornitura"
    assert ("heading", "Penali") in [(b.kind, b.text) for b in doc.blocks]
    table = next(b for b in doc.blocks if b.kind == "table")
    assert "| Pallet | 12.000 EUR |" in table.text


def test_xlsx_sheet_as_table(docs: Path):
    doc = parse_file(docs / "budget.xlsx", NoOcr())
    assert doc.author == "Ufficio Finanza"
    assert "Foglio: Budget" in doc.blocks[0].text
    assert "| Ricerca | 87000 |" in doc.text


def test_pptx_slides(docs: Path):
    doc = parse_file(docs / "roadmap.pptx", NoOcr())
    assert doc.blocks[0].text == "Slide 1: Roadmap 2025"
    assert "Aurora" in doc.text
    assert all(b.page == 1 for b in doc.blocks)


def test_vector_pdf_heading_detection(docs: Path):
    doc = parse_file(docs / "manuale.pdf", OCR)
    assert doc.author == "Team Qualita"
    assert doc.ocr_pages == 0
    assert doc.blocks[0].kind == "heading" and doc.blocks[0].text == "Procedura di sicurezza"
    assert "guanti protettivi" in doc.text


def test_scanned_pdf_goes_through_ocr(docs: Path):
    doc = parse_file(docs / "scansione.pdf", OCR)
    assert doc.ocr_pages == 1
    assert "4471" in doc.text
    assert "980" in doc.text


def test_image_ocr(docs: Path):
    doc = parse_file(docs / "foto.png", OCR)
    assert "INVENTORY" in doc.text.upper()
    assert "1200" in doc.text


def test_text_formats(docs: Path):
    md = parse_file(docs / "note.md", NoOcr())
    assert [b.text for b in md.blocks if b.kind == "heading"] == ["Note riunione", "Azioni"]
    csv_doc = parse_file(docs / "dati.csv", NoOcr())
    assert "| Milano | 1350000 |" in csv_doc.text
    assert '"porta": 8080' in parse_file(docs / "config.json", NoOcr()).text
    assert "Aurora" in parse_file(docs / "leggimi.txt", NoOcr()).text
