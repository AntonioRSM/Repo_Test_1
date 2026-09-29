"""Rileva l'hardware del PC e sceglie la configurazione F5-TTS più adatta.

Usa solo la libreria standard (funziona anche prima che torch sia installato);
se torch è disponibile lo usa per una rilevazione più precisa.
Scrive il risultato in config.json (accanto a questo file) e lo stampa.
"""
import json
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

# Modelli F5-TTS (vedi src/f5_tts/infer/SHARED.md nel repo SWivid/F5-TTS)
MODELS = {
    "it": {
        "name": "F5-TTS Base @ it (alien79)",
        "model": "F5TTS_Base",
        "ckpt_file": "hf://alien79/F5-TTS-italian/model_159600.safetensors",
        "vocab_file": "hf://alien79/F5-TTS-italian/vocab.txt",
    },
    "en": {
        "name": "F5-TTS v1 Base (SWivid)",
        "model": "F5TTS_v1_Base",
        "ckpt_file": "",
        "vocab_file": "",
    },
}
MODELS["zh"] = MODELS["en"]

DEFAULTS = {
    "language": "it",
    "lmstudio_url": "http://localhost:1234/v1",
    "lmstudio_model": "",
    "system_prompt": "Rispondi in italiano, in modo conciso e con frasi adatte a essere lette ad alta voce. Niente markdown, elenchi o emoji.",
    "ref_audio": "",
    "ref_text": "",
    "output_dir": "output",
}


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""


def total_ram_gb():
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return ms.ullTotalPhys / 1024**3
        if sys.platform == "darwin":
            return int(_run(["sysctl", "-n", "hw.memsize"]).strip()) / 1024**3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except Exception:
        return 0.0


def detect_gpu():
    """Ritorna (backend, nome, vram_gb). backend: cuda | mps | xpu | cpu."""
    try:
        import torch

        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return "cuda", p.name, p.total_memory / 1024**3
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return "xpu", torch.xpu.get_device_name(0), 0.0
        if torch.backends.mps.is_available():
            return "mps", "Apple Silicon", total_ram_gb()
    except Exception:
        pass
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        if out.strip():
            name, mem = [x.strip() for x in out.strip().splitlines()[0].split(",")]
            return "cuda", name, float(mem) / 1024
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "mps", "Apple Silicon", total_ram_gb()
    return "cpu", platform.processor() or platform.machine(), 0.0


def recommend(language="it"):
    backend, gpu_name, vram = detect_gpu()
    ram = total_ram_gb()
    notes = []

    # F5-TTS Base ~336M parametri: ~2 GB di VRAM in inferenza (modello + vocoder Vocos).
    # LM Studio sulla stessa GPU occupa altra VRAM: con meno di 6 GB conviene
    # lasciare la GPU all'LLM oppure caricare un LLM piccolo.
    if backend == "cuda" and vram < 3:
        notes.append(f"VRAM {vram:.1f} GB insufficiente: F5-TTS userà la CPU.")
        backend = "cpu"
    if backend == "cuda" and vram < 6:
        notes.append("VRAM limitata: in LM Studio usa un modello piccolo (es. 3-4B Q4) o GPU offload parziale.")

    if backend in ("cuda", "mps", "xpu"):
        nfe_step = 32  # qualità piena
    else:
        nfe_step = 16  # CPU: circa 2x più veloce, qualità leggermente inferiore
        notes.append("Nessuna GPU utilizzabile: sintesi su CPU (lenta, ~qualche secondo per frase).")
    if ram and ram < 8:
        notes.append(f"RAM {ram:.1f} GB: bassa, evita di tenere LM Studio e F5-TTS con modelli grandi insieme.")

    model = MODELS.get(language, MODELS["en"])
    return {
        "hardware": {"os": platform.system(), "backend": backend, "gpu": gpu_name,
                     "vram_gb": round(vram, 1), "ram_gb": round(ram, 1)},
        "tts": {**model, "language": language, "device": backend, "nfe_step": nfe_step},
        "notes": notes,
    }


def main(language=None):
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    language = language or cfg.get("language", "it")
    cfg["language"] = language
    cfg.update(recommend(language))
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    h, t = cfg["hardware"], cfg["tts"]
    print("=== Hardware rilevato ===")
    print(f"Sistema: {h['os']} | Backend: {h['backend']} | GPU: {h['gpu']} | VRAM: {h['vram_gb']} GB | RAM: {h['ram_gb']} GB")
    print("=== Modello F5-TTS consigliato ===")
    print(f"{t['name']} | device={t['device']} | nfe_step={t['nfe_step']}")
    for n in cfg["notes"]:
        print(f"- {n}")
    print(f"Configurazione salvata in {CONFIG_PATH}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
