"""Test dell'avvio in background usato dagli strumenti MCP genera_audiolibro / stato_audiolibro."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "app"))
import audiobook_job  # noqa: E402

FAKE_PIPELINE = """import sys, time
print("argomenti:", " ".join(sys.argv[1:]))
time.sleep(float(__import__("os").environ.get("FAKE_SLEEP", "0")))
print("Completati 1/1 capitoli.")
sys.exit(int(__import__("os").environ.get("FAKE_EXIT", "0")))
"""


@pytest.fixture
def job(tmp_path, monkeypatch):
    (tmp_path / "audiobook_pipeline.py").write_text(FAKE_PIPELINE)
    monkeypatch.setenv("AUDIOBOOK_DIR", str(tmp_path))
    return audiobook_job.AudiobookJob(log_path=str(tmp_path / "log" / "audiolibro.log"))


def wait(job):
    for _ in range(100):
        if not job.running():
            return
        time.sleep(0.05)


def test_comando(job):
    cmd = job.build_command("capitolo_01.txt", "wav", forza=True, solo_testo=True)
    assert cmd[1:2] == ["-u"]
    assert cmd[-6:] == ["--format", "wav", "--file", "capitolo_01.txt", "--force", "--dry-run"]
    with pytest.raises(ValueError):
        job.build_command(formato="ogg")


def test_script_mancante(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_DIR", str(tmp_path / "vuota"))
    with pytest.raises(FileNotFoundError):
        audiobook_job.AudiobookJob().build_command()


def test_avvio_e_stato(job):
    assert "Nessuna generazione" in job.status()
    msg = job.start("capitolo_01.txt")
    assert "Generazione avviata (capitolo_01.txt, formato mp3)" in msg
    wait(job)
    st = job.status()
    assert st.startswith("Completata con successo.")
    assert "argomenti: --format mp3 --file capitolo_01.txt" in st


def test_errore_e_doppio_avvio(job, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "1")
    monkeypatch.setenv("FAKE_EXIT", "1")
    job.start()
    assert job.start().startswith("Una generazione è già in corso.")
    wait(job)
    assert "Terminata con errori (codice 1)" in job.status()


def test_verifica(job, monkeypatch):
    out = job.check()
    assert "Cartella pipeline:" in out and "argomenti: --check" in out and out.endswith("Tutto pronto.")
    monkeypatch.setenv("FAKE_EXIT", "1")
    assert job.check().endswith("Ci sono problemi da risolvere (righe con ❌).")


def test_ferma_e_pid(job, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "30")
    assert job.stop() == "Nessuna generazione in corso."
    job.start(normalizzazione="regole")
    assert os.path.exists(job.pid_path)
    # un nuovo server MCP (nuova istanza) vede la generazione avviata dal precedente
    altro = audiobook_job.AudiobookJob(log_path=job.log_path)
    assert altro.running() and altro.status().startswith("In corso (avviata da una sessione precedente")
    assert altro.start().startswith("Una generazione è già in corso.")
    assert altro.stop().startswith("Generazione interrotta.")
    wait(job)
    assert not job.running() and not altro.running()


def test_normalizzazione_nel_comando(job):
    assert job.build_command(normalizzazione="regole")[-2:] == ["--normalizzazione", "regole"]
    with pytest.raises(ValueError):
        job.build_command(normalizzazione="altro")
