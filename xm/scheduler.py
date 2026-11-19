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


class DispatchStopped(RuntimeError):
    """派活中途必须停（预算用尽等）。worker 抛它，调度器收尾并落 stopped 读数。

    为什么由 worker 抛而不是调度器自己算：调度器不知道一次派活花了多少 token，
    只有真发过请求的那一层知道。调度器负责的是「停了之后把账记清」。
    """


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

    def run(self, plan: dict | None = None, worker=None) -> dict:
        plan = plan or getattr(self, "plan", None)
        if not plan:
            raise ValueError("没有编制方案可派")
        roles = plan.get("roles") or []
        process = plan.get("process") or []
        if not roles or not process:
            raise ValueError("编制方案缺 roles 或 process")

        upstream: dict | None = None
        last_producer: dict | None = None
        artifacts: list[dict] = []
        reworks = 0
        stopped = ""
        try:
            for stage in process:
                for role in roles:
                    self.ledger.append("dispatch", "scheduler", {
                        "stage": stage, "role": role["name"], "kind": role["kind"],
                    })
                    self.dispatch_log.append(Dispatch(stage, role["name"], role["kind"]))

                    # 干活 + 交接：产物必须带上游 id，否则链路是断的
                    if worker is not None:
                        artifact = worker(role, stage, upstream)
                    else:
                        artifact = {
                            "id": f"{stage}:{role['name']}",
                            "upstream": upstream["id"] if upstream else None,
                            "stage": stage,
                            "role": role["name"],
                        }
                    artifacts.append(artifact)
                    self.ledger.append("progress", role["name"],
                                       {"stage": stage, "artifact": artifact.get("id"),
                                        "upstream": artifact.get("upstream")})

                    # 验证拒绝 → 触发一次返工：只判不改等于白判（每阶段最多一次）
                    if artifact.get("verdict") == "reject" and last_producer and worker is not None:
                        rework = worker(last_producer, f"{stage}·返工", artifact)
                        rework = dict(rework)
                        rework["id"] = f"{stage}:{last_producer['name']}:rework"
                        rework["upstream"] = artifact["id"]
                        rework["rework_reason"] = artifact.get("reason", "")
                        artifacts.append(rework)
                        reworks += 1
                        self.ledger.append("rework", last_producer["name"],
                                           {"stage": stage, "reason": artifact.get("reason", ""),
                                            "artifact": rework["id"]})
                        artifact = rework

                    if role.get("kind") != "verifier":
                        last_producer = role
                    upstream = artifact
        except DispatchStopped as exc:
            stopped = str(exc)
            self.ledger.append("dispatch_stopped", "scheduler",
                               {"stopped": stopped, "dispatches": len(self.dispatch_log)})

        chain_ok = all(
            artifacts[i].get("upstream") == artifacts[i - 1].get("id")
            for i in range(1, len(artifacts))
        ) and len(artifacts) > 1

        kinds = {d.kind for d in self.dispatch_log}
        names = {d.role for d in self.dispatch_log}
        return {
            "stages": len(process),
            # dispatches=真的产出了产物的派活；attempts=记过账的尝试（含被预算掐掉的那次）
            "dispatches": len(artifacts),
            "dispatch_attempts": len(self.dispatch_log),
            "handoffs": max(0, len(artifacts) - 1),
            "reworks": reworks,
            "chain_ok": chain_ok,
            "distinct_roles": len(names),
            "distinct_kinds": len(kinds),
            "has_verifier": "verifier" in kinds,
            "stopped": stopped,
        }