import asyncio

from vault_engine.chunking import (
    ChunkingSettings,
    build_sections,
    chunk_document,
    detect_language,
    drop_running_headers,
    split_recursive,
    split_with_overlap,
)
from vault_engine.parsers import Block

from .conftest import fake_vector


def test_recursive_respects_size_and_overlap():
    text = " ".join(f"parola{i}" for i in range(600))
    chunks = split_recursive(text, size=200, overlap=50)
    assert all(len(c) <= 200 for c in chunks)
    # Consecutive chunks share their boundary words.
    assert chunks[0].split()[-1] in chunks[1]


def test_overlap_present_with_ordinary_prose():
    # Paragraphs and sentences longer than the overlap: whole-piece overlap would be empty.
    sentence = "Clausola {n}: il fornitore consegna la merce presso il magazzino indicato nel contratto entro i termini concordati."
    text = "\n\n".join(" ".join(sentence.format(n=p * 3 + s) for s in range(3)) for p in range(4))
    chunks = split_with_overlap(text, 300, 80)
    assert len(chunks) > 3
    assert all(len(c) <= 300 for c in chunks)
    for previous, current in zip(chunks, chunks[1:]):
        shared = next(n for n in range(min(len(previous), len(current)), 0, -1) if previous.endswith(current[:n]))
        assert 20 <= shared <= 80
        assert not current[0].isspace()


def test_overlap_zero_and_short_text():
    assert split_with_overlap("breve testo", 300, 80) == ["breve testo"]
    chunks = split_with_overlap("parola " * 200, 200, 0)
    assert all(len(c) <= 200 for c in chunks)


def test_sections_carry_heading_path_and_pages():
    blocks = [
        Block("Manuale", "heading", 1, level=1),
        Block("Intro.", page=1),
        Block("Sicurezza", "heading", 2, level=2),
        Block("Usare i guanti.", page=2),
        Block("Allegati", "heading", 3, level=1),
        Block("Nessuno.", page=3),
    ]
    sections = build_sections(blocks)
    assert [s.heading_path for s in sections] == [["Manuale"], ["Manuale", "Sicurezza"], ["Allegati"]]


def test_chunk_document_recursive_pages():
    blocks = [Block("Titolo", "heading", 1, level=1)] + [Block("frase " * 60, page=p) for p in (1, 2, 3)]
    chunks = asyncio.run(chunk_document(blocks, ChunkingSettings(chunk_size=400, chunk_overlap=50), None))
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 3
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].embedding_text("Doc").startswith("Doc\nTitolo")


def test_semantic_splits_on_topic_change():
    cats = "Il gatto dorme sul divano. Il gatto mangia croccantini. Il gatto gioca con il gomitolo. Il gatto miagola alla porta."
    tax = "La dichiarazione IVA scade a febbraio. La dichiarazione IVA richiede il codice fiscale. La dichiarazione IVA va trasmessa online."

    async def embed(texts):
        return [fake_vector(t) for t in texts]

    settings = ChunkingSettings(strategy="semantic", chunk_size=2000, min_chunk_size=20, breakpoint_percentile=80)
    chunks = asyncio.run(chunk_document([Block(cats + " " + tax)], settings, embed))
    assert len(chunks) >= 2
    assert "gatto" in chunks[0].text and "IVA" not in chunks[0].text
    assert "IVA" in chunks[-1].text


def test_running_headers_removed():
    blocks = []
    for page in range(1, 6):
        blocks += [Block("ACME S.p.A. - Riservato", page=page), Block(f"Contenuto pagina {page} " * 5, page=page), Block(f"Pagina {page}", page=page)]
    kept = drop_running_headers(blocks)
    assert not any("Riservato" in b.text or b.text.startswith("Pagina") for b in kept)
    assert len(kept) == 5


def test_language_detection():
    assert detect_language("Il contratto è valido per la fornitura di materiali e non prevede che il cliente paghi " * 3) == "it"
    assert detect_language("The contract is valid for the supply of materials and it requires that the customer pays " * 3) == "en"
