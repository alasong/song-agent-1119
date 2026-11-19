"""收益账本：append-only，只有审计方写（设计文档 §15.1 / §15.8(1)）。

被考核方只能以 role="executor" 打开，任何写入直接抛错——否则账本会被被考核方刷，
G1 的「自主发起」读数就不可信（ROADMAP §6 风险表第一条）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class LedgerError(RuntimeError):
    """账本角色越权或记录非法。"""


class Ledger:
    def __init__(self, path, role: str = "auditor"):
        self.path = Path(path)
        self.role = role

    def _read_raw(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def append(self, kind: str, actor: str, payload: dict | None = None) -> dict:
        if self.role != "auditor":
            raise LedgerError(f"role={self.role} 无权写账本，账本只由审计方写")
        events = self._read_raw()
        event = {
            "seq": len(events) + 1,
            "ts": round(time.time(), 6),
            "kind": kind,
            "actor": actor,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read(self) -> list[dict]:
        return self._read_raw()

    def events(self, kind: str | None = None, actor: str | None = None) -> list[dict]:
        return [
            e for e in self._read_raw()
            if (kind is None or e["kind"] == kind)
            and (actor is None or e["actor"] == actor)
        ]

    def count(self, kind: str | None = None, actor: str | None = None) -> int:
        return len(self.events(kind, actor))