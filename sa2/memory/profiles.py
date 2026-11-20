"""角色档案：一个角色要有身份、有战绩、有未偿承诺，才谈得上「谁死了、谁接」。

S1 只做「档案能落盘、能重读、能交出接管包」；接管动作本身在 S2（Supervisor）里。
档案与编制（OrgPlan）分开存：编制是一次派活的计划，档案是这个人跨任务的连续性。

为什么 calibration 先是 None：P0 还没有自评（§11.1 已按目标判掉），None 表示「未知」，
不是 0.0——0.0 会被读成「校准完美」，是假读数。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import registry


@dataclass
class RoleProfile:
    id: str
    kind: str
    duty: str = ""
    tools: tuple = ()
    record: dict = field(default_factory=lambda: {"done": 0, "rejected": 0, "takeovers": 0})
    calibration: float | None = None          # 空壳：None = 还没有真值
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
    promises: list = field(default_factory=list)   # 未偿承诺：跨任务不丢
    criteria_version: str = ""
    status: str = "active"                    # active / frozen（冻结不是删除）
    generation: int = 1                       # 继任代次：同一 id，第 N 任

    def bump(self, key: str) -> None:
        self.record[key] = int(self.record.get(key, 0)) + 1

    def add_promise(self, text: str, goal: str = "") -> dict:
        item = {"id": f"p-{uuid.uuid4().hex[:8]}", "text": text, "goal": goal,
                "status": "pending", "created_at": time.time()}
        self.promises.append(item)
        return item

    def resolve_promise(self, promise_id: str) -> bool:
        """了结一条承诺。不存在或已了结返回 False（不静默成功）。"""
        for item in self.promises:
            if item.get("id") == promise_id and item.get("status") != "done":
                item["status"] = "done"
                item["closed_at"] = time.time()
                return True
        return False

    def pending_promises(self) -> list[dict]:
        return [dict(x) for x in self.promises if x.get("status") == "pending"]

    def handover(self) -> dict:
        """交给继任者的那一包：只带未偿承诺，不带已了结的。"""
        return {
            "role_id": self.id,
            "kind": self.kind,
            "duty": self.duty,
            "tools": list(self.tools),
            "promises": self.pending_promises(),
            "record": dict(self.record),
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "criteria_version": self.criteria_version,
            "generation": self.generation,
        }


_FIELDS = {f.name for f in fields(RoleProfile)}


def _from_row(row: dict) -> RoleProfile:
    data = {k: row[k] for k in _FIELDS if k in row}
    data["tools"] = tuple(data.get("tools") or ())
    return RoleProfile(**data)


class RoleStore:
    """追加写的 JSONL 档案库；同 id 多行时以最后一行为准（历史不覆盖）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else registry.ensure() / "roles.jsonl"

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows: list[dict] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"角色档案第 {number} 行坏了：{self.path}: {exc}") from exc
        return rows

    def save(self, profile: RoleProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = asdict(profile)
        row["updated_at"] = time.time()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def all(self) -> list[RoleProfile]:
        latest: dict[str, RoleProfile] = {}
        for row in self._rows():
            try:
                profile = _from_row(row)
            except (KeyError, TypeError) as exc:
                raise ValueError(f"角色档案缺字段：{row!r}") from exc
            latest[profile.id] = profile
        return list(latest.values())

    def get(self, role_id: str) -> RoleProfile:
        for profile in self.all():
            if profile.id == role_id:
                return profile
        raise KeyError(role_id)

    def by_kind(self, kind: str) -> list[RoleProfile]:
        return [p for p in self.all() if p.kind == kind]