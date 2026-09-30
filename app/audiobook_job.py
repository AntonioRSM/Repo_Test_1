"""Avvia audiobook/audiobook_pipeline.py in background per il server MCP.

Un audiolibro richiede da minuti a ore: lo strumento MCP non può attendere la fine
(LM Studio andrebbe in timeout), quindi il processo parte staccato, scrive in un log
e lo stato si legge con una seconda chiamata.

Variabili d'ambiente opzionali:
  AUDIOBOOK_DIR     cartella con audiobook_pipeline.py (default: ../audiobook del repo)
  AUDIOBOOK_PYTHON  interprete Python da usare (default: app/env-rocm se installato, altrimenti quello del server MCP)
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "output")
LOG_PATH = os.path.join(LOG_DIR, "audiolibro.log")


def pid_attivo(pid):
    """True se il processo esiste ancora (senza toccarlo: su Windows os.kill(pid, 0) lo terminerebbe)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def termina_pid(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        import signal

        os.kill(pid, signal.SIGTERM)


def _env():
    # niente avvisi di librerie (FutureWarning, symlink di Hugging Face) nel log mostrato in chat
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONWARNINGS": "ignore",
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "TRANSFORMERS_VERBOSITY": "error"}


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Su Windows LM Studio può mettere il server MCP in un "job" che chiude anche i processi figli quando
# riavvia il server: la generazione (ore) deve staccarsene, altrimenti muore senza lasciare errori.
_STACCATO = _NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
    getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


def _popen_staccato(cmd, **kw):
    try:
        return subprocess.Popen(cmd, creationflags=_STACCATO, **kw)
    except OSError:
        # il job non permette il distacco: si avvia comunque (con il rischio descritto sopra)
        return subprocess.Popen(cmd, creationflags=_NO_WINDOW, **kw)


def pipeline_python():
    """AUDIOBOOK_PYTHON, altrimenti l'ambiente GPU AMD (app/env-rocm) se installato e verificato, altrimenti questo."""
    if os.environ.get("AUDIOBOOK_PYTHON"):
        return os.environ["AUDIOBOOK_PYTHON"]
    rocm = os.path.join(HERE, "env-rocm")
    exe = os.path.join(rocm, "Scripts", "python.exe") if os.name == "nt" else os.path.join(rocm, "bin", "python")
    if os.path.exists(os.path.join(rocm, ".pronto")) and os.path.exists(exe):
        return exe
    return sys.executable


def pipeline_dir():
    return os.environ.get("AUDIOBOOK_DIR") or os.path.join(os.path.dirname(HERE), "audiobook")


class AudiobookJob:
    def __init__(self, log_path=LOG_PATH):
        self.log_path = log_path
        self.pid_path = os.path.splitext(log_path)[0] + ".pid"
        self.proc = None
        self.started = None

    def pid_orfano(self):
        """PID di una generazione avviata da un'istanza precedente del server MCP e ancora attiva."""
        try:
            with open(self.pid_path) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return None
        if self.proc is not None and pid == self.proc.pid:
            return None
        return pid if pid_attivo(pid) else None

    def running(self):
        return (self.proc is not None and self.proc.poll() is None) or self.pid_orfano() is not None

    def build_command(self, file="", formato="mp3", forza=False, solo_testo=False, normalizzazione=""):
        script = os.path.join(pipeline_dir(), "audiobook_pipeline.py")
        if not os.path.exists(script):
            raise FileNotFoundError(f"Script non trovato: {script} (imposta AUDIOBOOK_DIR)")
        if formato not in ("mp3", "wav"):
            raise ValueError("formato deve essere 'mp3' o 'wav'")
        cmd = [pipeline_python(), "-u", script, "--format", formato]
        if file.strip():
            cmd += ["--file", file.strip()]
        if forza:
            cmd.append("--force")
        if solo_testo:
            cmd.append("--dry-run")
        if normalizzazione:
            if normalizzazione not in ("llm", "regole"):
                raise ValueError("normalizzazione deve essere 'llm' o 'regole'")
            cmd += ["--normalizzazione", normalizzazione]
        return cmd

    def check(self, timeout=90):
        """Esegue audiobook_pipeline.py --check: percorsi, LM Studio, F5-TTS e voce di riferimento."""
        cmd = self.build_command()[:3] + ["--check"]
        intro = f"Cartella pipeline: {pipeline_dir()}\n"
        try:
            r = subprocess.run(cmd, cwd=pipeline_dir(), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout,
                               env=_env(),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return intro + f"Verifica non completata entro {timeout} s."
        esito = "Tutto pronto." if r.returncode == 0 else "Ci sono problemi da risolvere (righe con ❌)."
        return intro + (r.stdout + r.stderr).strip() + "\n\n" + esito

    def start(self, file="", formato="mp3", forza=False, solo_testo=False, normalizzazione=""):
        if self.running():
            return "Una generazione è già in corso.\n\n" + self.status()
        cmd = self.build_command(file, formato, forza, solo_testo, normalizzazione)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        log = open(self.log_path, "w", encoding="utf-8")
        # stdin/stdout NON devono essere quelli del server: il protocollo MCP viaggia su stdio.
        self.proc = _popen_staccato(cmd, cwd=pipeline_dir(), stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, env=_env())
        log.close()
        with open(self.pid_path, "w") as f:
            f.write(str(self.proc.pid))
        self.started = time.time()
        cosa = file.strip() or "tutti i capitoli della cartella di input"
        return (f"Generazione avviata ({cosa}, formato {formato}{', solo testo' if solo_testo else ''}"
                f"{', normalizzazione ' + normalizzazione if normalizzazione else ''}).\n"
                f"Log: {self.log_path}\nUsa lo strumento stato_audiolibro per seguire l'avanzamento.")

    def stop(self):
        if not self.running():
            return "Nessuna generazione in corso."
        if self.proc is not None and self.proc.poll() is None:
            termina_pid(self.proc.pid) if os.name == "nt" else self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        orfano = self.pid_orfano()
        if orfano:
            termina_pid(orfano)
        return ("Generazione interrotta. I paragrafi e i segmenti già creati restano in temp_segments: "
                "rilanciando genera_audiolibro riparte da lì.")

    def tail(self, righe=25):
        if not os.path.exists(self.log_path):
            return ""
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-righe:]).strip()

    def status(self, righe=25):
        if self.proc is None and self.pid_orfano():
            stato = "In corso (avviata da una sessione precedente del server MCP)."
        elif self.proc is None:
            stato = "Nessuna generazione in corso."
            ultimo = self.tail(3)
            if ultimo and "Completati" not in ultimo and "Traceback" not in self.tail(200):
                stato += (" ⚠️ L'ultima generazione si è interrotta senza finire e senza errori: il processo è stato "
                          "chiuso dall'esterno (es. LM Studio ha riavviato il server MCP) o è andato in crash nel "
                          "codice nativo della GPU. Ultimo log:")
            elif ultimo:
                stato += " Ultimo log disponibile:"
        elif self.proc.poll() is None:
            stato = f"In corso da {int((time.time() - self.started) // 60)} min."
        elif self.proc.returncode == 0:
            stato = "Completata con successo."
        else:
            stato = f"Terminata con errori (codice {self.proc.returncode})."
        log = self.tail(righe)
        return f"{stato}\n\n{log}" if log else stato
