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



def test_python_env_rocm(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIOBOOK_PYTHON", raising=False)
    monkeypatch.setattr(audiobook_job, "HERE", str(tmp_path))
    assert audiobook_job.pipeline_python() == sys.executable
    exe = tmp_path / "env-rocm" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert audiobook_job.pipeline_python() == sys.executable  # installato ma GPU non verificata
    (tmp_path / "env-rocm" / ".pronto").write_text("")
    assert audiobook_job.pipeline_python() == str(exe)
    monkeypatch.setenv("AUDIOBOOK_PYTHON", "C:/altro/python.exe")
    assert audiobook_job.pipeline_python() == "C:/altro/python.exe"


def test_tts_bridge_torchaudio_senza_torchcodec(monkeypatch):
    import types
    import tts_bridge
    ta = types.SimpleNamespace(__version__="2.9.1+cpu", load=None)
    arr = types.SimpleNamespace(T=types.SimpleNamespace(copy=lambda: "dati"))
    monkeypatch.setitem(sys.modules, "torchaudio", ta)
    monkeypatch.setitem(sys.modules, "torchcodec", None)
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=lambda *a, **k: (arr, 24000)))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(from_numpy=lambda x: f"tensore({x})"))
    tts_bridge.torchaudio_compatibile()
    assert ta.load("voce.wav") == ("tensore(dati)", 24000)


def test_stato_generazione_interrotta(job):
    os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
    with open(job.log_path, "w", encoding="utf-8") as f:
        f.write("📖 000_0001\n   Carico F5-TTS locale\nmodel : model_159600.safetensors\n")
    assert "si è interrotta senza finire" in job.status()
    with open(job.log_path, "a", encoding="utf-8") as f:
        f.write("\nCompletati 1/1 capitoli.\n")
    assert job.status().startswith("Nessuna generazione in corso. Ultimo log disponibile:")


def test_popen_staccato_ripiega(monkeypatch):
    chiamate = []

    def finto_popen(cmd, creationflags=0, **kw):
        chiamate.append(creationflags)
        if len(chiamate) == 1:
            raise OSError("accesso negato: il job non permette il distacco")
        return "processo"

    monkeypatch.setattr(audiobook_job.subprocess, "Popen", finto_popen)
    monkeypatch.setattr(audiobook_job, "_STACCATO", 0x01000200)
    assert audiobook_job._popen_staccato(["python"]) == "processo"
    assert chiamate == [0x01000200, audiobook_job._NO_WINDOW]
