"""最小调度：3 角色 + 心跳 + 无进展检测 + 自动降级（设计文档 §15.2 / §15.8(1)）。

stub 主体：Agent.productive 决定这一轮有没有产出事实。它存在的意义是证明
「活性读数由机制产生」，而不是由 prompt 演出来——所以关掉机制（XM_DISABLE_LIVENESS=1）
时，被观察的行为必须消失。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from xm.ledger import Ledger

Verifier = Callable[["Agent", int], bool]


@dataclass
class Agent:
    name: str
    subtree: str
    productive: bool = True
    budget: float = 100.0
    status: str = "active"  # active | readonly | frozen
    no_progress: int = 0
    dispatched: int = 0


def liveness_from_env() -> bool:
    return os.environ.get("XM_DISABLE_LIVENESS") != "1"


class Runner:
    def __init__(
        self,
        ledger: Ledger,
        agents: list[Agent],
        n_no_progress: int = 2,
        liveness_enabled: bool | None = None,
        verifier: Verifier | None = None,
    ):
        self.ledger = ledger
        self.agents = list(agents)
        self.n = n_no_progress
        self.liveness = liveness_from_env() if liveness_enabled is None else liveness_enabled
        self.verifier: Verifier = verifier or (lambda agent, rnd: True)
        self.round = 0

    def tick(self) -> None:
        self.round += 1
        if not self.liveness:
            return
        for agent in self.agents:
            self._tick_agent(agent)

    def _tick_agent(self, agent: Agent) -> None:
        if agent.status == "frozen":
            return
        if agent.status == "readonly":
            agent.no_progress += 1
            self._maybe_freeze(agent)
            return

        agent.dispatched += 1
        self.ledger.append(
            "autonomous_dispatch", agent.name,
            {"subtree": agent.subtree, "round": self.round},
        )

        progress = False
        if agent.productive:
            self.ledger.append("submission", agent.name, {"round": self.round})
            if self.verifier(agent, self.round):
                self.ledger.append("fact", agent.name, {"round": self.round})
            else:
                self.ledger.append("rejected", agent.name, {"round": self.round})
                self.ledger.append(
                    "self_correction", agent.name, {"reason": "verifier_rejected"}
                )
                self.ledger.append(
                    "fact", agent.name, {"round": self.round, "corrected": True}
                )
            progress = True

        if progress:
            agent.no_progress = 0
        else:
            agent.no_progress += 1
            self._maybe_downgrade(agent)

    def _maybe_downgrade(self, agent: Agent) -> None:
        if agent.status == "active" and agent.no_progress >= self.n:
            agent.status = "readonly"
            agent.budget *= 0.5
            self.ledger.append(
                "downgrade", agent.name,
                {"no_progress": agent.no_progress, "budget": agent.budget},
            )

    def _maybe_freeze(self, agent: Agent) -> None:
        if agent.status == "readonly" and agent.no_progress >= 2 * self.n:
            agent.status = "frozen"
            self.ledger.append("freeze", agent.name, {"no_progress": agent.no_progress})

    def readings(self) -> dict:
        accepted = self.ledger.count("fact")
        rejected = self.ledger.count("rejected")
        total = accepted + rejected
        return {
            "autonomous_dispatch": self.ledger.count("autonomous_dispatch"),
            "self_correction": self.ledger.count("self_correction"),
            "rejection_rate": round(rejected / total, 4) if total else 0.0,
        }