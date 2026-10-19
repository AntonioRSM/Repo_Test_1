"""Vault registry, per-vault file manifest (SQLite) and vector store (LanceDB)."""

from __future__ import annotations

import fnmatch
import os
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import lancedb
import numpy as np
import pyarrow as pa
from pydantic import BaseModel, Field

from .chunking import ChunkingSettings
from .config import ModelRef, OcrSettings, data_dir, write_json_atomic
from .parsers import SUPPORTED_EXTS

Metric = Literal["cosine", "dot", "l2"]
FileStatus = Literal["pending", "indexed", "error", "skipped"]

DEFAULT_EXCLUDES = ["~$*", "*.tmp", "*.part", "*.crdownload", ".git", "node_modules", "$RECYCLE.BIN", "Thumbs.db", "desktop.ini"]


class VaultConfig(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    description: str = ""
    sources: list[str] = Field(default_factory=list)
    embedding: ModelRef
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    ocr: OcrSettings | None = None  # None = use the application default
    parser: Literal["builtin", "docling"] = "builtin"
    # Ask the configured LLM for a short document summary that is prepended to every
    # chunk before embedding (contextual retrieval).
    contextual_summary: bool = False
    watch: bool = True
    metric: Metric = "cosine"
    include_extensions: list[str] = Field(default_factory=lambda: sorted(SUPPORTED_EXTS))
    exclude_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    dimension: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def accepts(self, path: Path) -> bool:
        if path.suffix.lower() not in self.include_extensions:
            return False
        return not any(fnmatch.fnmatch(part, pattern) for part in path.parts for pattern in self.exclude_patterns)

    def source_of(self, path: Path) -> str | None:
        resolved = str(path.resolve()).lower()
        for source in self.sources:
            root = str(Path(source).resolve()).lower().rstrip("\\/")
            if resolved == root or resolved.startswith(root + "\\") or resolved.startswith(root + "/"):
                return source
        return None


class FileRecord(BaseModel):
    path: str
    source: str | None
    sha256: str | None
    size: int
    mtime: float
    status: FileStatus
    chunks: int = 0
    error: str | None = None
    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    language: str | None = None
    pages: int | None = None
    ocr_pages: int = 0
    ocr_engine: str | None = None
    updated_at: float = 0.0


MANIFEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    source TEXT,
    sha256 TEXT,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    status TEXT NOT NULL,
    chunks INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    title TEXT, author TEXT, created TEXT, modified TEXT, language TEXT,
    pages INTEGER, ocr_pages INTEGER NOT NULL DEFAULT 0, ocr_engine TEXT,
    updated_at REAL NOT NULL
);
"""

TABLE = "chunks"


def _schema(dim: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("text", pa.string()),
            pa.field("file_path", pa.string()),
            pa.field("file_name", pa.string()),
            pa.field("ext", pa.string()),
            pa.field("file_sha256", pa.string()),
            pa.field("chunk_index", pa.int32()),
            pa.field("heading", pa.string()),
            pa.field("page_start", pa.int32()),
            pa.field("page_end", pa.int32()),
            pa.field("title", pa.string()),
            pa.field("author", pa.string()),
            pa.field("created", pa.string()),
            pa.field("modified", pa.string()),
            pa.field("language", pa.string()),
            pa.field("ocr", pa.bool_()),
            pa.field("ingested_at", pa.string()),
        ]
    )


def quote_sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def escape_like(value: str) -> str:
    """Escapes the LIKE wildcards so a user query is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Vault:
    """One vault on disk: vault.json + manifest.sqlite + lancedb/."""

    def __init__(self, root: Path, config: VaultConfig) -> None:
        self.root = root
        self.config = config
        self._lock = threading.RLock()
        self._db = lancedb.connect(str(root / "lancedb"))
        self._manifest = sqlite3.connect(root / "manifest.sqlite", check_same_thread=False)
        self._manifest.row_factory = sqlite3.Row
        self._manifest.executescript(MANIFEST_SCHEMA)

    # ------------------------------------------------------------------ config

    def save_config(self) -> None:
        write_json_atomic(self.root / "vault.json", self.config.model_dump())

    # ------------------------------------------------------------------ manifest

    def files(self, status: str | None = None, offset: int = 0, limit: int = 500, query: str | None = None) -> list[FileRecord]:
        sql, args = "SELECT * FROM files WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if query:
            sql += " AND path LIKE ? ESCAPE '\\'"
            args.append(f"%{escape_like(query)}%")
        sql += " ORDER BY path LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._lock:
            return [FileRecord(**dict(row)) for row in self._manifest.execute(sql, args)]

    def file(self, path: str) -> FileRecord | None:
        with self._lock:
            row = self._manifest.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        return FileRecord(**dict(row)) if row else None

    def upsert_file(self, record: FileRecord) -> None:
        record.updated_at = time.time()
        data = record.model_dump()
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self._lock:
            self._manifest.execute(f"INSERT OR REPLACE INTO files ({cols}) VALUES ({marks})", list(data.values()))
            self._manifest.commit()

    def remove_file(self, path: str) -> None:
        with self._lock:
            self._manifest.execute("DELETE FROM files WHERE path = ?", (path,))
            self._manifest.commit()
            self.delete_chunks(path)

    def known_paths(self) -> dict[str, FileRecord]:
        return {r.path: r for r in self.files(limit=10**9)}

    def matching_paths(self, path: str) -> list[str]:
        """Every recorded path equal to `path` or under it as a folder (SQL prefix match,
        no full manifest scan — used by bulk removals)."""
        prefix = path.rstrip("\\/") + os.sep
        with self._lock:
            rows = self._manifest.execute(
                "SELECT path FROM files WHERE path = ? OR path LIKE ? ESCAPE '\\'",
                (path, escape_like(prefix) + "%"),
            ).fetchall()
        return [r["path"] for r in rows]

    def stats(self) -> dict:
        with self._lock:
            rows = self._manifest.execute(
                "SELECT status, COUNT(*) AS n, SUM(chunks) AS c, SUM(size) AS s, SUM(ocr_pages) AS o FROM files GROUP BY status"
            ).fetchall()
        by_status = {r["status"]: r["n"] for r in rows}
        return {
            "files": sum(by_status.values()),
            "by_status": by_status,
            "chunks": sum(r["c"] or 0 for r in rows),
            "bytes": sum(r["s"] or 0 for r in rows),
            "ocr_pages": sum(r["o"] or 0 for r in rows),
            "vectors": self.count_chunks(),
        }

    # ------------------------------------------------------------------ vectors

    def _table_names(self) -> list[str]:
        result = self._db.list_tables()
        # lancedb >= 0.25 returns a paginated response object instead of a list.
        return list(getattr(result, "tables", result))

    def _table(self):
        if TABLE in self._table_names():
            return self._db.open_table(TABLE)
        return None

    def count_chunks(self, where: str | None = None) -> int:
        table = self._table()
        return table.count_rows(where) if table is not None else 0

    def replace_chunks(self, file_path: str, rows: list[dict]) -> None:
        """Atomically (per file) swaps the vectors of one document."""
        with self._lock:
            table = self._table()
            if table is not None:
                table.delete(f"file_path = {quote_sql(file_path)}")
            if not rows:
                return
            dim = len(rows[0]["vector"])
            if self.config.dimension is None:
                self.config.dimension = dim
                self.save_config()
            elif dim != self.config.dimension:
                raise ValueError(
                    f"embedding dimension {dim} differs from the vault's {self.config.dimension}; "
                    "rebuild the vault to change embedding model"
                )
            batch = pa.Table.from_pylist(rows, schema=_schema(dim))
            if table is None:
                self._db.create_table(TABLE, batch)
            else:
                table.add(batch)

    def delete_chunks(self, file_path: str) -> None:
        with self._lock:
            table = self._table()
            if table is not None:
                table.delete(f"file_path = {quote_sql(file_path)}")

    def search(self, vector: list[float], k: int, metric: Metric, where: str | None = None) -> list[dict]:
        table = self._table()
        if table is None:
            return []
        query = table.search(vector).distance_type(metric).limit(k)
        if where:
            query = query.where(where, prefilter=True)
        rows = query.to_list()
        q = np.asarray(vector, dtype=np.float32)
        q_norm = float(np.linalg.norm(q)) or 1.0
        for row in rows:
            v = np.asarray(row["vector"], dtype=np.float32)
            dot = float(np.dot(q, v))
            row["scores"] = {
                "cosine": dot / (q_norm * (float(np.linalg.norm(v)) or 1.0)),
                "dot": dot,
                "euclidean": float(np.linalg.norm(q - v)),
            }
        return rows

    def list_chunks(self, offset: int, limit: int, file_path: str | None = None) -> list[dict]:
        table = self._table()
        if table is None:
            return []
        query = table.search().select(
            ["id", "text", "file_path", "file_name", "chunk_index", "heading", "page_start", "page_end", "title", "author", "language", "ocr"]
        )
        if file_path:
            query = query.where(f"file_path = {quote_sql(file_path)}")
        rows = query.limit(offset + limit).to_list()
        rows.sort(key=lambda r: (r["file_path"], r["chunk_index"]))
        return rows[offset : offset + limit]

    def projection(self, limit: int = 2000) -> list[dict]:
        """2D PCA of up to `limit` vectors for the vector explorer scatter plot."""
        table = self._table()
        if table is None:
            return []
        rows = table.search().select(["id", "vector", "file_name", "chunk_index", "text"]).limit(limit).to_list()
        if len(rows) < 3:
            return [{"id": r["id"], "x": 0.0, "y": 0.0, "file_name": r["file_name"], "chunk_index": r["chunk_index"], "preview": r["text"][:160]} for r in rows]
        matrix = np.array([r["vector"] for r in rows], dtype=np.float32)
        matrix -= matrix.mean(axis=0)
        _, _, vt = np.linalg.svd(matrix, full_matrices=False)
        coords = matrix @ vt[:2].T
        return [
            {"id": r["id"], "x": float(x), "y": float(y), "file_name": r["file_name"], "chunk_index": r["chunk_index"], "preview": r["text"][:160]}
            for r, (x, y) in zip(rows, coords)
        ]

    def reset_vectors(self) -> None:
        with self._lock:
            if TABLE in self._table_names():
                self._db.drop_table(TABLE)
            self._manifest.execute("DELETE FROM files")
            self._manifest.commit()
            self.config.dimension = None
            self.save_config()

    def close(self) -> None:
        with self._lock:
            self._manifest.close()


class VaultRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir() / "vaults"
        self.root.mkdir(parents=True, exist_ok=True)
        self._vaults: dict[str, Vault] = {}
        self._lock = threading.Lock()
        for folder in sorted(self.root.iterdir()):
            config_path = folder / "vault.json"
            if config_path.exists():
                config = VaultConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
                self._vaults[config.id] = Vault(folder, config)

    def list(self) -> list[Vault]:
        with self._lock:
            return sorted(self._vaults.values(), key=lambda v: v.config.created_at)

    def get(self, vault_id: str) -> Vault:
        with self._lock:
            vault = self._vaults.get(vault_id)
        if vault is None:
            raise KeyError(vault_id)
        return vault

    def create(self, config: VaultConfig) -> Vault:
        folder = self.root / config.id
        folder.mkdir(parents=True, exist_ok=False)
        vault = Vault(folder, config)
        vault.save_config()
        with self._lock:
            self._vaults[config.id] = vault
        return vault

    def delete(self, vault_id: str) -> None:
        with self._lock:
            vault = self._vaults.pop(vault_id)
        vault.close()
        # Only the vault's own index is removed; source documents are never touched.
        shutil.rmtree(vault.root, ignore_errors=True)
