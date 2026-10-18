"""Reports which native dependencies load under Windows application control (Smart App Control)."""

import importlib
import sys

MODULES = sys.argv[1:] or [
    "pymupdf",
    "pyarrow",
    "pyarrow.dataset",
    "lancedb",
    "onnxruntime",
    "rapidocr_onnxruntime",
    "cv2",
    "numpy",
    "PIL.Image",
    "docx",
    "openpyxl",
    "pptx",
    "olefile",
    "watchdog.observers",
    "psutil",
    "win32pdh",
    "pydantic_core",
    "uvicorn",
    "httptools",
    "watchfiles",
]

for name in MODULES:
    try:
        importlib.import_module(name)
        print(f"OK      {name}")
    except Exception as exc:  # noqa: BLE001 - probing every failure mode
        print(f"BLOCKED {name}: {type(exc).__name__}: {str(exc)[:140]}")
