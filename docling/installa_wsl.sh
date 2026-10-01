#!/usr/bin/env bash
# Installa Docling pronto all'uso in WSL2 (Ubuntu) per convertire archivi documentali.
# Uso (dal terminale Ubuntu/WSL, nella cartella di questo file):  bash installa_wsl.sh
set -euo pipefail

ENV_DIR="$HOME/docling-env"
APP_DIR="$HOME/docling-archivio"
BIN_DIR="$HOME/.local/bin"
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

passo() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
avviso() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

passo "1/6 Pacchetti di sistema (Python, LibreOffice per .doc/.xls/.ppt, Tesseract come OCR alternativo)"
$SUDO apt-get update -q
$SUDO apt-get install -y -q --no-install-recommends \
    python3 python3-venv python3-pip \
    tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng \
    libreoffice-writer libreoffice-calc libreoffice-impress \
    libgl1 libglib2.0-0 fonts-dejavu-core

passo "2/6 Ambiente Python in $ENV_DIR"
python3 -m venv "$ENV_DIR"
"$ENV_DIR/bin/pip" install -q --upgrade pip wheel

passo "3/6 PyTorch"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "GPU NVIDIA rilevata: installo PyTorch con CUDA."
    "$ENV_DIR/bin/pip" install -q torch torchvision
else
    echo "Nessuna GPU NVIDIA in WSL: installo PyTorch per CPU (più leggero)."
    "$ENV_DIR/bin/pip" install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu \
        || "$ENV_DIR/bin/pip" install -q torch torchvision
fi

passo "4/6 Docling con OCR RapidOCR (e supporto email .eml/.msg)"
"$ENV_DIR/bin/pip" install -q "docling[rapidocr]"

passo "5/6 Modelli Docling (impaginazione, tabelle, OCR) - qualche minuto la prima volta"
if ! "$ENV_DIR/bin/docling-tools" models download; then
    avviso "Download dei modelli non riuscito: verranno scaricati al primo utilizzo."
fi

passo "6/6 Comando 'converti-archivio'"
mkdir -p "$APP_DIR" "$BIN_DIR"
cp "$QUI/converti.py" "$APP_DIR/converti.py"
cat > "$BIN_DIR/converti-archivio" <<EOF
#!/usr/bin/env bash
# Converte CARTELLA_PROGETTO/originali -> markdown/ (e copia i file validi in inputs/ per LightRAG).
set -e
if [ -z "\${1:-}" ]; then
    echo "Uso: converti-archivio CARTELLA_PROGETTO [--ocr rapidocr|tesseract] [--timeout SECONDI]"
    echo "Es.: converti-archivio 'D:\\RAG\\progetto-alfa'   oppure   converti-archivio /mnt/d/RAG/progetto-alfa"
    exit 1
fi
P="\$1"; shift
case "\$P" in [A-Za-z]:\\\\*|[A-Za-z]:/*) P="\$(wslpath "\$P")" ;; esac
exec "$ENV_DIR/bin/python" "$APP_DIR/converti.py" "\$P/originali" "\$P/markdown" --copia-in "\$P/inputs" "\$@"
EOF
chmod +x "$BIN_DIR/converti-archivio"

passo "Verifica"
"$ENV_DIR/bin/python" -c "import docling, importlib.metadata as m; print('Docling', m.version('docling'))"
"$ENV_DIR/bin/python" -c "import torch; print('PyTorch', torch.__version__, '| GPU CUDA:', torch.cuda.is_available())"
tesseract --list-langs 2>/dev/null | grep -qx ita && echo "Tesseract: italiano OK" || avviso "Lingua ita di Tesseract mancante"
command -v soffice >/dev/null && echo "LibreOffice: OK"

printf '\n\033[1;32mInstallazione completata.\033[0m\n'
echo "Uso:  converti-archivio /mnt/d/RAG/progetto-alfa"
echo "      (la cartella del progetto deve contenere la sottocartella 'originali')"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) avviso "Chiudi e riapri il terminale per usare il comando 'converti-archivio'." ;; esac
