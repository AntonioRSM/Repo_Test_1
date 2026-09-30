"""Pipeline audiolibri: capitoli .txt -> LM Studio (normalizzazione) -> F5-TTS su Pinokio -> MP3/WAV.

1. LM Studio (API compatibile OpenAI) normalizza il testo italiano per la sintesi
   vocale (numeri arabi/romani, date, accenti sugli omografi) e lo divide in
   paragrafi da 100-200 parole, restituiti come array JSON.
2. F5-TTS (interfaccia Gradio avviata da Pinokio) genera un WAV per ogni paragrafo
   tramite gradio_client: 001_paragrafo.wav, 002_paragrafo.wav, ...
3. pydub concatena i segmenti con 200 ms di silenzio ed esporta il capitolo.

Uso:
  python audiobook_pipeline.py --check                      # LM Studio e F5-TTS raggiungibili?
  python audiobook_pipeline.py --test-normalizzazione       # verifica le regole su test_normalizzazione.txt
  python audiobook_pipeline.py                              # tutti i .txt di input_dir
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
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
TEST_TXT = os.path.join(HERE, "test_normalizzazione.txt")

# Configurazione default (sovrascritta da config.json)
LM_STUDIO_URL = "http://localhost:1234/v1"
F5_TTS_URL = "http://127.0.0.1:7860/"
VOICE_REF_AUDIO = "voce_guida.wav"
VOICE_REF_TEXT = "Trascrizione esatta del file audio di riferimento."
PAUSA_PARAGRAFO_MS = 200  # 0.2 secondi come da requisiti

DEFAULTS = {
    "input_dir": "capitoli_input",
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
    "f5_tts_url": F5_TTS_URL,
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
    return cfg


# ---------------------------------------------------------------- verifiche

def port_open(url, timeout=3):
    u = urlparse(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        with socket.create_connection((u.hostname or "127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def check_services(cfg, need_tts=True):
    ok = True
    if port_open(cfg["lmstudio_url"]):
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
        if port_open(cfg["f5_tts_url"]):
            log(f"✅ F5-TTS (Gradio) raggiungibile su {cfg['f5_tts_url']}")
        else:
            log(f"❌ F5-TTS non raggiungibile su {cfg['f5_tts_url']}: avvia F5-TTS in Pinokio e controlla la porta "
                "(la vedi nel terminale: 'Running on local URL').")
            ok = False
        if not os.path.exists(cfg["voice_ref_audio"]):
            log(f"❌ Voce di riferimento mancante: {cfg['voice_ref_audio']} (WAV di 6-10 s di parlato pulito).")
            ok = False
        elif cfg["voice_ref_text"].strip() in ("", VOICE_REF_TEXT):
            log("⚠️ voice_ref_text in config.json è ancora il segnaposto: scrivi la trascrizione ESATTA di voce_guida.wav.")
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

    return OpenAI(base_url=cfg["lmstudio_url"], api_key="lm-studio", timeout=900)


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
    kwargs = dict(
        model=pick_model(cfg),
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo}],
        temperature=cfg["llm_temperature"],
        max_tokens=cfg["llm_max_tokens"],
    )
    last = None
    for attempt in range(cfg["llm_retries"] + 1):
        use_schema = cfg["llm_json_schema"] and attempt == 0
        try:
            resp = client.chat.completions.create(**kwargs, **({"response_format": JSON_SCHEMA} if use_schema else {}))
            return parse_paragraphs(resp.choices[0].message.content or "")
        except Exception as e:  # schema non supportato, JSON malformato, timeout...
            last = e
            log(f"   ⚠️ Tentativo {attempt + 1} di normalizzazione fallito: {e}")
    raise RuntimeError(f"Normalizzazione non riuscita: {last}")


def normalizza_testo(cfg, testo):
    client = lm_client(cfg)
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
    tts = tts or F5TTSClient(cfg)
    segmenti = []
    for i, testo in enumerate(paragrafi, 1):
        seg = os.path.join(temp, f"{i:03d}_paragrafo.wav")
        if not (os.path.exists(seg) and os.path.getsize(seg) > 0) or force:
            log(f"   🎙️  {i}/{len(paragrafi)} ({word_count(testo)} parole)")
            tts.synthesize(testo, seg)
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
    files = sorted(glob.glob(os.path.join(cfg["input_dir"], "*.txt")))
    if not files:
        raise SystemExit(f"Nessun file .txt in {cfg['input_dir']}")
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

    need_tts = not (args.dry_run or args.test_normalizzazione)
    if not check_services(cfg, need_tts=need_tts):
        raise SystemExit(1)
    if args.check:
        return
    if args.test_normalizzazione:
        raise SystemExit(0 if test_normalizzazione(cfg) else 1)

    capitoli = trova_capitoli(cfg, args.file)
    log(f"{len(capitoli)} capitoli da {cfg['input_dir']} → {cfg['output_dir']}")
    tts = None if args.dry_run else F5TTSClient(cfg)
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
