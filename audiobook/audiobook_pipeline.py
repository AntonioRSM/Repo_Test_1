"""Pipeline audiolibri: capitoli .txt/.md -> LM Studio (normalizzazione) -> F5-TTS su Pinokio -> MP3/WAV.

1. LM Studio (API compatibile OpenAI) normalizza il testo italiano per la sintesi
   vocale (numeri arabi/romani, date, accenti sugli omografi) e lo divide in
   paragrafi da 100-200 parole, restituiti come array JSON.
2. F5-TTS (interfaccia Gradio avviata da Pinokio) genera un WAV per ogni paragrafo
   tramite gradio_client: 001_paragrafo.wav, 002_paragrafo.wav, ...
3. pydub concatena i segmenti con 200 ms di silenzio ed esporta il capitolo.

Uso:
  python audiobook_pipeline.py --check                      # LM Studio e F5-TTS raggiungibili?
  python audiobook_pipeline.py --test-normalizzazione       # verifica le regole su test_normalizzazione.txt
  python audiobook_pipeline.py                              # tutti i .txt/.md di input_dir
  python audiobook_pipeline.py --file capitolo_01.txt       # un solo capitolo
  python audiobook_pipeline.py --dry-run                    # solo normalizzazione (niente audio)

La configurazione è in config.json (accanto a questo file).
"""
import argparse
import glob
import json
import os
import re
import shutil
import socket
import sys
import time
import urllib.request
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
TEST_TXT = os.path.join(HERE, "test_normalizzazione.txt")
# App "F5-TTS + LM Studio" di questo repo: il suo F5-TTS installato e la sua voce predefinita
APP_DIR = os.environ.get("F5_APP_DIR") or os.path.join(os.path.dirname(HERE), "app")

# Configurazione default (sovrascritta da config.json)
LM_STUDIO_URL = "http://localhost:1234/v1"
F5_TTS_URL = "auto"  # "auto" = cerca il server F5-TTS sulle porte locali (Pinokio le cambia a ogni avvio)
VOICE_REF_AUDIO = "voce_guida.wav"
VOICE_REF_TEXT = "Trascrizione esatta del file audio di riferimento."
PAUSA_PARAGRAFO_MS = 200  # 0.2 secondi come da requisiti
# Modello per F5-TTS locale se l'app non ha un config.json (stesso di app/detect_hardware.py)
F5_LOCALE_IT = {
    "name": "F5-TTS Base @ it (alien79)",
    "model": "F5TTS_Base",
    "ckpt_file": "hf://alien79/F5-TTS-italian/model_159600.safetensors",
    "vocab_file": "hf://alien79/F5-TTS-italian/vocab.txt",
    "device": "",
}

DEFAULTS = {
    "input_dir": "capitoli_input",
    "input_ext": [".txt", ".md"],
    "output_dir": "audiolibri_output",
    "temp_dir": "temp_segments",
    "output_format": "mp3",
    "mp3_bitrate": "192k",
    "pausa_paragrafo_ms": PAUSA_PARAGRAFO_MS,
    "skip_existing": True,
    "keep_temp": False,
    "ffmpeg_path": "",
    "lmstudio_url": LM_STUDIO_URL,
    "lmstudio_model": "",
    "llm_temperature": 0.1,
    "llm_max_tokens": 8192,
    "llm_chunk_words": 700,
    "llm_json_schema": True,
    "llm_retries": 2,
    "llm_timeout": 300,  # secondi per richiesta (poi un nuovo tentativo, con messaggio nel log)
    "llm_no_think": True,  # "/no_think": i modelli che ragionano (Qwen3) rispondono subito
    "normalizzazione": "llm",  # llm = LM Studio | regole = solo regole deterministiche (molto più veloce)
    "tts_backend": "auto",  # auto | gradio | locale
    "f5_tts_url": F5_TTS_URL,
    "f5_tts_porte": [[7860, 7880], [42000, 42300]],
    "f5_api_name": "/basic_tts",
    "voice_ref_audio": VOICE_REF_AUDIO,
    "voice_ref_text": VOICE_REF_TEXT,
    "nfe_step": 32,
    "temperature": 0.65,
    "speed": 0.95,
    "cross_fade_duration": 0.15,
    "remove_silence": False,
    "seed": 42,
    "tts_retries": 2,
    "parole_min": 100,
    "parole_max": 200,
    "parole_limite": 300,
}

# System prompt rigoroso per normalizzazione
SYSTEM_PROMPT_NORMALIZER = """Sei un editor esperto per audiolibri italiani.
Il tuo compito è trasformare il testo fornito rendendolo perfetto per la sintesi vocale TTS.
Riporta TUTTO il testo: non riassumere, non omettere, non aggiungere e non riformulare frasi.
Modifica solo ciò che le regole richiedono.
Applica queste regole fondamentali:
1. NUMERI ARABI:
   - Converti cardinali in parole (es. "28 libri" -> "ventotto libri", "100 euro" -> "cento euro").
   - Converti ordinali considerando il genere (es. "1° posto" -> "primo posto", "2° gara" -> "seconda gara").
   - Converti date ed anni (es. "15/05/1998" -> "quindici maggio millenovecentonovantotto").
2. NUMERI ROMANI:
   - Secoli in ordinali (es. "XIX secolo" -> "diciannovesimo secolo").
   - Sovrani/Papi in ordinali (es. "Luigi XIV" -> "Luigi Quattordicesimo", "Pio IX" -> "Pio Nono").
   - Capitoli/Volumi in esteso (es. "Capitolo IV, Volume II" -> "Capitolo quarto, volume secondo").
3. ACCENTI E PUNTEGGIATURA:
   - Aggiungi accento fonetico sulle parole omografe se trasmettono significato diverso (es. àncora/ancóra, sùbito/subìto, prìncipi/princìpi).
   - Assicurati che ogni paragrafo termini con un punto fermo o punteggiatura forte (. ! ? …).
4. LUNGHEZZA:
   - Dividi il testo in paragrafi compresi tra {min} e {max} parole ciascuno (mai oltre {limite}), spezzando solo a fine frase.
5. FORMATO:
   - Niente markdown, titoli con #, elenchi puntati, note o commenti tuoi.

RESTITUISCI ESCLUSIVAMENTE UN ARRAY JSON DI STRINGHE (I PARAGRAFI). Esempio: ["Paragrafo uno...", "Paragrafo due..."]"""

JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "paragrafi_audiolibro",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"paragrafi": {"type": "array", "items": {"type": "string"}}},
            "required": ["paragrafi"],
        },
    },
}

# Nomi logici -> possibili nomi del parametro nell'endpoint Gradio /basic_tts
# (cambiano tra le versioni di F5-TTS: si usano quelli che il server dichiara).
F5_PARAM_ALIASES = {
    "ref_audio": ["ref_audio_input", "ref_audio"],
    "ref_text": ["ref_text_input", "ref_text"],
    "gen_text": ["gen_text_input", "gen_text"],
    "remove_silence": ["remove_silence"],
    "randomize_seed": ["randomize_seed"],
    "seed": ["seed_input", "seed"],
    "cross_fade_duration": ["cross_fade_duration_slider", "cross_fade_duration"],
    "nfe_step": ["nfe_slider", "nfe_step"],
    "speed": ["speed_slider", "speed"],
    "temperature": ["temperature", "temperature_slider"],
}
# Firma di basic_tts in F5-TTS 1.x, usata se il server non espone la descrizione dell'API
F5_DEFAULT_PARAMS = ["ref_audio_input", "ref_text_input", "gen_text_input", "remove_silence",
                     "randomize_seed", "seed_input", "cross_fade_duration_slider", "nfe_slider", "speed_slider"]


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- configurazione

def _resolve(path):
    path = os.path.expandvars(os.path.expanduser(path))
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if m:
        # D:\Workspace\... usato da Linux/WSL (es. Hermes Agent in WSL2) -> /mnt/d/Workspace/...
        wsl = f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/")
        return wsl if os.name != "nt" and os.path.isdir(f"/mnt/{m.group(1).lower()}") else path
    return path if os.path.isabs(path) else os.path.join(HERE, path)


def load_config(path=CONFIG_PATH):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    cfg["lmstudio_url"] = os.environ.get("LMSTUDIO_URL", cfg["lmstudio_url"]).rstrip("/")
    cfg["f5_tts_url"] = os.environ.get("F5_TTS_URL", cfg["f5_tts_url"])
    for key in ("input_dir", "output_dir", "temp_dir", "voice_ref_audio"):
        cfg[key] = _resolve(cfg[key])
    cfg["config_path"] = os.path.abspath(path)
    return cfg


def conta_capitoli(cfg):
    estensioni = cfg.get("input_ext") or [".txt", ".md"]
    try:
        return sum(os.path.splitext(f)[1].lower() in estensioni for f in os.listdir(cfg["input_dir"]))
    except OSError:
        return None


# ---------------------------------------------------------------- verifiche

def port_open(url, timeout=3):
    u = urlparse(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        with socket.create_connection((u.hostname or "127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def gradio_endpoints(url, timeout=3):
    """Nomi degli endpoint API di un server Gradio (dalla sua /config), None se non è Gradio."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # server locale: niente proxy
        with opener.open(url.rstrip("/") + "/config", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    return {str(d.get("api_name")).lstrip("/") for d in data.get("dependencies", []) if d.get("api_name")}


def trova_f5(cfg):
    """Restituisce l'URL del server Gradio che espone l'endpoint di F5-TTS (/basic_tts).

    Usa f5_tts_url se risponde con quell'endpoint; altrimenti (o con "auto") prova le porte
    locali in f5_tts_porte, perché Pinokio assegna una porta diversa a ogni avvio.
    """
    api = cfg["f5_api_name"].lstrip("/")
    url = (cfg.get("f5_tts_url") or "auto").strip()
    if url.lower() != "auto":
        eps = gradio_endpoints(url) if port_open(url, timeout=1) else None
        if eps is not None and api in eps:
            return url
    senza_api = []
    for inizio, fine in cfg.get("f5_tts_porte") or []:
        for porta in range(int(inizio), int(fine) + 1):
            cand = f"http://127.0.0.1:{porta}/"
            if not port_open(cand, timeout=0.05):
                continue
            eps = gradio_endpoints(cand)
            if eps is None:
                continue
            if api in eps:
                if url.lower() != "auto":
                    log(f"ℹ️ F5-TTS non è su {url}: trovato su {cand}")
                return cand
            senza_api.append(cand)
    if senza_api:
        log(f"⚠️ Server Gradio senza /{api} su {', '.join(senza_api)}: non è l'app F5-TTS ufficiale "
            "(probabilmente l'interfaccia 'F5-TTS + LM Studio' di questo repo).")
    return None


def app_config():
    try:
        with open(os.path.join(APP_DIR, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def f5_locale_disponibile():
    import importlib.util

    return importlib.util.find_spec("f5_tts") is not None


def risolvi_voce(cfg):
    """voce_guida.wav, altrimenti la voce predefinita salvata nell'app (app/voices/voce_riferimento.wav).

    Una trascrizione vuota o ancora segnaposto diventa "": F5-TTS la ricava da solo con Whisper.
    Restituisce True se c'è una voce utilizzabile.
    """
    testo = cfg["voice_ref_text"].strip()
    if not os.path.exists(cfg["voice_ref_audio"]):
        voce_app = os.path.join(APP_DIR, "voices", "voce_riferimento.wav")
        if not os.path.exists(voce_app):
            log(f"❌ Voce di riferimento mancante: {cfg['voice_ref_audio']} (WAV di 6-10 s di parlato pulito), "
                f"e nessuna voce predefinita salvata nell'app ({voce_app}).")
            return False
        log(f"ℹ️ {os.path.basename(cfg['voice_ref_audio'])} non trovato: uso la voce predefinita dell'app {voce_app}")
        cfg["voice_ref_audio"] = voce_app
        testo = (app_config().get("ref_text") or "").strip()
    if testo in ("", VOICE_REF_TEXT):
        log("⚠️ Trascrizione della voce di riferimento assente: F5-TTS la ricava da solo (Whisper). "
            "Per una voce più fedele scrivi la trascrizione ESATTA in voice_ref_text.")
        testo = ""
    cfg["voice_ref_text"] = testo
    log(f"✅ Voce di riferimento: {cfg['voice_ref_audio']}")
    return True


def check_services(cfg, need_tts=True):
    ok = True
    log(f"📁 Configurazione: {cfg['config_path']}")
    n = conta_capitoli(cfg)
    if n is None:
        log(f"❌ Cartella di input non trovata: {cfg['input_dir']} (input_dir in config.json)")
        ok = False
    else:
        log(f"📁 Input: {cfg['input_dir']} ({n} capitoli {'/'.join(cfg.get('input_ext') or ['.txt', '.md'])})")
    log(f"📁 Output: {cfg['output_dir']}")
    if cfg.get("normalizzazione") == "regole":
        log("✅ Normalizzazione a regole: LM Studio non serve")
    elif port_open(cfg["lmstudio_url"]):
        try:
            models = list_models(cfg)
            log(f"✅ LM Studio raggiungibile su {cfg['lmstudio_url']} — modelli: {', '.join(models) or 'nessuno caricato'}")
            if not models:
                log("   ⚠️ Carica un modello LLM in LM Studio.")
                ok = False
        except Exception as e:
            log(f"❌ LM Studio risponde sulla porta ma l'API fallisce: {e}")
            ok = False
    else:
        log(f"❌ LM Studio non raggiungibile su {cfg['lmstudio_url']}: LM Studio > Developer > Start Server (porta 1234).")
        ok = False
    if need_tts:
        backend = (cfg.get("tts_backend") or "auto").lower()
        trovato = trova_f5(cfg) if backend in ("auto", "gradio") else None
        if trovato:
            cfg["f5_tts_url"], cfg["_backend"] = trovato, "gradio"
            log(f"✅ F5-TTS (Gradio {cfg['f5_api_name']}) raggiungibile su {trovato}")
        elif backend in ("auto", "locale") and f5_locale_disponibile():
            cfg["_backend"] = "locale"
            device, nome = dispositivo_torch()
            log(f"✅ F5-TTS locale su {nome} ({device}): il modello viene caricato da questo script "
                "(non serve l'app F5-TTS ufficiale)")
            if device == "cpu":
                log("   ⚠️ Nessuna GPU visibile a PyTorch in questo Python: la sintesi sarà lenta.")
            log(f"   Python: {sys.executable}")
        else:
            if backend == "locale":
                log("❌ tts_backend è 'locale' ma f5-tts non è installato in questo Python: usa quello dell'app "
                    "(app\\env\\Scripts\\python) o installa f5-tts.")
            else:
                log(f"❌ F5-TTS non trovato (f5_tts_url: {cfg['f5_tts_url']}, porte provate: {cfg.get('f5_tts_porte')}) "
                    "e f5-tts non installato in questo Python: avvia l'app F5-TTS in Pinokio o usa il Python dell'app.")
            ok = False
        ok = risolvi_voce(cfg) and ok
    return ok


# ---------------------------------------------------------------- testo

def read_text(path):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Codifica non riconosciuta: {path}")


def pulisci_markdown(text):
    """Toglie la sintassi Markdown (i file .md) che il TTS leggerebbe o che confonde l'LLM."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->|<[^>\n]+>", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # immagini
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # link -> testo
    text = re.sub(r"\[\^[^\]]+\]", "", text)  # richiami di nota
    text = re.sub(r"^[ \t]{0,3}(?:[-*_][ \t]*){3,}$", "", text, flags=re.M)  # righe orizzontali
    # titoli: "# Capitolo IV" -> "Capitolo IV." (pausa dopo il titolo)
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$",
                  lambda m: m.group(1) if re.search(r"[.!?…:;]$", m.group(1)) else m.group(1) + ".", text, flags=re.M)
    text = re.sub(r"^[ \t]{0,3}>[ \t]?", "", text, flags=re.M)  # citazioni
    text = re.sub(r"^[ \t]*(?:[-*+]|\d{1,3}[.)])[ \t]+", "", text, flags=re.M)  # elenchi
    text = re.sub(r"(\*{1,3}|_{1,3})(\S(?:.*?\S)?)\1", r"\2", text)  # corsivo/grassetto
    text = text.replace("`", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Numeri romani -> ordinali italiani, convertiti prima dell'LLM (i modelli piccoli sbagliano,
# es. "XIII secolo" -> "zerosimo"). Solo dopo parole che li rendono inequivocabili.
_ROMANO = r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
_ROMANI = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_UNITA = ["", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci",
          "undici", "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove"]
_DECINE = ["", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta"]
_ORDINALI = ["", "primo", "secondo", "terzo", "quarto", "quinto", "sesto", "settimo", "ottavo", "nono", "decimo"]


def romano_a_int(r):
    r = r.upper()
    if not r or not re.fullmatch(_ROMANO, r):
        raise ValueError(f"Numero romano non valido: {r}")
    tot = 0
    for a, b in zip(r, r[1:] + " "):
        v = _ROMANI[a]
        tot += -v if b != " " and _ROMANI[b] > v else v
    return tot


def cardinale(n):
    """Cardinale italiano (zero, ventuno, ventitré, centotto, milleduecento, due milioni...)."""
    if n == 0:
        return "zero"
    if n >= 1_000_000_000:
        g, r = divmod(n, 1_000_000_000)
        testa = "un miliardo" if g == 1 else cardinale(g) + " miliardi"
        return testa + (" " + cardinale(r) if r else "")
    if n >= 1_000_000:
        m, r = divmod(n, 1_000_000)
        testa = "un milione" if m == 1 else cardinale(m) + " milioni"
        return testa + (" " + cardinale(r) if r else "")
    if n >= 1000:
        m, r = divmod(n, 1000)
        return ("mille" if m == 1 else cardinale(m) + "mila") + (cardinale(r) if r else "")
    if n >= 100:
        c, r = divmod(n, 100)
        testa = "cento" if c == 1 else _UNITA[c] + "cento"
        coda = cardinale(r) if r else ""
        return (testa[:-1] if coda.startswith("o") else testa) + coda
    if n < 20:
        return _UNITA[n]
    d, u = divmod(n, 10)
    decina = _DECINE[d][:-1] if u in (1, 8) else _DECINE[d]
    return decina + ("tré" if u == 3 else _UNITA[u])


def ordinale(n, femminile=False):
    if n <= 10:
        w = _ORDINALI[n]
    else:
        c = cardinale(n)
        if c.endswith("tré"):
            w = c[:-1] + "eesimo"  # ventitreesimo
        elif c.endswith("sei"):
            w = c + "esimo"  # ventiseiesimo
        else:
            w = c[:-1] + "esimo"  # ventunesimo, centesimo, millesimo
    return w[:-1] + "a" if femminile else w


_NOMI_FEMMINILI = {"parte", "sezione"}


def converti_romani(text):
    """XIX secolo -> diciannovesimo secolo; Capitolo IV -> Capitolo quarto; Parte II -> Parte seconda.

    "I" è anche l'articolo ("I secoli bui", "nel capitolo I personaggi"): viene convertito
    solo davanti a "secolo" o se dopo il titolo c'è punteggiatura o fine riga.
    """
    def secolo(m):
        if not m.group(1) or (m.group(1) == "I" and m.group(2) != "secolo"):
            return m.group(0)
        nome = m.group(2)
        if nome == "sec.":  # il punto dell'abbreviazione può chiudere anche la frase
            nome = "secolo." if re.match(r"\s*(?:[A-ZÀ-Ý«“\"]|$)", m.string[m.end():]) else "secolo"
        return f"{ordinale(romano_a_int(m.group(1)))} {nome}"

    def titolo(m):
        if not m.group(2):
            return m.group(0)
        if m.group(2).upper() == "I" and not re.match(r"[ \t]*(?:[.,;:!?)\]»”\"—–-]|$)", m.string[m.end():], flags=re.M):
            return m.group(0)
        n = romano_a_int(m.group(2))
        return f"{m.group(1)} {ordinale(n, m.group(1).lower() in _NOMI_FEMMINILI)}"

    text = re.sub(rf"\b({_ROMANO})\s+(secolo|secoli|sec\.)", secolo, text)
    return re.sub(rf"\b(capitolo|volume|libro|tomo|parte|canto|atto|scena|sezione)\s+({_ROMANO})\b(?![\w'’])",
                  titolo, text, flags=re.I)


_MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
         "settembre", "ottobre", "novembre", "dicembre"]
# Parole che dopo il nome indicano un sovrano/papa: "Luigi XIV", "Pio IX", "Carlo V"
_ROMANO_SOVRANO = r"(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
_NON_NOMI = {"capitolo", "volume", "libro", "tomo", "parte", "canto", "atto", "scena", "sezione", "secolo",
             "secoli", "vitamina", "classe", "tipo", "serie", "fase", "livello", "gruppo", "punto", "articolo"}


def _intero(txt):
    return int(txt.replace(".", "").replace("\u2009", "").replace(" ", ""))


def converti_numeri(text):
    """Numeri arabi in parole, senza LLM: date, ordinali (1°, 2ª), percentuali, euro, decimali, migliaia."""
    def data(m):
        g, me, a = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= g <= 31 and 1 <= me <= 12):
            return m.group(0)
        anno = int(a) if len(a) == 4 else 1900 + int(a) if int(a) >= 30 else 2000 + int(a)
        return f"{'primo' if g == 1 else cardinale(g)} {_MESI[me]} {cardinale(anno)}"

    def ordin(m):
        n, segno, dopo = int(m.group(1)), m.group(2), m.group(3) or ""
        parola = dopo.strip().lower()
        fem = segno in "ªa" or (segno in "°º" and parola.endswith("a") and not parola.endswith("ma"))
        return ordinale(n, fem) + dopo if 0 < n < 10_000 else m.group(0)

    def decimale(m):
        return f"{cardinale(_intero(m.group(1)))} virgola {' '.join(cardinale(int(c)) for c in m.group(2))}" \
            if len(m.group(2)) > 2 else f"{cardinale(_intero(m.group(1)))} virgola {cardinale(int(m.group(2)))}"

    text = re.sub(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b", data, text)
    text = re.sub(r"\b(\d{1,4})\s?([°ºª])(\s+[A-Za-zÀ-ÿ]+)?", ordin, text)
    text = re.sub(r"€\s?(\d[\d.]*(?:,\d+)?)", r"\1 euro", text)
    text = re.sub(r"(\d)\s?%", r"\1 per cento", text)
    text = re.sub(r"\b(\d{1,3}(?:\.\d{3})+|\d+),(\d+)\b", decimale, text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{3})+\b", lambda m: cardinale(_intero(m.group(0))), text)
    return re.sub(r"\b\d{1,12}\b", lambda m: cardinale(int(m.group(0))), text)


def converti_sovrani(text):
    """Luigi XIV -> Luigi Quattordicesimo, Pio IX -> Pio Nono (nome maiuscolo + numero romano)."""
    def sost(m):
        nome, rom = m.group(1), m.group(2)
        if nome.lower() in _NON_NOMI or rom in ("C", "D", "L", "M"):
            return m.group(0)
        if rom == "I" and not re.match(r"[ \t]*(?:[.,;:!?)\]»”\"—–-]|$|\s+(?:di|d'|e|il|la|re|papa)\b)",
                                      m.string[m.end():], flags=re.M):
            return m.group(0)  # "I" come articolo: "Carlo I personaggi" resta invariato
        return f"{nome} {ordinale(romano_a_int(rom)).capitalize()}"

    return re.sub(rf"\b([A-ZÀ-Ý][a-zà-ÿ]+)\s+({_ROMANO_SOVRANO})\b(?![\w'’])",
                  lambda m: sost(m) if m.group(2) else m.group(0), text)


def dividi_paragrafi(text, minimo, massimo):
    """Paragrafi da minimo-massimo parole, spezzando solo a fine frase (senza LLM)."""
    pezzi = []
    for par in re.split(r"\n\s*\n", text):
        par = re.sub(r"\s+", " ", par).strip()
        if par and not re.search(r"[.!?…:;][»”\"')]*$", par):
            par += "."  # titoli e righe senza punto: pausa prima del testo che segue
        if par:
            pezzi += split_sentences(par) if word_count(par) > massimo else [par]
    out, cur = [], []
    for pz in pezzi:
        if cur and word_count(" ".join(cur + [pz])) > massimo:
            out.append(" ".join(cur))
            cur = []
        cur.append(pz)
        if word_count(" ".join(cur)) >= minimo:
            out.append(" ".join(cur))
            cur = []
    if cur:
        if out and word_count(out[-1] + " " + " ".join(cur)) <= massimo:
            out[-1] += " " + " ".join(cur)
        else:
            out.append(" ".join(cur))
    return out


def normalizza_regole(cfg, testo):
    """Normalizzazione completa senza LLM (niente accenti sugli omografi, che richiedono il contesto)."""
    testo = converti_numeri(converti_sovrani(prepara_testo(testo)))
    return enforce_limits(dividi_paragrafi(testo, cfg["parole_min"], cfg["parole_max"]),
                          cfg["parole_limite"], cfg["parole_max"])


def prepara_testo(text):
    """Pulizia deterministica prima dell'LLM: Markdown e numeri romani inequivocabili."""
    return converti_romani(pulisci_markdown(text))


def word_count(text):
    return len(text.split())


def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?…»”\"])\s+", text.strip()) if s]


def chunk_text(text, max_words):
    """Divide il capitolo in blocchi da ~max_words parole (a fine paragrafo o frase) per il contesto dell'LLM."""
    units = []
    for par in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
        par = re.sub(r"\s+", " ", par).strip()
        if not par:
            continue
        units += split_sentences(par) if word_count(par) > max_words else [par]
    chunks, cur, n = [], [], 0
    for u in units:
        w = word_count(u)
        if cur and n + w > max_words:
            chunks.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(u)
        n += w
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def parse_paragraphs(content):
    """Estrae l'array di paragrafi dalla risposta dell'LLM (tollera <think>, ```json e oggetti {"paragrafi": [...]})."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    candidates = [content]
    m = re.search(r"\[.*\]", content, flags=re.S)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data = data.get("paragrafi") or next((v for v in data.values() if isinstance(v, list)), None)
        if isinstance(data, list) and data and all(isinstance(p, str) for p in data):
            return [p.strip() for p in data if p.strip()]
    raise ValueError(f"Risposta dell'LLM non è un array JSON di stringhe: {content[:300]!r}")


def enforce_limits(paragraphs, limite, massimo):
    """Spezza a fine frase i paragrafi oltre il limite e garantisce la punteggiatura finale."""
    out = []
    for p in paragraphs:
        p = re.sub(r"\s+", " ", p).strip()
        if word_count(p) > limite:
            cur = []
            for s in split_sentences(p):
                if cur and word_count(" ".join(cur + [s])) > massimo:
                    out.append(" ".join(cur))
                    cur = []
                cur.append(s)
            if cur:
                out.append(" ".join(cur))
        else:
            out.append(p)
    return [p if re.search(r"[.!?…][»”\"')]*$", p) else p + "." for p in out]


# ---------------------------------------------------------------- LM Studio

def lm_client(cfg):
    from openai import OpenAI

    # max_retries=0: i nuovi tentativi li gestisce normalizza_blocco, scrivendoli nel log
    return OpenAI(base_url=cfg["lmstudio_url"], api_key="lm-studio", timeout=float(cfg["llm_timeout"]), max_retries=0)


def list_models(cfg):
    return [m.id for m in lm_client(cfg).models.list().data if "embed" not in m.id.lower()]


def pick_model(cfg):
    if cfg.get("lmstudio_model"):
        return cfg["lmstudio_model"]
    models = list_models(cfg)
    if not models:
        raise RuntimeError("LM Studio è attivo ma nessun modello LLM è caricato.")
    cfg["lmstudio_model"] = models[0]
    return models[0]


def normalizza_blocco(cfg, client, testo):
    prompt = SYSTEM_PROMPT_NORMALIZER.format(min=cfg["parole_min"], max=cfg["parole_max"], limite=cfg["parole_limite"])
    if cfg.get("llm_no_think"):
        prompt += "\n/no_think"
    kwargs = dict(
        model=pick_model(cfg),
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo}],
        temperature=cfg["llm_temperature"],
        max_tokens=cfg["llm_max_tokens"],
    )
    last = None
    for attempt in range(cfg["llm_retries"] + 1):
        use_schema = cfg["llm_json_schema"] and attempt == 0
        t0 = time.time()
        try:
            resp = client.chat.completions.create(**kwargs, **({"response_format": JSON_SCHEMA} if use_schema else {}))
            out = parse_paragraphs(resp.choices[0].message.content or "")
            log(f"   LM Studio ha risposto in {time.time() - t0:.0f} s")
            return out
        except Exception as e:  # schema non supportato, JSON malformato, timeout...
            last = e
            log(f"   ⚠️ Tentativo {attempt + 1} di normalizzazione fallito dopo {time.time() - t0:.0f} s: {e}")
    raise RuntimeError(f"Normalizzazione non riuscita: {last}")


def normalizza_testo(cfg, testo):
    if cfg.get("normalizzazione") == "regole":
        paragrafi = normalizza_regole(cfg, testo)
        log(f"   Normalizzazione a regole (senza LLM): {len(paragrafi)} paragrafi")
        return paragrafi
    client = lm_client(cfg)
    testo = prepara_testo(testo)
    chunks = chunk_text(testo, cfg["llm_chunk_words"])
    paragraphs = []
    for i, chunk in enumerate(chunks, 1):
        log(f"   LM Studio: blocco {i}/{len(chunks)} ({word_count(chunk)} parole)")
        out = normalizza_blocco(cfg, client, chunk)
        ratio = word_count(" ".join(out)) / max(word_count(chunk), 1)
        if ratio < 0.85:
            log(f"   ⚠️ Il blocco {i} normalizzato ha il {ratio:.0%} delle parole originali: l'LLM potrebbe aver tagliato testo.")
        paragraphs += out
    paragraphs = enforce_limits(paragraphs, cfg["parole_limite"], cfg["parole_max"])
    residui = [p[:60] for p in paragraphs if re.search(r"\d", p)]
    if residui:
        log(f"   ⚠️ Cifre ancora presenti in {len(residui)} paragrafi (es. {residui[0]!r}...)")
    return paragraphs


# ---------------------------------------------------------------- F5-TTS locale (senza Gradio)

def dispositivo_torch():
    """("cuda", nome GPU) se PyTorch vede una GPU (NVIDIA CUDA o AMD ROCm), altrimenti ("cpu", "CPU")."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", torch.cuda.get_device_name(0)
        if torch.backends.mps.is_available():
            return "mps", "Apple Silicon"
    except Exception:
        pass
    return "cpu", "CPU"


def _torchaudio_compatibile():
    """torchaudio >= 2.9 (es. le build ROCm per Windows) legge l'audio solo con torchcodec: se manca, soundfile."""
    try:
        import torchaudio
        versione = tuple(int(x) for x in re.findall(r"\d+", torchaudio.__version__)[:2])
    except Exception:
        return
    if versione < (2, 9):
        return
    try:
        import torchcodec  # noqa: F401
        return
    except Exception:
        pass
    import soundfile as sf
    import torch

    def load(path, *a, **k):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), sr

    torchaudio.load = load


class LocalF5TTS:
    """F5-TTS caricato in questo processo con il modello dell'app (app/config.json) o quello italiano.

    Il dispositivo è scelto qui (GPU se PyTorch la vede): il "device" di app/config.json può essere "cpu"
    solo perché l'app è stata installata con PyTorch per CPU.
    """

    def __init__(self, cfg):
        from cached_path import cached_path
        from f5_tts.api import F5TTS

        self.cfg = cfg
        _torchaudio_compatibile()
        t = {**F5_LOCALE_IT, **(app_config().get("tts") or {})}
        t["device"] = ""
        t.update(cfg.get("f5_locale") or {})
        device, nome = (t["device"], t["device"]) if t["device"] else dispositivo_torch()
        ckpt = str(cached_path(t["ckpt_file"])) if t.get("ckpt_file") else ""
        vocab = str(cached_path(t["vocab_file"])) if t.get("vocab_file") else ""
        log(f"   Carico F5-TTS locale: {t.get('name') or t['model']} su {nome} ({device})")
        if device == "cpu":
            log("   ⚠️ Sintesi su CPU: molto lenta. Con una GPU AMD Ryzen AI / Radeon usa in Pinokio "
                "'Accelerazione GPU AMD (ROCm)'.")
        self.tts = F5TTS(model=t["model"], ckpt_file=ckpt, vocab_file=vocab, device=device)

    def synthesize(self, text, out_path):
        c = self.cfg
        self.tts.infer(
            ref_file=c["voice_ref_audio"],
            ref_text=c["voice_ref_text"],  # "" = trascrizione automatica
            gen_text=text,
            show_info=lambda *a, **k: None,
            nfe_step=int(c["nfe_step"]),
            speed=float(c["speed"]),
            cross_fade_duration=float(c["cross_fade_duration"]),
            remove_silence=bool(c["remove_silence"]),
            seed=int(c["seed"]),
            file_wave=out_path,
        )
        return out_path


def crea_tts(cfg):
    return LocalF5TTS(cfg) if cfg.get("_backend") == "locale" else F5TTSClient(cfg)


# ---------------------------------------------------------------- F5-TTS (Gradio su Pinokio)

class F5TTSClient:
    def __init__(self, cfg):
        from gradio_client import Client

        self.cfg = cfg
        self.client = Client(cfg["f5_tts_url"], verbose=False)
        self.params = self._endpoint_params()
        extra = [k for k in ("temperature",) if not self._name(k)]
        if extra:
            log(f"   ℹ️ Il server F5-TTS non espone {', '.join(extra)} su {cfg['f5_api_name']}: parametro ignorato "
                "(F5-TTS è un modello flow-matching, non campiona con temperatura).")

    def _endpoint_params(self):
        try:
            api = self.client.view_api(print_info=False, return_format="dict")
            ep = api["named_endpoints"][self.cfg["f5_api_name"]]
            return [p.get("parameter_name") or p.get("label") for p in ep["parameters"]]
        except Exception as e:
            log(f"   ⚠️ Descrizione API non disponibile ({e}): uso la firma di F5-TTS 1.x.")
            return list(F5_DEFAULT_PARAMS)

    def _name(self, logical):
        return next((a for a in F5_PARAM_ALIASES[logical] if a in self.params), None)

    def build_kwargs(self, text):
        from gradio_client import handle_file

        c = self.cfg
        values = {
            "ref_audio": handle_file(c["voice_ref_audio"]),
            "ref_text": c["voice_ref_text"],
            "gen_text": text,
            "remove_silence": bool(c["remove_silence"]),  # False: conserva le pause della punteggiatura
            "randomize_seed": False,  # seed fisso = timbro coerente tra i paragrafi
            "seed": int(c["seed"]),
            "cross_fade_duration": float(c["cross_fade_duration"]),
            "nfe_step": int(c["nfe_step"]),
            "speed": float(c["speed"]),
            "temperature": float(c["temperature"]),
        }
        kwargs = {self._name(k): v for k, v in values.items() if self._name(k)}
        missing = [k for k in ("ref_audio", "ref_text", "gen_text") if not self._name(k)]
        if missing:
            raise RuntimeError(f"L'endpoint {c['f5_api_name']} non ha i parametri {missing}. Parametri: {self.params}")
        return kwargs

    def synthesize(self, text, out_path):
        kwargs = self.build_kwargs(text)
        last = None
        for attempt in range(self.cfg["tts_retries"] + 1):
            try:
                result = self.client.predict(api_name=self.cfg["f5_api_name"], **kwargs)
                shutil.copyfile(_audio_path(result), out_path)
                return out_path
            except Exception as e:
                last = e
                log(f"   ⚠️ F5-TTS tentativo {attempt + 1} fallito: {e}")
                time.sleep(2)
        raise RuntimeError(f"Sintesi non riuscita: {last}")


def _audio_path(result):
    """Il primo output di /basic_tts è l'audio: un percorso, un dict {'path': ...} o una tupla."""
    if isinstance(result, (list, tuple)):
        result = result[0]
    if isinstance(result, dict):
        result = result.get("path") or result.get("value") or result.get("name")
    if not isinstance(result, str) or not os.path.exists(result):
        raise RuntimeError(f"Output audio inatteso da F5-TTS: {result!r}")
    return result


# ---------------------------------------------------------------- audio

def concatena(cfg, segmenti, out_path):
    from pydub import AudioSegment

    if cfg.get("ffmpeg_path"):
        AudioSegment.converter = cfg["ffmpeg_path"]
    pausa = AudioSegment.silent(duration=int(cfg["pausa_paragrafo_ms"]))
    audio = None
    for seg in segmenti:
        a = AudioSegment.from_wav(seg)
        audio = a if audio is None else audio + pausa + a
    fmt = cfg["output_format"].lower()
    tmp = out_path + ".part"
    params = {"bitrate": cfg["mp3_bitrate"]} if fmt == "mp3" else {}
    audio.export(tmp, format=fmt, **params)
    os.replace(tmp, out_path)
    return len(audio) / 1000


# ---------------------------------------------------------------- pipeline

def processa_capitolo(cfg, percorso_txt, tts=None, dry_run=False, force=False):
    nome = os.path.splitext(os.path.basename(percorso_txt))[0]
    fmt = cfg["output_format"].lower()
    out_path = os.path.join(cfg["output_dir"], f"{nome}.{fmt}")
    if cfg["skip_existing"] and not force and not dry_run and os.path.exists(out_path):
        log(f"⏭️  {nome}: {out_path} esiste già (usa --force per rigenerarlo)")
        return out_path
    log(f"📖 {nome}")
    temp = os.path.join(cfg["temp_dir"], nome)
    os.makedirs(temp, exist_ok=True)

    # 1-2. Lettura TXT + normalizzazione con LM Studio (in cache per riprendere dopo un'interruzione)
    cache = os.path.join(temp, "paragrafi.json")
    if os.path.exists(cache) and not force:
        with open(cache, encoding="utf-8") as f:
            paragrafi = json.load(f)
        log(f"   Paragrafi normalizzati letti da {cache}")
    else:
        paragrafi = normalizza_testo(cfg, read_text(percorso_txt))
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(paragrafi, f, ensure_ascii=False, indent=2)
    log(f"   {len(paragrafi)} paragrafi → {cache}")
    if dry_run:
        return cache

    # 3-4. F5-TTS: 001_paragrafo.wav, 002_paragrafo.wav... (i segmenti già creati vengono riusati)
    tts = tts or crea_tts(cfg)
    segmenti = []
    for i, testo in enumerate(paragrafi, 1):
        seg = os.path.join(temp, f"{i:03d}_paragrafo.wav")
        if not (os.path.exists(seg) and os.path.getsize(seg) > 0) or force:
            t0 = time.time()
            tts.synthesize(testo, seg)
            log(f"   🎙️  {i}/{len(paragrafi)} ({word_count(testo)} parole) in {time.time() - t0:.0f} s")
        segmenti.append(seg)

    # 5-6. Concatenazione con 200 ms di pausa, esportazione e pulizia
    os.makedirs(cfg["output_dir"], exist_ok=True)
    durata = concatena(cfg, segmenti, out_path)
    log(f"   ✅ {out_path} ({int(durata // 60)}:{int(durata % 60):02d} min)")
    if not cfg["keep_temp"]:
        shutil.rmtree(temp, ignore_errors=True)
    return out_path


def trova_capitoli(cfg, file=None):
    if file:
        path = file if os.path.isabs(file) else os.path.join(cfg["input_dir"], file)
        if not os.path.exists(path) and os.path.exists(file):
            path = file
        if not os.path.exists(path):
            raise SystemExit(f"File non trovato: {path}")
        return [path]
    estensioni = cfg.get("input_ext") or [".txt", ".md"]
    files = sorted(f for f in glob.glob(os.path.join(cfg["input_dir"], "*"))
                   if os.path.splitext(f)[1].lower() in estensioni)
    if not files:
        raise SystemExit(f"Nessun file {'/'.join(estensioni)} in {cfg['input_dir']}")
    return files


# ---------------------------------------------------------------- test di normalizzazione

ATTESI = [
    "ventotto libri", "cento euro", "primo posto", "seconda gara",
    "quindici maggio millenovecentonovantotto", "diciannovesimo secolo",
    "luigi quattordicesimo", "pio nono", "capitolo quarto", "volume secondo",
]


def test_normalizzazione(cfg):
    paragrafi = normalizza_testo(cfg, read_text(TEST_TXT))
    testo = " ".join(paragrafi)
    log("\n--- Testo normalizzato ---\n" + "\n\n".join(paragrafi) + "\n--------------------------")
    basso = testo.lower()
    risultati = [(a, a in basso) for a in ATTESI]
    risultati.append(("nessuna cifra araba residua", not re.search(r"\d", testo)))
    risultati.append(("nessun numero romano residuo", not re.search(r"\b[IVXLCDM]{2,}\b|\b(?:Pio|Luigi) [IVX]+\b", testo)))
    risultati.append(("output JSON: array di stringhe", isinstance(paragrafi, list) and all(isinstance(p, str) for p in paragrafi)))
    for nome, ok in risultati:
        log(f"{'✅' if ok else '❌'} {nome}")
    falliti = sum(not ok for _, ok in risultati)
    log(f"\n{len(risultati) - falliti}/{len(risultati)} verifiche superate.")
    return falliti == 0


def main():
    p = argparse.ArgumentParser(description="Audiolibri: LM Studio + F5-TTS (Pinokio)")
    p.add_argument("--config", default=CONFIG_PATH, help="percorso di config.json")
    p.add_argument("--file", help="un solo capitolo (nome in input_dir o percorso completo)")
    p.add_argument("--input-dir", help="sovrascrive input_dir")
    p.add_argument("--output-dir", help="sovrascrive output_dir")
    p.add_argument("--format", choices=["mp3", "wav"], help="formato di uscita")
    p.add_argument("--check", action="store_true", help="verifica solo LM Studio (1234) e F5-TTS (7860)")
    p.add_argument("--test-normalizzazione", action="store_true", help="normalizza test_normalizzazione.txt e verifica le regole")
    p.add_argument("--dry-run", action="store_true", help="solo normalizzazione, salva i paragrafi JSON senza audio")
    p.add_argument("--force", action="store_true", help="rigenera anche i capitoli già esportati")
    p.add_argument("--normalizzazione", choices=["llm", "regole"],
                   help="llm = LM Studio (default di config.json), regole = senza LLM, molto più veloce")
    args = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):  # emoji e accenti nella console di Windows
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = load_config(args.config)
    if args.input_dir:
        cfg["input_dir"] = _resolve(args.input_dir)
    if args.output_dir:
        cfg["output_dir"] = _resolve(args.output_dir)
    if args.format:
        cfg["output_format"] = args.format
    if args.normalizzazione:
        cfg["normalizzazione"] = args.normalizzazione

    need_tts = not (args.dry_run or args.test_normalizzazione)
    if not check_services(cfg, need_tts=need_tts):
        raise SystemExit(1)
    if args.check:
        return
    if args.test_normalizzazione:
        raise SystemExit(0 if test_normalizzazione(cfg) else 1)

    capitoli = trova_capitoli(cfg, args.file)
    log(f"{len(capitoli)} capitoli da {cfg['input_dir']} → {cfg['output_dir']}")
    tts = None if args.dry_run else crea_tts(cfg)
    errori = []
    for path in capitoli:
        try:
            processa_capitolo(cfg, path, tts=tts, dry_run=args.dry_run, force=args.force)
        except Exception as e:
            log(f"   ❌ {os.path.basename(path)}: {e} (i segmenti già creati restano in {cfg['temp_dir']} per riprendere)")
            errori.append(path)
    log(f"\nCompletati {len(capitoli) - len(errori)}/{len(capitoli)} capitoli.")
    if errori:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
