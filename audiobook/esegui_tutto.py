"""Genera TUTTI i capitoli fino alla fine, anche se la pipeline si blocca.

Fa lavorare audiobook_pipeline.py a lotti (--blocco capitoli per volta) e ne sorveglia il log:
- se il log non cresce per --stallo-min minuti (blocco GPU, LM Studio appeso, ...) termina il processo
  e lo riavvia dal capitolo in corso (i paragrafi già sintetizzati vengono riusati);
- un capitolo che fallisce o si blocca --tentativi volte viene saltato e messo nel resoconto finale;
- ogni lotto riparte con un processo nuovo: la memoria della GPU non cresce su migliaia di capitoli.

Uso (meglio con genera_tutto.bat):
  python esegui_tutto.py                          # normalizzazione a regole, MP3
  python esegui_tutto.py --normalizzazione llm    # con LM Studio
Interrompibile con Ctrl+C: rilanciando riparte dai capitoli mancanti.
"""
import argparse
import codecs
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audiobook_pipeline as ap  # noqa: E402

PIPELINE = os.path.join(HERE, "audiobook_pipeline.py")
LOG_DIR = os.path.join(HERE, "logs")
STATO_PATH = os.path.join(LOG_DIR, "stato_batch.json")


def disattiva_modifica_rapida():
    """Nella console di Windows un clic nella finestra ("Modifica rapida") sospende chi scrive a video:
    è una causa classica dei blocchi "dopo un po'" degli script lanciati da un .bat."""
    if os.name != "nt":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)  # -QUICK_EDIT, +EXTENDED_FLAGS
    except Exception:
        pass


def termina(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def carica_stato():
    try:
        with open(STATO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"falliti": {}}


def salva_stato(stato):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(STATO_PATH, "w", encoding="utf-8") as f:
        json.dump(stato, f, ensure_ascii=False, indent=2)


def uscita(cfg, path):
    nome = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(cfg["output_dir"], f"{nome}.{cfg['output_format'].lower()}")


def da_fare(cfg, stato, tentativi):
    out = []
    for path in ap.trova_capitoli(cfg):
        if os.path.exists(uscita(cfg, path)):
            continue
        if stato["falliti"].get(os.path.basename(path), 0) >= tentativi:
            continue
        out.append(path)
    return out


def esegui_lotto(args, cfg, lotto, log_path):
    """Esegue un lotto; restituisce (codice di uscita o None se bloccato, ultimo capitolo visto)."""
    lista = os.path.join(LOG_DIR, "lotto.txt")
    with open(lista, "w", encoding="utf-8") as f:
        f.write("\n".join(lotto))
    cmd = [sys.executable, "-u", PIPELINE, "--config", args.config,
           "--lista", lista, "--format", cfg["output_format"], "--normalizzazione", cfg["normalizzazione"],
           "--input-dir", cfg["input_dir"], "--output-dir", cfg["output_dir"]]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONWARNINGS": "ignore",
           "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "TRANSFORMERS_VERBOSITY": "error"}
    with open(log_path, "ab") as log:
        log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} lotto di {len(lotto)} capitoli =====\n"
                  .encode("utf-8"))
        log.flush()
        inizio = log.tell()
        proc = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    letto, ultimo_capitolo, ultima_crescita = inizio, None, time.time()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")  # emoji spezzate tra due letture
    while True:
        time.sleep(args.intervallo)
        dimensione = os.path.getsize(log_path)
        if dimensione > letto:
            ultima_crescita = time.time()
            with open(log_path, "rb") as f:
                f.seek(letto)
                nuovo = decoder.decode(f.read(dimensione - letto))
            letto = dimensione
            for riga in re.split(r"[\r\n]+", nuovo):
                m = re.match(r"\s*📖 (.+)$", riga)
                if m:
                    ultimo_capitolo = m.group(1).strip()
                if riga.strip() and not re.match(r"\s*\d+%\|", riga):  # niente barre di avanzamento a video
                    print(riga, flush=True)
        if proc.poll() is not None:
            return proc.returncode, ultimo_capitolo
        if time.time() - ultima_crescita > args.stallo_min * 60:
            print(f"⚠️ Nessun avanzamento da {args.stallo_min} minuti (capitolo {ultimo_capitolo}): "
                  "riavvio la pipeline.", flush=True)
            termina(proc)
            return None, ultimo_capitolo


def capitoli_falliti_nel_log(log_path, da_byte):
    with open(log_path, "rb") as f:
        f.seek(da_byte)
        return re.findall(r"❌ (.+?\.(?:txt|md)):", f.read().decode("utf-8", "replace"))


def main():
    p = argparse.ArgumentParser(description="Genera tutti i capitoli, riavviando la pipeline se si blocca")
    p.add_argument("--config", default=ap.CONFIG_PATH)
    p.add_argument("--input-dir")
    p.add_argument("--output-dir")
    p.add_argument("--format", choices=["mp3", "wav"])
    p.add_argument("--normalizzazione", choices=["llm", "regole"], default="regole",
                   help="regole (default: veloce, senza LM Studio) o llm")
    p.add_argument("--blocco", type=int, default=25, help="capitoli per processo prima di ripartire (default 25)")
    p.add_argument("--stallo-min", type=float, default=10, help="minuti senza avanzamento prima del riavvio")
    p.add_argument("--tentativi", type=int, default=3, help="tentativi per capitolo prima di saltarlo")
    p.add_argument("--intervallo", type=float, default=5, help="secondi tra un controllo e l'altro")
    p.add_argument("--azzera-falliti", action="store_true", help="riprova anche i capitoli già saltati")
    args = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    disattiva_modifica_rapida()
    cfg = ap.load_config(args.config)
    if args.input_dir:
        cfg["input_dir"] = ap._resolve(args.input_dir)
    if args.output_dir:
        cfg["output_dir"] = ap._resolve(args.output_dir)
    if args.format:
        cfg["output_format"] = args.format
    cfg["normalizzazione"] = args.normalizzazione
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "genera_tutto.log")
    stato = carica_stato()
    if args.azzera_falliti:
        stato["falliti"] = {}
        salva_stato(stato)

    totale = len(ap.trova_capitoli(cfg))
    print(f"Log completo: {log_path}", flush=True)
    t0 = time.time()
    senza_progresso = 0
    while True:
        restanti = da_fare(cfg, stato, args.tentativi)
        fatti = totale - len(restanti) - sum(1 for v in stato["falliti"].values() if v >= args.tentativi)
        if not restanti:
            break
        trascorso = time.time() - t0
        print(f"\n=== {fatti}/{totale} capitoli pronti, {len(restanti)} da fare "
              f"({trascorso / 3600:.1f} h trascorse) ===", flush=True)
        lotto = restanti[:args.blocco]
        inizio_log = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        codice, ultimo = esegui_lotto(args, cfg, lotto, log_path)

        if codice == 1 and ultimo is None:
            raise SystemExit("❌ La pipeline si è fermata ai controlli iniziali (righe ❌ qui sopra): risolvi e rilancia.")
        colpevoli = set(capitoli_falliti_nel_log(log_path, inizio_log))
        if codice is None and ultimo:  # bloccato: il capitolo in corso conta come fallito
            colpevoli.add(next((os.path.basename(x) for x in lotto
                                if os.path.splitext(os.path.basename(x))[0] == ultimo), ultimo))
        elif codice not in (0, 1) and ultimo:  # crash del processo (es. driver)
            colpevoli.add(next((os.path.basename(x) for x in lotto
                                if os.path.splitext(os.path.basename(x))[0] == ultimo), ultimo))
        prodotti = sum(os.path.exists(uscita(cfg, x)) for x in lotto)
        senza_progresso = 0 if prodotti else senza_progresso + 1
        if senza_progresso >= 5:
            raise SystemExit(f"❌ 5 lotti di fila senza nessun capitolo completato: c'è un problema generale "
                             f"(GPU, driver, voce, spazio su disco). Ultime righe in {log_path}.")
        if not prodotti and not colpevoli:  # crash prima del primo capitolo (es. caricamento del modello)
            colpevoli.add(os.path.basename(lotto[0]))
        for c in colpevoli:
            stato["falliti"][c] = stato["falliti"].get(c, 0) + 1
            if stato["falliti"][c] >= args.tentativi:
                print(f"⏭️  {c}: {args.tentativi} tentativi falliti, lo salto (riprovabile con --azzera-falliti)",
                      flush=True)
        salva_stato(stato)

    saltati = sorted(c for c, v in stato["falliti"].items() if v >= args.tentativi)
    pronti = sum(os.path.exists(uscita(cfg, x)) for x in ap.trova_capitoli(cfg))
    print(f"\n✅ Finito: {pronti}/{totale} capitoli in {cfg['output_dir']} "
          f"({(time.time() - t0) / 3600:.1f} h).", flush=True)
    if saltati:
        print(f"⚠️ {len(saltati)} capitoli saltati dopo {args.tentativi} tentativi (elenco in {STATO_PATH}): "
              + ", ".join(saltati[:20]) + (" ..." if len(saltati) > 20 else ""), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
