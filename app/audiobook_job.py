"""Avvia audiobook/audiobook_pipeline.py in background per il server MCP.

Un audiolibro richiede da minuti a ore: lo strumento MCP non può attendere la fine
(LM Studio andrebbe in timeout), quindi il processo parte staccato, scrive in un log
e lo stato si legge con una seconda chiamata.

Variabili d'ambiente opzionali:
  AUDIOBOOK_DIR     cartella con audiobook_pipeline.py (default: ../audiobook del repo)
  AUDIOBOOK_PYTHON  interprete Python da usare (default: quello del server MCP)
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, "output")
LOG_PATH = os.path.join(LOG_DIR, "audiolibro.log")


def pipeline_dir():
    return os.environ.get("AUDIOBOOK_DIR") or os.path.join(os.path.dirname(HERE), "audiobook")


class AudiobookJob:
    def __init__(self, log_path=LOG_PATH):
        self.log_path = log_path
        self.proc = None
        self.started = None

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def build_command(self, file="", formato="mp3", forza=False, solo_testo=False):
        script = os.path.join(pipeline_dir(), "audiobook_pipeline.py")
        if not os.path.exists(script):
            raise FileNotFoundError(f"Script non trovato: {script} (imposta AUDIOBOOK_DIR)")
        if formato not in ("mp3", "wav"):
            raise ValueError("formato deve essere 'mp3' o 'wav'")
        cmd = [os.environ.get("AUDIOBOOK_PYTHON") or sys.executable, "-u", script, "--format", formato]
        if file.strip():
            cmd += ["--file", file.strip()]
        if forza:
            cmd.append("--force")
        if solo_testo:
            cmd.append("--dry-run")
        return cmd

    def start(self, file="", formato="mp3", forza=False, solo_testo=False):
        if self.running():
            return "Una generazione è già in corso.\n\n" + self.status()
        cmd = self.build_command(file, formato, forza, solo_testo)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        log = open(self.log_path, "w", encoding="utf-8")
        # stdin/stdout NON devono essere quelli del server: il protocollo MCP viaggia su stdio.
        self.proc = subprocess.Popen(
            cmd, cwd=pipeline_dir(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.close()
        self.started = time.time()
        cosa = file.strip() or "tutti i capitoli della cartella di input"
        return (f"Generazione avviata ({cosa}, formato {formato}{', solo testo' if solo_testo else ''}).\n"
                f"Log: {self.log_path}\nUsa lo strumento stato_audiolibro per seguire l'avanzamento.")

    def tail(self, righe=25):
        if not os.path.exists(self.log_path):
            return ""
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-righe:]).strip()

    def status(self, righe=25):
        if self.proc is None:
            stato = "Nessuna generazione avviata da questa sessione."
            if os.path.exists(self.log_path):
                stato += " Ultimo log disponibile:"
        elif self.running():
            stato = f"In corso da {int((time.time() - self.started) // 60)} min."
        elif self.proc.returncode == 0:
            stato = "Completata con successo."
        else:
            stato = f"Terminata con errori (codice {self.proc.returncode})."
        log = self.tail(righe)
        return f"{stato}\n\n{log}" if log else stato
