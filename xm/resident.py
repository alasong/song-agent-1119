"""常驻循环：没有人在场时，自己决定下一步做什么并推进。

与 daemon 的区别：daemon 是「给任务就跑」，resident 是「自己看状态、自己挑任务」。
G1 要的就是后者：24 小时里，任务不是启动时给定的一张清单，而是循环按当下状态挑的。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from xm.ledger import Ledger

Task = Callable[[], dict]


@dataclass
class ResidentConfig:
    interval_s: float = 600
    max_hours: float = 24
    max_ticks: int | None = None
    checkpoint: Path | None = None


@dataclass
class Resident:
    ledger: Ledger
    policy: Callable[[dict], tuple[str, Task]]  # (任务名, 任务函数)
    cfg: ResidentConfig
    state: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def tick(self) -> dict:
        name, task = self.policy(self.state)
        try:
            result = task()
            progressed = bool(result.get("progress", True))
        except Exception as exc:  # 任务坏了要记账，不能静默
            result = {"error": f"{type(exc).__name__}: {exc}"}
            progressed = False
        self.ledger.append("dispatch", "resident", {"task": name})
        if progressed:
            self.ledger.append("progress", "resident", {"task": name, **result})
        self.state.setdefault("done", []).append(name)
        self.state["progress_tasks"] = sum(
            1 for e in self.ledger.events("progress", "resident"))
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": name,
                  "progress": progressed, "result": result}
        self.history.append(record)
        self._checkpoint()
        return record

    def _checkpoint(self) -> None:
        if not self.cfg.checkpoint:
            return
        self.cfg.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.checkpoint.write_text(json.dumps({
            "ticks": len(self.history),
            "progress_tasks": self.state.get("progress_tasks", 0),
            "last": self.history[-1] if self.history else None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(self) -> dict:
        started = time.time()
        deadline = started + self.cfg.max_hours * 3600
        ticks = 0
        while time.time() < deadline:
            if self.cfg.max_ticks is not None and ticks >= self.cfg.max_ticks:
                break
            self.tick()
            ticks += 1
            if time.time() + self.cfg.interval_s > deadline:
                break
            time.sleep(self.cfg.interval_s)
        elapsed_hours = round((time.time() - started) / 3600, 4)
        return {
            "hours": elapsed_hours,
            "ticks": ticks,
            "progress_tasks": self.state.get("progress_tasks", 0),
            "distinct_tasks": len(set(self.state.get("done", []))),
            "tasks": self.state.get("done", []),
        }