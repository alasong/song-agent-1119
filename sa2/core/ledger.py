"""append-only 账本：事件流是唯一真相，状态只是投影。

只允许追加：没有 update、没有 delete。这条限制就是它的全部价值——
一个能被回头改的账本，等于没有账本。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, actor: str, payload: dict | None = None) -> dict:
        event = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": kind,
            "actor": actor,
            "payload": payload or {},
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"kind": "corrupt", "raw": line[:200]})
        return out

    def count(self, kind: str) -> int:
        return sum(1 for e in self.read() if e.get("kind") == kind)

    def kinds(self) -> list[str]:
        return [e.get("kind", "") for e in self.read()]