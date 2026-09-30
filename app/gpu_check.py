"""Verifica che PyTorch veda la GPU e, se sì, abilita app/env-rocm per la pipeline audiolibri (file .pronto)."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PRONTO = os.path.join(os.path.dirname(sys.executable), os.pardir, ".pronto")

try:
    import torch
except Exception as e:  # installazione non riuscita
    raise SystemExit(f"PyTorch non importabile: {e}")

print(f"PyTorch {torch.__version__} | Python {sys.version.split()[0]}")
if not torch.cuda.is_available():
    if os.path.exists(PRONTO):
        os.remove(PRONTO)
    raise SystemExit("NESSUNA GPU visibile: aggiorna il driver AMD Software: Adrenalin Edition (26.2.2 o più recente), "
                     "riavvia il PC e rilancia questa voce. La pipeline continuerà a usare la CPU.")
nome = torch.cuda.get_device_name(0)
x = torch.randn(2048, 2048, device="cuda")
torch.cuda.synchronize()
t0 = time.time()
for _ in range(20):
    x = x @ x
    x = x / x.norm()
torch.cuda.synchronize()
print(f"GPU: {nome} | test di calcolo: {time.time() - t0:.2f} s")
open(os.path.normpath(PRONTO), "w").close()
print("GPU pronta: la pipeline audiolibri userà questo ambiente (app/env-rocm).")
