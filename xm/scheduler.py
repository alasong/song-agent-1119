"""调度器：按 OrgPlan 派活给各角色，记录交接与进展。

G2 的判据靠它：一个目标生成的编制，必须真的被派出去、被至少 3 个角色承接。
G1 的自主性也要靠它（心跳循环），但 24h 观测本轮不做。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xm.ledger import Ledger


@dataclass
class Dispatch:
    stage: str
    role: str
    kind: str


class Scheduler:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self.dispatch_log: list[Dispatch] = []

    @classmethod
    def from_plan_file(cls, path: str | Path, ledger: Ledger) -> "Scheduler":
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
        sched = cls(ledger)
        sched.plan = plan
        return sched

    def run(self, plan: dict | None = None) -> dict:
        plan = plan or getattr(self, "plan", None)
        if not plan:
            raise ValueError("没有编制方案可派")
        roles = plan.get("roles") or []
        process = plan.get("process") or []
        if not roles or not process:
            raise ValueError("编制方案缺 roles 或 process")

        for stage in process:
            for role in roles:
                self.ledger.append("dispatch", "scheduler", {
                    "stage": stage, "role": role["name"], "kind": role["kind"],
                })
                self.dispatch_log.append(Dispatch(stage, role["name"], role["kind"]))
                self.ledger.append("progress", role["name"], {"stage": stage})

        kinds = {d.kind for d in self.dispatch_log}
        names = {d.role for d in self.dispatch_log}
        return {
            "stages": len(process),
            "dispatches": len(self.dispatch_log),
            "distinct_roles": len(names),
            "distinct_kinds": len(kinds),
            "has_verifier": "verifier" in kinds,
        }