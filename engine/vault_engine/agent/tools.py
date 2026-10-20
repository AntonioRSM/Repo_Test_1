"""Tools the local agent can call. Every call is shown to the user for approval first."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Awaitable, Callable

from ..config import SettingsStore
from ..ocr import build_engine
from ..parsers import SUPPORTED_EXTS, parse_file
from ..providers import ProviderClient, ProviderError
from ..vaults import VaultRegistry
from .store import Task, Thread
from .web import WebError, fetch_url, web_search

MAX_RESULT_CHARS = 8000
VAULT_PASSAGE_CHARS = 900
POWERSHELL_TIMEOUT_MAX = 300


class ToolError(Exception):
    """Raised for user-facing tool failures; the message is returned to the model."""


@dataclass
class ToolContext:
    registry: VaultRegistry
    settings: SettingsStore
    thread: Thread
    save_thread: Callable[[Thread], None]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[ToolContext, dict], Awaitable[dict]]
    # Shown in the approval card; True only for tools with no effect outside the app.
    needs_approval: bool = True
    risk: str = "read"  # read | write | execute | network

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit] + "\n…[troncato]", True)


def _path(raw: str) -> Path:
    if not raw:
        raise ToolError("percorso mancante")
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


# ---------------------------------------------------------------------- vaults


async def _list_vaults(ctx: ToolContext, args: dict) -> dict:
    vaults = [v for v in ctx.registry.list() if not ctx.thread.vault_ids or v.config.id in ctx.thread.vault_ids]
    return {
        "vaults": [
            {"name": v.config.name, "description": v.config.description, "files": v.stats()["files"], "chunks": v.count_chunks()}
            for v in vaults
        ]
    }


async def _vault_search(ctx: ToolContext, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolError("query mancante")
    k = max(1, min(int(args.get("k") or 5), 12))
    wanted = (args.get("vault") or "").strip().lower()
    vaults = [v for v in ctx.registry.list() if not ctx.thread.vault_ids or v.config.id in ctx.thread.vault_ids]
    if wanted:
        vaults = [v for v in vaults if wanted in v.config.name.lower() or wanted == v.config.id]
        if not vaults:
            raise ToolError(f"nessun Vault corrisponde a '{args.get('vault')}'")
    if not vaults:
        raise ToolError("nessun Vault disponibile")
    client = ProviderClient(ctx.settings.get().endpoints)
    hits = []
    for vault in vaults:
        try:
            vector = (await client.embed(vault.config.embedding, [query]))[0]
        except ProviderError as exc:
            raise ToolError(f"embedding non disponibile per il Vault '{vault.config.name}': {exc}") from exc
        for row in await asyncio.to_thread(vault.search, vector, k, "cosine", None):
            hits.append(
                {
                    "vault": vault.config.name,
                    "file": row["file_name"],
                    "path": row["file_path"],
                    "page": row.get("page_start"),
                    "section": row.get("heading") or None,
                    "score": round(row["scores"]["cosine"], 4),
                    # Every character is prompt the local model must read on the next step.
                    "text": row["text"] if len(row["text"]) <= VAULT_PASSAGE_CHARS else row["text"][:VAULT_PASSAGE_CHARS] + "…",
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return {"results": hits[:k]}


# ---------------------------------------------------------------------- files


# Miglioramento #4: a sparse pattern must not walk an entire (possibly network) disk,
# and the scan must stay off the event-loop thread so /health and SSE keep answering.
SCAN_VISITED_LIMIT = 20_000


def _glob_match(rel: str, pattern: str) -> bool:
    """glob semantics on a POSIX relative path: `*` and `?` do not cross '/',
    `**/` matches zero or more directories, `**` matches anything."""
    out = []
    i, n = 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
            elif pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(r"\[")
                i += 1
            else:
                cls = pattern[i : end + 1]
                out.append(cls.replace("[!", "[^"))  # glob negation -> regex negation
                i = end + 1
        else:
            out.append(re.escape(char))
            i += 1
    # Bug #14: on Windows the file system is case-insensitive and Path.glob (used up
    # to ciclo 2) matched *.pdf → Contratto.PDF; keep that behavior.
    flags = re.IGNORECASE if os.name == "nt" else 0
    return re.fullmatch("".join(out), rel, flags=flags) is not None


def _pattern_max_depth(pattern: str) -> int | None:
    """How deep (in path segments) a pattern can match: `*` or `*.pdf` only reach the
    top level, `sub/*.txt` two levels; `**` means unlimited (Bug #13)."""
    segments = [s for s in pattern.split("/") if s not in ("", ".")]
    if any("**" in s for s in segments):
        return None
    return max(1, len(segments))


def _scan_directory(path: Path, pattern: str) -> dict:
    """Sync scan executed in a worker thread (asyncio.to_thread). Visits at most
    SCAN_VISITED_LIMIT entries; `truncated` is True when either the visit budget or
    the 300-entry result budget is exhausted. Subtrees deeper than the pattern can
    reach are pruned away instead of walked and budgeted (Bug #13): with `*` a
    20.000-file subfolder must neither be traversed nor mark the list truncated."""
    rel_pattern = pattern.replace("\\", "/")
    max_depth = _pattern_max_depth(rel_pattern)
    matches: list[Path] = []
    visited = 0
    budget_exhausted = False
    for dirpath, dirnames, filenames in os.walk(path):
        names = (*dirnames, *filenames)
        if max_depth is not None:
            depth = len(Path(dirpath).relative_to(path).parts)
            if depth >= max_depth - 1:
                # Entries here sit at max_depth; their children cannot match.
                dirnames[:] = []
        for name in names:
            visited += 1
            if visited > SCAN_VISITED_LIMIT:
                budget_exhausted = True
                break
            full = Path(dirpath) / name
            rel = full.relative_to(path).as_posix()
            if _glob_match(rel, rel_pattern):
                matches.append(full)
        if budget_exhausted:
            break
    entries = []
    for entry in sorted(matches, key=lambda p: (not p.is_dir(), p.name.lower()))[:300]:
        try:
            stat = entry.stat()
        except OSError:
            continue
        entries.append({"name": entry.name, "type": "dir" if entry.is_dir() else "file", "size": None if entry.is_dir() else stat.st_size})
    return {"path": str(path), "entries": entries, "truncated": budget_exhausted or len(matches) > 300}


async def _list_directory(ctx: ToolContext, args: dict) -> dict:
    path = _path(args.get("path", ""))
    if not path.is_dir():
        raise ToolError(f"cartella inesistente: {path}")
    pattern = args.get("pattern") or "*"
    return await asyncio.to_thread(_scan_directory, path, pattern)


async def _read_file(ctx: ToolContext, args: dict) -> dict:
    path = _path(args.get("path", ""))
    if not path.is_file():
        raise ToolError(f"file inesistente: {path}")
    offset = max(0, int(args.get("offset") or 0))
    settings = ctx.settings.get()
    if path.suffix.lower() in SUPPORTED_EXTS:
        try:
            parsed = await asyncio.to_thread(parse_file, path, build_engine(settings.ocr, settings.endpoints))
        except Exception as exc:  # noqa: BLE001 - corrupt documents
            raise ToolError(f"lettura non riuscita: {exc}") from exc
        text = parsed.text
    else:
        raw = path.read_bytes()[: 4 * 2**20]
        if b"\x00" in raw[:4096]:
            raise ToolError("file binario non leggibile come testo")
        text = raw.decode("utf-8", errors="replace")
    chunk, truncated = _truncate(text[offset:])
    return {"path": str(path), "offset": offset, "total_chars": len(text), "content": chunk, "truncated": truncated}


async def _write_file(ctx: ToolContext, args: dict) -> dict:
    path = _path(args.get("path", ""))
    content = args.get("content")
    if content is None:
        raise ToolError("contenuto mancante")
    if path.exists() and not args.get("overwrite"):
        raise ToolError(f"{path} esiste già; usa overwrite=true per sostituirlo o edit_file per modificarlo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "bytes": len(content.encode("utf-8"))}


async def _edit_file(ctx: ToolContext, args: dict) -> dict:
    path = _path(args.get("path", ""))
    old, new = args.get("old_text"), args.get("new_text")
    if not path.is_file():
        raise ToolError(f"file inesistente: {path}")
    if not old:
        raise ToolError("old_text mancante")
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise ToolError(f"old_text deve comparire esattamente una volta, trovato {count} volte")
    path.write_text(text.replace(old, new or "", 1), encoding="utf-8")
    return {"path": str(path), "replaced": 1}


# ---------------------------------------------------------------------- shell


# powershell.exe/pwsh accept -EncodedCommand (and -EncodedArguments) under abbreviated
# forms: every prefix (-e, -enc, -enco…), the aliases -ec/-ea, and the '/' or Unicode
# dash prefixes (–, —, ―). The check applies ONLY to tokens following an explicit
# powershell/pwsh invocation: `node -e …` or `Get-Content -Enc UTF8` are legitimate
# and must not be flagged. Quoted tokens still count: PowerShell strips the quotes and
# treats '-e' as the switch anyway. This guard is a tripwire, not a sandbox.
_PWSH_NAMES = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
_PWSH_DASHES = ("-", "/", "\u2013", "\u2014", "\u2015")
_ENCODED_PARAM = ("encodedcommand", "encodedarguments")
_TOKEN = re.compile(r'"[^"\r\n]*"|\'[^\'\r\n]*\'|\S+')


def _uses_encoded_command(command: str) -> bool:
    tokens = _TOKEN.findall(command)
    # Scan from every powershell/pwsh invocation: nested calls are the dangerous ones.
    for i, token in enumerate(tokens):
        quoted = token[:1] in "\"'"
        inner = token.strip('"\'').lstrip("&").strip()
        # Bug #11: compare the invoked executable by FILE NAME, so a full path
        # (C:\...\powershell.exe) or an &-call ("C:\Program Files\...\pwsh.exe")
        # names the same binary as the bare alias.
        if inner and PureWindowsPath(inner).name.lower() in _PWSH_NAMES:
            for arg in tokens[i + 1 :]:
                # Bug #11: '-e <b64>' (Start-Process -ArgumentList) arrives as ONE
                # quoted token containing a space — the effective switch is its
                # first word.
                words = arg.strip('"\'').split()
                word = words[0] if words else ""
                if not word.startswith(_PWSH_DASHES):
                    continue
                name = word.lstrip("".join(_PWSH_DASHES)).lower()
                # "encoded…" starts with "en": -ec/-ea are two-letter aliases, not prefixes.
                if name and (name in ("ec", "ea") or any(param.startswith(name) for param in _ENCODED_PARAM)):
                    return True
        elif quoted and " " in inner and _uses_encoded_command(inner):
            # Bug #11: cmd /c "powershell -e …" hides a whole command line inside one
            # quoted token — re-examine its contents as a command.
            return True
    return False


async def _run_powershell(ctx: ToolContext, args: dict) -> dict:
    command = (args.get("command") or "").strip()
    if not command:
        raise ToolError("comando mancante")
    if _uses_encoded_command(command):
        raise ToolError("comandi codificati non ammessi: scrivi il comando in chiaro")
    cwd = _path(args["cwd"]) if args.get("cwd") else Path.home()
    if not cwd.is_dir():
        raise ToolError(f"cartella di lavoro inesistente: {cwd}")
    timeout = max(1, min(int(args.get("timeout_seconds") or 60), POWERSHELL_TIMEOUT_MAX))
    script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'; " + command
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        timed_out = False
    except asyncio.TimeoutError:
        subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stdout, stderr = await proc.communicate()
        timed_out = True
    out, out_trunc = _truncate(stdout.decode("utf-8", errors="replace"), 6000)
    err, _ = _truncate(stderr.decode("utf-8", errors="replace"), 2000)
    return {"exit_code": proc.returncode, "timed_out": timed_out, "stdout": out, "stderr": err, "truncated": out_trunc, "cwd": str(cwd)}


# ---------------------------------------------------------------------- web


async def _web_search(ctx: ToolContext, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolError("query mancante")
    try:
        results = await web_search(query, max_results=max(1, min(int(args.get("max_results") or 5), 10)))
    except WebError as exc:
        raise ToolError(str(exc)) from exc
    return {"query": query, "results": [r.model_dump() for r in results]}


async def _fetch_url(ctx: ToolContext, args: dict) -> dict:
    try:
        return await fetch_url((args.get("url") or "").strip(), max_chars=MAX_RESULT_CHARS)
    except WebError as exc:
        raise ToolError(str(exc)) from exc


# ---------------------------------------------------------------------- planning


async def _task_list(ctx: ToolContext, args: dict) -> dict:
    raw = args.get("tasks")
    if not isinstance(raw, list) or not raw:
        raise ToolError("tasks deve essere una lista non vuota")
    try:
        tasks = [Task(id=str(t.get("id") or i), content=str(t["content"]), status=t.get("status", "pending")) for i, t in enumerate(raw, 1)]
    except (KeyError, ValueError, AttributeError) as exc:
        raise ToolError(f"task non validi: {exc}") from exc
    ctx.thread.tasks = tasks
    ctx.save_thread(ctx.thread)
    return {"tasks": [t.model_dump() for t in tasks]}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "vault_search",
            "Semantic search in the user's local document Vaults (contracts, manuals, emails, scans…). "
            "Use it first for any question about the user's own documents. Returns passages with file, page and score.",
            _obj(
                {
                    "query": {"type": "string", "description": "What to look for, as a short natural-language query"},
                    "vault": {"type": "string", "description": "Optional Vault name to restrict the search"},
                    "k": {"type": "integer", "description": "Number of passages (1-12, default 5)"},
                },
                ["query"],
            ),
            _vault_search,
        ),
        Tool("list_vaults", "List the available document Vaults with their size.", _obj({}, []), _list_vaults),
        Tool(
            "list_directory",
            "List files and folders in a local directory.",
            _obj(
                {
                    "path": {"type": "string", "description": "Absolute folder path, e.g. C:\\Users\\name\\Documents"},
                    "pattern": {"type": "string", "description": "Optional glob such as *.pdf"},
                },
                ["path"],
            ),
            _list_directory,
        ),
        Tool(
            "read_file",
            "Read a local file as text. Office files, PDFs (with OCR for scans), images, emails and text files are converted to text.",
            _obj(
                {
                    "path": {"type": "string", "description": "Absolute file path"},
                    "offset": {"type": "integer", "description": "Character offset to continue a truncated read"},
                },
                ["path"],
            ),
            _read_file,
        ),
        Tool(
            "write_file",
            "Create a UTF-8 text file (e.g. .md, .txt, .csv). Fails if it exists unless overwrite is true.",
            _obj(
                {
                    "path": {"type": "string", "description": "Absolute file path"},
                    "content": {"type": "string", "description": "Full file content"},
                    "overwrite": {"type": "boolean", "description": "Replace an existing file"},
                },
                ["path", "content"],
            ),
            _write_file,
            risk="write",
        ),
        Tool(
            "edit_file",
            "Replace one exact occurrence of old_text with new_text in a UTF-8 text file.",
            _obj(
                {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "description": "Exact text to replace; must occur exactly once"},
                    "new_text": {"type": "string"},
                },
                ["path", "old_text", "new_text"],
            ),
            _edit_file,
            risk="write",
        ),
        Tool(
            "run_powershell",
            "Run a Windows PowerShell 5.1 command on the user's PC and return its output. "
            "Use for system information, file operations and automation. No interactive commands.",
            _obj(
                {
                    "command": {"type": "string", "description": "PowerShell command or script"},
                    "cwd": {"type": "string", "description": "Working directory (default: user profile)"},
                    "timeout_seconds": {"type": "integer", "description": "1-300, default 60"},
                },
                ["command"],
            ),
            _run_powershell,
            risk="execute",
        ),
        Tool(
            "web_search",
            "Search the web (DuckDuckGo) for current or public information not in the user's documents.",
            _obj(
                {
                    "query": {"type": "string", "description": "Short focused search query"},
                    "max_results": {"type": "integer", "description": "1-10, default 5"},
                },
                ["query"],
            ),
            _web_search,
            risk="network",
        ),
        Tool(
            "fetch_url",
            "Download a web page and return its readable text. Use after web_search to read a result.",
            _obj({"url": {"type": "string", "description": "http(s) URL"}}, ["url"]),
            _fetch_url,
            risk="network",
        ),
        Tool(
            "task_list",
            "Keep a checklist for multi-step work. Send the FULL list each time; keep at most one item in_progress.",
            _obj(
                {
                    "tasks": {
                        "type": "array",
                        "items": _obj(
                            {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            },
                            ["id", "content", "status"],
                        ),
                    }
                },
                ["tasks"],
            ),
            _task_list,
            needs_approval=False,  # only updates the plan shown in the chat
            risk="plan",
        ),
    ]
}


def parse_arguments(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"argomenti non sono JSON valido: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ToolError("gli argomenti devono essere un oggetto JSON")
    return value
