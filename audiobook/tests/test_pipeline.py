"""Test offline della pipeline (nessun LM Studio o F5-TTS reale richiesto).

  pip install pytest
  python -m pytest tests -v
"""
import json
import math
import os
import struct
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import audiobook_pipeline as ap  # noqa: E402

NORMALIZZATO = ("Capitolo quarto, volume secondo. Nel diciannovesimo secolo la biblioteca contava ventotto libri, "
                "pagati cento euro. Luigi Quattordicesimo e Pio Nono. Il quindici maggio millenovecentonovantotto "
                "la squadra conquistò il primo posto; nella seconda gara la barca rimase all'àncora.")


def write_wav(path, seconds=0.5, rate=24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(int(rate * seconds))))


# ---------------------------------------------------------------- server LM Studio finto

class FakeLMStudio(BaseHTTPRequestHandler):
    requests = []
    reply = json.dumps({"paragrafi": [NORMALIZZATO]})

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "qwen3-8b", "object": "model", "owned_by": "me"},
                                               {"id": "text-embedding-nomic", "object": "model", "owned_by": "me"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLMStudio.requests.append(body)
        self._send({"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": FakeLMStudio.reply}}]})


@pytest.fixture
def lmstudio():
    FakeLMStudio.requests = []
    srv = HTTPServer(("127.0.0.1", 0), FakeLMStudio)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


@pytest.fixture
def cfg(tmp_path, lmstudio):
    c = ap.load_config(str(tmp_path / "missing.json"))
    ref = tmp_path / "voce_guida.wav"
    write_wav(ref)
    c.update(input_dir=str(tmp_path / "in"), output_dir=str(tmp_path / "out"), temp_dir=str(tmp_path / "tmp"),
             lmstudio_url=lmstudio, voice_ref_audio=str(ref), voice_ref_text="Buongiorno, questa è la mia voce.",
             output_format="wav")
    os.makedirs(c["input_dir"])
    return c


# ---------------------------------------------------------------- parsing e testo

def test_parse_paragraphs_formati():
    assert ap.parse_paragraphs('["uno.", "due."]') == ["uno.", "due."]
    assert ap.parse_paragraphs('<think>ragiono</think>\n```json\n["a."]\n```') == ["a."]
    assert ap.parse_paragraphs('{"paragrafi": ["x."]}') == ["x."]
    assert ap.parse_paragraphs('Ecco il risultato: ["y."] spero vada bene') == ["y."]
    with pytest.raises(ValueError):
        ap.parse_paragraphs("non è json")


def test_chunk_text_rispetta_limite():
    testo = "\n\n".join(" ".join(["parola"] * 90) + "." for _ in range(20))
    chunks = ap.chunk_text(testo, 300)
    assert all(ap.word_count(c) <= 300 for c in chunks)
    assert sum(ap.word_count(c) for c in chunks) == ap.word_count(testo)


def test_enforce_limits_spezza_e_punteggia():
    frase = " ".join(["parola"] * 50) + "."
    lungo = " ".join([frase] * 8)  # 400 parole
    out = ap.enforce_limits([lungo, "senza punto"], limite=300, massimo=200)
    assert all(ap.word_count(p) <= 200 for p in out[:-1])
    assert out[-1] == "senza punto."


def test_read_text_cp1252(tmp_path):
    p = tmp_path / "c.txt"
    p.write_bytes("perché è così".encode("cp1252"))
    assert ap.read_text(str(p)) == "perché è così"


def test_windows_path_non_viene_reso_relativo():
    with mock.patch("os.path.isdir", return_value=False):
        assert ap._resolve("D:\\Workspace\\epub_build") == "D:\\Workspace\\epub_build"


def test_windows_path_in_wsl():
    with mock.patch("os.name", "posix"), mock.patch("os.path.isdir", return_value=True):
        assert ap._resolve("D:\\Workspace\\epub_build\\testo_x_audio") == "/mnt/d/Workspace/epub_build/testo_x_audio"


# ---------------------------------------------------------------- LM Studio

def test_normalizzazione_via_lmstudio(cfg):
    out = ap.normalizza_testo(cfg, "Capitolo IV, Volume II. Nel XIX secolo 28 libri.")
    assert out == [NORMALIZZATO]
    req = FakeLMStudio.requests[0]
    assert req["model"] == "qwen3-8b"  # esclude i modelli di embedding
    assert req["response_format"]["type"] == "json_schema"
    assert "NUMERI ROMANI" in req["messages"][0]["content"]
    assert "tra 100 e 200 parole" in req["messages"][0]["content"]


def test_verifiche_regole_su_output_corretto(cfg):
    with mock.patch.object(ap, "normalizza_testo", return_value=[NORMALIZZATO]):
        assert ap.test_normalizzazione(cfg)
    with mock.patch.object(ap, "normalizza_testo", return_value=["Luigi XIV vinse 28 gare."]):
        assert not ap.test_normalizzazione(cfg)


def test_check_services(cfg):
    cfg["f5_tts_url"] = "http://127.0.0.1:1/"  # porta chiusa
    cfg["f5_tts_porte"] = []
    assert ap.check_services(cfg, need_tts=False)
    assert not ap.check_services(cfg, need_tts=True)


# ---------------------------------------------------------------- F5-TTS

API_F5_V1 = {"named_endpoints": {"/basic_tts": {"parameters": [{"parameter_name": n} for n in ap.F5_DEFAULT_PARAMS]}}}


def test_parametri_f5(cfg):
    fake = mock.MagicMock()
    fake.view_api.return_value = API_F5_V1
    with mock.patch("gradio_client.Client", return_value=fake):
        tts = ap.F5TTSClient(cfg)
    kw = tts.build_kwargs("Testo.")
    assert kw["gen_text_input"] == "Testo."
    assert kw["ref_text_input"] == "Buongiorno, questa è la mia voce."
    assert kw["nfe_slider"] == 32 and kw["speed_slider"] == 0.95
    assert kw["cross_fade_duration_slider"] == 0.15
    assert kw["remove_silence"] is False and kw["randomize_seed"] is False
    assert "temperature" not in kw  # non esiste in /basic_tts di F5-TTS


def test_pipeline_completa(cfg, tmp_path):
    with open(os.path.join(cfg["input_dir"], "capitolo_01.txt"), "w", encoding="utf-8") as f:
        f.write("Capitolo IV. Testo di prova con 28 libri.")
    FakeLMStudio.reply = json.dumps(["Primo paragrafo.", "Secondo paragrafo.", "Terzo paragrafo."])

    class FakeTTS:
        def synthesize(self, text, out):
            write_wav(out, 1.0)
            return out

    try:
        out = ap.processa_capitolo(cfg, ap.trova_capitoli(cfg, "capitolo_01.txt")[0], tts=FakeTTS())
    finally:
        FakeLMStudio.reply = json.dumps({"paragrafi": [NORMALIZZATO]})
    assert out == os.path.join(cfg["output_dir"], "capitolo_01.wav")
    with wave.open(out) as w:
        durata = w.getnframes() / w.getframerate()
    assert abs(durata - 3.4) < 0.02  # 3 segmenti da 1 s + 2 pause da 200 ms
    assert not os.path.exists(os.path.join(cfg["temp_dir"], "capitolo_01"))  # temporanei cancellati


# ---------------------------------------------------------------- pre-elaborazione deterministica

@pytest.mark.parametrize("n,card,ordn", [
    (1, "uno", "primo"), (4, "quattro", "quarto"), (11, "undici", "undicesimo"), (13, "tredici", "tredicesimo"),
    (19, "diciannove", "diciannovesimo"), (20, "venti", "ventesimo"), (21, "ventuno", "ventunesimo"),
    (23, "ventitré", "ventitreesimo"), (26, "ventisei", "ventiseiesimo"), (28, "ventotto", "ventottesimo"),
    (100, "cento", "centesimo"), (108, "centotto", "centottesimo"), (1000, "mille", "millesimo"),
    (1998, "millenovecentonovantotto", "millenovecentonovantottesimo"),
])
def test_cardinali_ordinali(n, card, ordn):
    assert ap.cardinale(n) == card
    assert ap.ordinale(n) == ordn


def test_romano_a_int():
    assert [ap.romano_a_int(r) for r in ("IV", "IX", "XIII", "XIX", "XXI", "MCMXCVIII")] == [4, 9, 13, 19, 21, 1998]
    with pytest.raises(ValueError):
        ap.romano_a_int("IIII")


def test_converti_romani():
    testo = ("Capitolo IV, Volume II. Nel XIII secolo e nel XIX sec. I secoli bui. Parte II. "
             "Nel capitolo I personaggi. Capitolo I, inizio. Luigi XIV e Pio IX.")
    assert ap.converti_romani(testo) == (
        "Capitolo quarto, Volume secondo. Nel tredicesimo secolo e nel diciannovesimo secolo. I secoli bui. "
        "Parte seconda. Nel capitolo I personaggi. Capitolo primo, inizio. Luigi XIV e Pio IX.")


def test_pulisci_markdown():
    md = ("# Capitolo XIII\n\nTesto con **grassetto**, _corsivo_ e un [link](http://x.it).[^1]\n\n"
          "> Citazione\n\n- voce di elenco\n\n---\n\n![img](a.png)\n```\ncodice\n```\n<br>Fine.")
    assert ap.pulisci_markdown(md) == ("Capitolo XIII.\n\nTesto con grassetto, corsivo e un link.\n\n"
                                       "Citazione\n\nvoce di elenco\n\nFine.")
    assert ap.prepara_testo("## Capitolo XIII") == "Capitolo tredicesimo."


def test_trova_capitoli_txt_e_md(cfg):
    for nome in ("000_0157.md", "001.txt", "note.docx"):
        open(os.path.join(cfg["input_dir"], nome), "w").close()
    assert [os.path.basename(f) for f in ap.trova_capitoli(cfg)] == ["000_0157.md", "001.txt"]


def test_check_services_mostra_percorsi(cfg, capsys):
    open(os.path.join(cfg["input_dir"], "000_0157.md"), "w").close()
    ap.check_services(cfg, need_tts=False)
    out = capsys.readouterr().out
    assert "📁 Configurazione:" in out and f"📁 Input: {cfg['input_dir']} (1 capitoli" in out
    cfg["input_dir"] = cfg["input_dir"] + "_manca"
    assert not ap.check_services(cfg, need_tts=False)
    assert "Cartella di input non trovata" in capsys.readouterr().out


# ---------------------------------------------------------------- ricerca automatica di F5-TTS

def gradio_finto(endpoints):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"dependencies": [{"api_name": e} for e in endpoints] + [{"api_name": None}]}).encode()
            self.send_response(200 if self.path == "/config" else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_trova_f5(cfg, capsys):
    f5, repo_ui = gradio_finto(["basic_tts", "multistyle_tts"]), gradio_finto(["chat", "say"])
    try:
        p_f5, p_ui = f5.server_port, repo_ui.server_port
        cfg["f5_tts_porte"] = [[p_ui, p_ui], [p_f5, p_f5]]  # solo le due porte di prova
        cfg["f5_tts_url"] = f"http://127.0.0.1:{p_f5}/"
        assert ap.trova_f5(cfg) == cfg["f5_tts_url"]  # URL esplicito giusto
        cfg["f5_tts_url"] = "auto"
        assert ap.trova_f5(cfg) == f"http://127.0.0.1:{p_f5}/"
        cfg["f5_tts_url"] = "http://127.0.0.1:42003/"  # porta vecchia: ricerca automatica
        assert ap.trova_f5(cfg) == f"http://127.0.0.1:{p_f5}/"
        assert "trovato su" in capsys.readouterr().out
        cfg["f5_tts_porte"] = [[p_ui, p_ui]]  # solo l'interfaccia senza /basic_tts
        assert ap.trova_f5(cfg) is None
        assert "senza /basic_tts" in capsys.readouterr().out
    finally:
        f5.shutdown()
        repo_ui.shutdown()
