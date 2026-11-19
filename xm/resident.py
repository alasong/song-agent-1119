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
    already_elapsed_h: float = 0.0
    already_slept_h: float = 0.0


@dataclass
class Resident:
    ledger: Ledger
    policy: Callable[[dict], tuple[str, Task]]  # (任务名, 任务函数)
    cfg: ResidentConfig
    state: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.session_start = time.time()
        self.session_mono = time.monotonic()

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
        # 运行时长用单调时钟：睡眠期间 monotonic 不走，不会被算成“在跑”
        running_h = round(self.cfg.already_elapsed_h
                          + (time.monotonic() - self.session_mono) / 3600, 4)
        wall_h = round((time.time() - self.session_start) / 3600, 4)
        slept_h = round(self.cfg.already_slept_h + max(0.0, wall_h - running_h
                                                       + self.cfg.already_elapsed_h), 4)
        self.cfg.checkpoint.write_text(json.dumps({
            "running_hours": running_h,
            "slept_hours": slept_h,
            "ticks": len(self.history),
            "progress_tasks": self.state.get("progress_tasks", 0),
            "last": self.history[-1] if self.history else None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _elapsed_h(self) -> float:
        return self.cfg.already_elapsed_h + (time.monotonic() - self.session_mono) / 3600

    def run(self) -> dict:
        started = time.monotonic()
        ticks = 0
        # 关键：必须跑满窗口，不能因为「下一次睡眠会越过 deadline」就提前收工——
        # 那会算出 23.8h，24h 判据永远过不了。
        while self._elapsed_h() < self.cfg.max_hours:
            if self.cfg.max_ticks is not None and ticks >= self.cfg.max_ticks:
                break
            self.tick()
            ticks += 1
            remaining_s = (self.cfg.max_hours - self._elapsed_h()) * 3600
            if remaining_s <= 0:
                break
            time.sleep(min(self.cfg.interval_s, remaining_s))
        elapsed_hours = round(self._elapsed_h(), 4)
        slept_hours = round(self.cfg.already_slept_h, 4)
        return {
            "hours": elapsed_hours,
            "slept_hours": slept_hours,
            "ticks": ticks,
            "progress_tasks": self.state.get("progress_tasks", 0),
            "distinct_tasks": len(set(self.state.get("done", []))),
            "tasks": self.state.get("done", []),
        }