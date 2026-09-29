"""Ponte LM Studio -> F5-TTS.

LM Studio espone un'API compatibile OpenAI (default http://localhost:1234/v1).
Questo modulo chiede una risposta all'LLM caricato in LM Studio e la trasforma
in un file audio .wav con F5-TTS, usando la configurazione scritta da
detect_hardware.py (config.json).

Uso da riga di comando:
  python tts_bridge.py --check                    # verifica connessione a LM Studio
  python tts_bridge.py --say "Testo da leggere"   # solo testo -> audio
  python tts_bridge.py --ask "Domanda per l'LLM"  # LLM -> testo -> audio
  python tts_bridge.py --merge a.wav b.wav c.wav  # unisce più WAV in un unico file
"""
import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
DEFAULT_VOICE = os.path.join(HERE, "voices", "voce_riferimento.wav")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        import detect_hardware

        detect_hardware.main()
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["lmstudio_url"] = os.environ.get("LMSTUDIO_URL", cfg.get("lmstudio_url", "http://localhost:1234/v1")).rstrip("/")
    out = cfg.get("output_dir") or "output"
    cfg["output_dir"] = out if os.path.isabs(out) else os.path.join(HERE, out)
    ref = cfg.get("ref_audio") or ""
    if ref and not os.path.isabs(ref):
        ref = os.path.join(HERE, ref)
    if not ref and os.path.exists(DEFAULT_VOICE):
        ref = DEFAULT_VOICE  # voce salvata in app/voices/ (esclusa da git)
    cfg["ref_audio"] = ref
    return cfg


def save_default_voice(cfg, audio_path, ref_text=""):
    """Copia l'audio in app/voices/voce_riferimento.wav e lo imposta come voce predefinita."""
    import shutil

    os.makedirs(os.path.dirname(DEFAULT_VOICE), exist_ok=True)
    if os.path.abspath(audio_path) != DEFAULT_VOICE:
        shutil.copyfile(audio_path, DEFAULT_VOICE)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    saved["ref_audio"] = "voices/voce_riferimento.wav"
    saved["ref_text"] = ref_text
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=2, ensure_ascii=False)
    cfg["ref_audio"], cfg["ref_text"] = DEFAULT_VOICE, ref_text
    return DEFAULT_VOICE


# ---------------------------------------------------------------- LM Studio

def _request(url, payload=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def list_models(cfg):
    ids = [m["id"] for m in _request(f"{cfg['lmstudio_url']}/models", timeout=10).get("data", [])]
    return [i for i in ids if "embed" not in i.lower()]


def pick_model(cfg):
    if cfg.get("lmstudio_model"):
        return cfg["lmstudio_model"]
    models = list_models(cfg)
    if not models:
        raise RuntimeError("LM Studio è attivo ma nessun modello LLM è caricato.")
    return models[0]


def ask_lmstudio(cfg, prompt, history=None):
    messages = [{"role": "system", "content": cfg.get("system_prompt", "")}]
    messages += history or []
    messages.append({"role": "user", "content": prompt})
    resp = _request(f"{cfg['lmstudio_url']}/chat/completions", {
        "model": pick_model(cfg),
        "messages": messages,
        "temperature": 0.7,
        "stream": False,
    })
    return clean_for_speech(resp["choices"][0]["message"]["content"])


def clean_for_speech(text):
    """Rimuove ragionamento <think>, markdown ed emoji che il TTS leggerebbe male."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- F5-TTS

class Speaker:
    def __init__(self, cfg):
        self.cfg = cfg
        self._tts = None

    def _load(self):
        if self._tts is None:
            from cached_path import cached_path
            from f5_tts.api import F5TTS

            t = self.cfg["tts"]
            ckpt = str(cached_path(t["ckpt_file"])) if t.get("ckpt_file") else ""
            vocab = str(cached_path(t["vocab_file"])) if t.get("vocab_file") else ""
            self._tts = F5TTS(model=t["model"], ckpt_file=ckpt, vocab_file=vocab, device=t["device"])
        return self._tts

    def reference(self):
        """Voce di riferimento: quella in config.json, altrimenti l'esempio incluso in F5-TTS."""
        if self.cfg.get("ref_audio") and os.path.exists(self.cfg["ref_audio"]):
            return self.cfg["ref_audio"], self.cfg.get("ref_text", "")
        from importlib.resources import files

        return (str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav")),
                "Some call me nature, others call me mother nature.")

    def speak(self, text, ref_audio=None, ref_text=None, speed=1.0, out_file=None):
        if not text.strip():
            raise ValueError("Testo vuoto.")
        if not ref_audio:
            ref_audio, ref_text = self.reference()
        os.makedirs(self.cfg["output_dir"], exist_ok=True)
        out_file = out_file or os.path.join(self.cfg["output_dir"], time.strftime("tts_%Y%m%d_%H%M%S.wav"))
        self._load().infer(
            ref_file=ref_audio,
            ref_text=ref_text or "",  # vuoto = trascrizione automatica con Whisper
            gen_text=text,
            nfe_step=self.cfg["tts"]["nfe_step"],
            speed=speed,
            remove_silence=True,
            file_wave=out_file,
        )
        return out_file


# ---------------------------------------------------------------- Unione WAV

def merge_wavs(paths, out_file=None, pause=0.0, output_dir=None):
    """Unisce più file audio in un unico .wav, nell'ordine dato.

    Se i file hanno frequenze di campionamento o numero di canali diversi
    vengono convertiti a quelli del primo file. `pause` = secondi di silenzio
    inseriti tra un file e il successivo.
    """
    import numpy as np
    import soundfile as sf

    paths = [p for p in paths if p]
    if len(paths) < 2:
        raise ValueError("Servono almeno due file audio da unire.")
    parts, sr, channels = [], None, None
    for p in paths:
        data, rate = sf.read(p, dtype="float32", always_2d=True)
        if sr is None:
            sr, channels = rate, data.shape[1]
        if rate != sr:
            import librosa

            data = librosa.resample(data.T, orig_sr=rate, target_sr=sr).T
        if data.shape[1] != channels:
            mono = data.mean(axis=1, keepdims=True)
            data = np.repeat(mono, channels, axis=1)
        if parts and pause > 0:
            parts.append(np.zeros((int(sr * pause), channels), dtype="float32"))
        parts.append(data)
    if not out_file:
        output_dir = output_dir or os.path.join(HERE, "output")
        os.makedirs(output_dir, exist_ok=True)
        out_file = os.path.join(output_dir, time.strftime("unito_%Y%m%d_%H%M%S.wav"))
    sf.write(out_file, np.concatenate(parts), sr)
    return out_file


def main():
    p = argparse.ArgumentParser(description="LM Studio -> F5-TTS")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="verifica la connessione a LM Studio")
    g.add_argument("--say", help="testo da trasformare in audio")
    g.add_argument("--ask", help="domanda da inviare all'LLM in LM Studio")
    g.add_argument("--merge", nargs="+", metavar="WAV", help="file audio da unire, nell'ordine")
    p.add_argument("--out", help="file .wav di destinazione")
    p.add_argument("--pause", type=float, default=0.0, help="secondi di silenzio tra i file uniti (con --merge)")
    args = p.parse_args()

    if args.merge:
        try:
            print(f"Audio unito salvato in {merge_wavs(args.merge, args.out, args.pause)}")
        except (ValueError, OSError, RuntimeError) as e:
            raise SystemExit(f"Impossibile unire i file: {e}")
        return
    cfg = load_config()

    if args.check:
        try:
            print(f"LM Studio raggiungibile su {cfg['lmstudio_url']}. Modelli: {', '.join(list_models(cfg)) or '(nessuno caricato)'}")
        except (urllib.error.URLError, OSError) as e:
            raise SystemExit(f"LM Studio non raggiungibile su {cfg['lmstudio_url']}: {e}\n"
                             "Apri LM Studio > Developer > avvia il server (porta 1234).")
        return

    text = args.say
    if args.ask:
        text = ask_lmstudio(cfg, args.ask)
        print(f"LLM: {text}")
    print(f"Audio salvato in {Speaker(cfg).speak(text, out_file=args.out)}")


if __name__ == "__main__":
    main()
