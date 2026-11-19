"""目标队列：领导给的目标与自己提的目标放在同一个队列里，但领取规则不同。

这条规则就是红线在 L3 的形态：**自己提的目标，没有领导批准不许领取**。
否则 sa 可以自己立一个目标、自己定判据、自己判定完成——判定权那一道门再严也没用，
因为门判的是「这次交付合不合格」，没人判「这次该不该做」。
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

SOURCES = ("leader", "self")
STATUSES = ("pending", "done", "failed")


@dataclass(frozen=True)
class Goal:
    text: str
    dims: tuple[str, ...]
    criteria: tuple[str, ...]
    budget_tokens: int
    source: str = "leader"
    approved: bool = True          # self 提出时必须显式置 True 才能被领取
    status: str = "pending"
    id: str = field(default="", compare=False)

    def gid(self) -> str:
        # 不用内置 hash()：它按进程加盐，跨进程会给出不同 id
        if self.id:
            return self.id
        return f"{self.source}-{hashlib.sha1(self.text.encode('utf-8')).hexdigest()[:8]}"


class Backlog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def add(self, goal: Goal) -> Goal:
        if goal.source not in SOURCES:
            raise ValueError(f"来源只能是 {SOURCES}")
        if goal.status not in STATUSES:
            raise ValueError(f"状态只能是 {STATUSES}")
        data = asdict(goal)
        data["id"] = goal.gid()
        data["dims"] = list(goal.dims)
        data["criteria"] = list(goal.criteria)
        data["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")
        return goal

    def _rows(self):
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    def all(self) -> list[Goal]:
        """目标行 + 状态事件行分开读：状态只追加，不回头改历史。"""
        goals: dict[str, Goal] = {}
        status: dict[str, str] = {}
        for data in self._rows():
            if "text" in data:
                goal = Goal(text=data.get("text", ""), dims=tuple(data.get("dims") or ()),
                            criteria=tuple(data.get("criteria") or ()),
                            budget_tokens=int(data.get("budget_tokens") or 0),
                            source=data.get("source", "leader"),
                            approved=bool(data.get("approved", True)),
                            status=data.get("status", "pending"),
                            id=data.get("id", ""))
                goals[goal.gid()] = goal
            elif "id" in data and "status" in data:
                status[data["id"]] = data["status"]
        return [replace(g, status=status.get(gid, g.status)) for gid, g in goals.items()]

    def pick(self) -> Goal | None:
        """按顺序取第一个可领取的：领导给的优先，自助的必须已批准。"""
        for goal in self.all():
            if goal.status != "pending":
                continue
            if goal.source == "self" and not goal.approved:
                continue
            return goal
        return None

    def mark(self, goal: Goal, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"状态只能是 {STATUSES}")
        if goal.gid() not in {g.gid() for g in self.all()}:
            raise ValueError(f"队列里没有这个目标：{goal.gid()}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": goal.gid(), "status": status,
                                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                ensure_ascii=False) + "\n")

    def done_ids(self) -> set[str]:
        return {g.gid() for g in self.all() if g.status == "done"}
