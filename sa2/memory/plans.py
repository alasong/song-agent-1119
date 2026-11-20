"""编制的跨运行复用：同一组输入不重造编制。

键是**复合键**：只按 goal 缓存会把「同目标、不同预算/判据/工具/标题」的编制当成同一份
（设计 §8 实测过的坑）。判据按集合规范化——顺序不同不算新条件。

存的是纯 JSON（roles/stages），不 import forge，避免 memory ↔ forge 循环依赖；
OrgPlan 与 JSON 的互转放在 `forge/org.py` 那一侧。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from . import registry


class PlanStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else registry.plans_path()

    def key(self, goal: str, budget_cap: int, criteria, tools, headings, notes=()) -> str:
        payload = {
            "goal": (goal or "").strip(),
            "budget": int(budget_cap or 0),
            "criteria": sorted(str(x) for x in (criteria or ())),
            "tools": sorted(f"{n}:{c or ''}" for n, c in dict(tools or {}).items()),
            "headings": [str(x) for x in (headings or ())],
            "notes": [str(x) for x in (notes or ())],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"编制库坏了：{self.path}: {exc}") from exc

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, key: str) -> dict | None:
        row = self._load().get(key)
        return dict(row.get("plan") or {}) if row else None

    def put(self, key: str, plan: dict) -> None:
        data = self._load()
        row = data.get(key) or {"uses": 0, "created_at": time.time()}
        row["plan"] = plan
        row["uses"] = int(row.get("uses") or 0) + 1
        row["last_used_at"] = time.time()
        data[key] = row
        self._save(data)

    def mark_reuse(self, key: str) -> None:
        data = self._load()
        row = data.get(key)
        if row is None:
            return
        row["uses"] = int(row.get("uses") or 0) + 1
        row["last_used_at"] = time.time()
        self._save(data)