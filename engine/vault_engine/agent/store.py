"""Conversation persistence (SQLite): threads and their message history."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..config import ModelRef, data_dir

Role = Literal["user", "assistant", "tool"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT,
    vault_ids TEXT NOT NULL DEFAULT '[]',
    auto_approve TEXT NOT NULL DEFAULT '[]',
    tasks TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread_id, seq);
"""


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON text as produced by the model


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    thread_id: str
    seq: int = 0
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    meta: dict = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)

    def to_openai(self) -> dict:
        msg: dict = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in self.tool_calls
            ]
        if self.role == "tool":
            msg["tool_call_id"] = self.tool_call_id
            if self.name:
                msg["name"] = self.name
        return msg


class Task(BaseModel):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed"] = "pending"


class Thread(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "Nuova conversazione"
    model: ModelRef | None = None
    vault_ids: list[str] = Field(default_factory=list)  # empty = all vaults
    auto_approve: list[str] = Field(default_factory=list)  # tools allowed for the whole thread
    tasks: list[Task] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class AgentStore:
    def __init__(self, path: Path | None = None) -> None:
        self._db = sqlite3.connect(path or data_dir() / "agent.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ threads

    def _thread(self, row: sqlite3.Row) -> Thread:
        return Thread(
            id=row["id"],
            title=row["title"],
            model=ModelRef.model_validate_json(row["model"]) if row["model"] else None,
            vault_ids=json.loads(row["vault_ids"]),
            auto_approve=json.loads(row["auto_approve"]),
            tasks=json.loads(row["tasks"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_thread(self, thread: Thread) -> Thread:
        thread.updated_at = time.time()
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO threads (id, title, model, vault_ids, auto_approve, tasks, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thread.id,
                    thread.title,
                    thread.model.model_dump_json() if thread.model else None,
                    json.dumps(thread.vault_ids),
                    json.dumps(thread.auto_approve),
                    json.dumps([t.model_dump() for t in thread.tasks]),
                    thread.created_at,
                    thread.updated_at,
                ),
            )
            self._db.commit()
        return thread

    def thread(self, thread_id: str) -> Thread:
        with self._lock:
            row = self._db.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise KeyError(thread_id)
        return self._thread(row)

    def threads(self) -> list[Thread]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM threads ORDER BY updated_at DESC").fetchall()
        return [self._thread(r) for r in rows]

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            self._db.commit()

    # ------------------------------------------------------------------ messages

    def append(self, message: Message) -> Message:
        with self._lock:
            row = self._db.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE thread_id = ?", (message.thread_id,)).fetchone()
            message.seq = row[0]
            self._db.execute(
                "INSERT INTO messages (id, thread_id, seq, role, content, tool_calls, tool_call_id, name, meta, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message.id,
                    message.thread_id,
                    message.seq,
                    message.role,
                    message.content,
                    json.dumps([c.model_dump() for c in message.tool_calls]) if message.tool_calls else None,
                    message.tool_call_id,
                    message.name,
                    json.dumps(message.meta, ensure_ascii=False, default=str),
                    message.created_at,
                ),
            )
            self._db.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (time.time(), message.thread_id))
            self._db.commit()
        return message

    def messages(self, thread_id: str) -> list[Message]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY seq", (thread_id,)).fetchall()
        return [
            Message(
                id=r["id"],
                thread_id=r["thread_id"],
                seq=r["seq"],
                role=r["role"],
                content=r["content"],
                tool_calls=[ToolCall(**c) for c in json.loads(r["tool_calls"])] if r["tool_calls"] else None,
                tool_call_id=r["tool_call_id"],
                name=r["name"],
                meta=json.loads(r["meta"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
