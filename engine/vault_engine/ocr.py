"""OCR engines: RapidOCR (ONNX, local), Tesseract (if installed) and local vision LLMs."""

from __future__ import annotations

import base64
import io
import shutil
import threading
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import numpy as np
from PIL import Image

from .config import ModelRef, OcrSettings
from .providers import chat_content, chat_payload, post_json_sync

VISION_PROMPT = (
    "Transcribe all text in this image faithfully, preserving reading order. "
    "Render tables as Markdown tables and headings as Markdown headings. "
    "If the image has no text, describe its content in two or three sentences. "
    "Output only the transcription or description."
)


@dataclass
class OcrLine:
    text: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1
    confidence: float


@dataclass
class OcrResult:
    text: str
    engine: str
    lines: list[OcrLine] = field(default_factory=list)
    mean_confidence: float | None = None


class OcrEngine(Protocol):
    name: str

    def recognize(self, png: bytes) -> OcrResult: ...


def layout_text(lines: list[OcrLine]) -> str:
    """Rebuilds reading order from line boxes: groups boxes into rows and rows into paragraphs.

    Several boxes on the same row become a ` | `-separated table row, which keeps
    scanned tables readable for embedding.
    """
    if not lines:
        return ""
    heights = sorted(ln.box[3] - ln.box[1] for ln in lines)
    median_h = max(heights[len(heights) // 2], 1.0)
    rows: list[list[OcrLine]] = []
    for line in sorted(lines, key=lambda ln: ((ln.box[1] + ln.box[3]) / 2, ln.box[0])):
        center = (line.box[1] + line.box[3]) / 2
        if rows:
            last = rows[-1]
            last_center = sum((ln.box[1] + ln.box[3]) / 2 for ln in last) / len(last)
            if abs(center - last_center) < median_h * 0.5:
                last.append(line)
                continue
        rows.append([line])

    out: list[str] = []
    prev_bottom: float | None = None
    for row in rows:
        row.sort(key=lambda ln: ln.box[0])
        top = min(ln.box[1] for ln in row)
        if prev_bottom is not None and top - prev_bottom > median_h * 1.2:
            out.append("")
        out.append(" | ".join(ln.text for ln in row) if len(row) > 1 else row[0].text)
        prev_bottom = max(ln.box[3] for ln in row)
    return "\n".join(out).strip()


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    def _get(self):
        if self._engine is None:
            # Model creation is not thread-safe and loads ONNX sessions: build it once,
            # under the same lock that serialises recognition.
            with self._lock:
                if self._engine is None:
                    from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415 - slow import

                    self._engine = RapidOCR()
        return self._engine

    def recognize(self, png: bytes) -> OcrResult:
        image = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
        engine = self._get()  # builds under the lock if needed
        # The ONNX sessions are not documented as thread-safe; serialise calls.
        with self._lock:
            result, _ = engine(image)
        lines = []
        for box, text, score in result or []:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append(OcrLine(text=text, box=(min(xs), min(ys), max(xs), max(ys)), confidence=float(score)))
        mean = sum(ln.confidence for ln in lines) / len(lines) if lines else None
        return OcrResult(text=layout_text(lines), engine=self.name, lines=lines, mean_confidence=mean)


TESSERACT_LANGS = {"it": "ita", "en": "eng", "de": "deu", "fr": "fra", "es": "spa", "pt": "por"}


class TesseractEngine:
    name = "tesseract"

    def __init__(self, languages: list[str]) -> None:
        import pytesseract  # noqa: PLC0415 - optional extra

        exe = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        pytesseract.pytesseract.tesseract_cmd = exe
        self._tess = pytesseract
        self.lang = "+".join(TESSERACT_LANGS.get(code, code) for code in languages) or "eng"

    def recognize(self, png: bytes) -> OcrResult:
        image = Image.open(io.BytesIO(png))
        text = self._tess.image_to_string(image, lang=self.lang, config="--psm 3")
        return OcrResult(text=text.strip(), engine=self.name)


class VisionLlmEngine:
    """Delegates OCR and image description to a multimodal model (llava, qwen2-vl…)."""

    name = "vision"

    def __init__(self, endpoints: dict[str, str], ref: ModelRef) -> None:
        self.base = endpoints[ref.provider].rstrip("/")
        self.ref = ref

    def recognize(self, png: bytes) -> OcrResult:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]
        payload = chat_payload(self.ref, messages, temperature=0, max_tokens=2048, reasoning=False)
        body = post_json_sync(
            f"{self.base}/v1/chat/completions", payload, f"OCR vision {self.ref.model}", httpx.Timeout(600.0, connect=5.0)
        )
        return OcrResult(text=chat_content(self.ref, body), engine=f"vision:{self.ref.model}")


class NoOcr:
    name = "none"

    def recognize(self, png: bytes) -> OcrResult:
        return OcrResult(text="", engine=self.name)


_rapid_singleton = RapidOcrEngine()


def build_engine(settings: OcrSettings, endpoints: dict[str, str]) -> OcrEngine:
    if settings.engine == "none":
        return NoOcr()
    if settings.engine == "vision":
        if settings.vision is None:
            raise ValueError("Vision OCR selected but no vision model configured")
        return VisionLlmEngine(endpoints, settings.vision)
    if settings.engine == "tesseract":
        return TesseractEngine(settings.languages)
    return _rapid_singleton


def to_png(image: Image.Image, max_side: int = 2400) -> bytes:
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
