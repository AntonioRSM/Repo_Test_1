"""Supervisore: completa tutti i capitoli anche se la pipeline si blocca o va in crash."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import esegui_tutto  # noqa: E402

# Pipeline finta: "blocca" resta appeso per sempre, "crash" muore senza messaggi, "rotto" fallisce con ❌.
FINTA = r'''
import argparse, json, os, sys, time
p = argparse.ArgumentParser()
for a in ("--config", "--lista", "--format", "--normalizzazione", "--input-dir", "--output-dir"):
    p.add_argument(a)
a = p.parse_args()
lista = [r.strip() for r in open(a.lista, encoding="utf-8") if r.strip()]
print("✅ controlli ok", flush=True)
errori = 0
for path in lista:
    nome = os.path.splitext(os.path.basename(path))[0]
    print(f"📖 {nome}", flush=True)
    if "blocca" in nome:
        time.sleep(3600)
    if "crash" in nome:
        os._exit(3)
    if "rotto" in nome:
        print(f"   ❌ {os.path.basename(path)}: errore di prova", flush=True)
        errori += 1
        continue
    open(os.path.join(a.output_dir, nome + "." + a.format), "w").close()
    print(f"   ✅ {nome}", flush=True)
sys.exit(1 if errori else 0)
'''


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    ing, out = tmp_path / "in", tmp_path / "out"
    ing.mkdir()
    out.mkdir()
    for n in ["001", "002_blocca", "003", "004_crash", "005_rotto", "006", "007", "008"]:
        (ing / f"{n}.md").write_text("Testo.")
    (tmp_path / "config.json").write_text(json.dumps({"input_dir": str(ing), "output_dir": str(out)}))
    finta = tmp_path / "pipeline_finta.py"
    finta.write_text(FINTA, encoding="utf-8")
    monkeypatch.setattr(esegui_tutto, "PIPELINE", str(finta))
    monkeypatch.setattr(esegui_tutto, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(esegui_tutto, "STATO_PATH", str(tmp_path / "logs" / "stato.json"))
    return tmp_path, out


def test_arriva_alla_fine_saltando_i_capitoli_problematici(ambiente, monkeypatch, capsys):
    tmp, out = ambiente
    monkeypatch.setattr(sys, "argv", ["esegui_tutto.py", "--config", str(tmp / "config.json"), "--blocco", "3",
                                      "--stallo-min", "0.04", "--intervallo", "0.2", "--tentativi", "2"])
    with pytest.raises(SystemExit) as e:
        esegui_tutto.main()
    assert e.value.code == 1  # alcuni capitoli saltati
    assert sorted(os.listdir(out)) == ["001.mp3", "003.mp3", "006.mp3", "007.mp3", "008.mp3"]
    stato = json.loads((tmp / "logs" / "stato.json").read_text())
    assert stato["falliti"] == {"002_blocca.md": 2, "004_crash.md": 2, "005_rotto.md": 2}
    testo = capsys.readouterr().out
    assert "Nessun avanzamento" in testo and "Finito: 5/8 capitoli" in testo


def test_ripresa_salta_i_gia_fatti(ambiente, monkeypatch):
    tmp, out = ambiente
    for n in ["002_blocca", "004_crash", "005_rotto"]:
        (tmp / "in" / f"{n}.md").unlink()
    (out / "001.mp3").write_text("già fatto")
    monkeypatch.setattr(sys, "argv", ["esegui_tutto.py", "--config", str(tmp / "config.json"), "--intervallo", "0.2"])
    esegui_tutto.main()  # nessuna eccezione: tutto completato
    assert (out / "001.mp3").read_text() == "già fatto"
    assert len(os.listdir(out)) == 5


def test_controlli_iniziali_falliti_fermano_tutto(ambiente, monkeypatch, tmp_path):
    tmp, out = ambiente
    rotta = tmp / "pipeline_rotta.py"
    rotta.write_text("import sys\nprint('❌ F5-TTS non trovato', flush=True)\nsys.exit(1)\n", encoding="utf-8")
    monkeypatch.setattr(esegui_tutto, "PIPELINE", str(rotta))
    monkeypatch.setattr(sys, "argv", ["esegui_tutto.py", "--config", str(tmp / "config.json"), "--intervallo", "0.2"])
    with pytest.raises(SystemExit) as e:
        esegui_tutto.main()
    assert "controlli iniziali" in str(e.value.code)
