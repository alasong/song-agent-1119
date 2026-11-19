"""M0a 退出实验：20 轮 stub，读三个数。

用法：python3 scripts/m0a_demo.py
产物：reports/m0a.json（读数）、reports/m0a_ledger.jsonl（账本证据）
"""
from __future__ import annotations

import json
from pathlib import Path

from xm.ledger import Ledger
from xm.runner import Agent, Runner

ROUNDS = 20


def main() -> dict:
    out = Path("reports")
    out.mkdir(exist_ok=True)
    ledger = Ledger(out / "m0a_ledger.jsonl")

    agents = [
        Agent("alice", "goal/a"),                      # 正常产出
        Agent("bob", "goal/b"),                        # 首次被打回，需自我纠偏
        Agent("carol", "goal/c", productive=False),    # 无产出，应被降级并冻结
    ]

    seen: dict[str, int] = {}

    def verifier(agent: Agent, rnd: int) -> bool:
        if agent.name == "bob":
            n = seen.get(agent.name, 0)
            seen[agent.name] = n + 1
            return n > 0
        return True

    runner = Runner(ledger, agents, n_no_progress=2, verifier=verifier)
    for _ in range(ROUNDS):
        runner.tick()

    summary = {
        "rounds": ROUNDS,
        "readings": runner.readings(),
        "agents": [
            {
                "name": a.name,
                "status": a.status,
                "budget": a.budget,
                "dispatched": a.dispatched,
                "no_progress": a.no_progress,
            }
            for a in agents
        ],
    }
    (out / "m0a.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()