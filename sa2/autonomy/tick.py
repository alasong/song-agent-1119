"""一次自主 tick：没人派活时，自己从队列里挑一个目标跑完一圈。

红线在 L3 的形态落在两处，缺一处这一层就没意义：
1. **自己提的目标**必须 `approved=True` 才能被领取（`Backlog.pick` 负责）——
   否则 sa 可以自己立目标、自己判定完成。
2. **目标要的判据**必须已经被外部登记（这里查 `judge.names()`）——
   否则它会拿一个自己造的判据去验收自己。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.gate import Declaration
from ..core.judge import Judge
from ..core.ledger import Ledger
from ..forge.org import OrgPlan
from ..loop import size
from ..loop.pdca import PDCA
from ..memory.cases import CaseBook
from .backlog import Backlog, Goal


@dataclass
class TickResult:
    ran: bool
    reason: str = ""
    goal: Goal | None = None
    scale: str = ""
    report: dict = field(default_factory=dict)


def tick(backlog: Backlog, ledger: Ledger, judge: Judge, produce, vocab,
         team_plan: OrgPlan | None = None, usage: list[dict] | None = None,
         evidence=None, max_stage_attempts: int = 2,
         cases: CaseBook | None = None) -> TickResult:
    goal = backlog.pick()
    if goal is None:
        return TickResult(False, "没有可领取的目标")

    missing = [c for c in goal.criteria if c not in judge.names()]
    if missing:
        return TickResult(False, f"判据未登记：{missing}（要领导批准后才能开工）", goal=goal)

    decl = Declaration(goal=goal.text, dims=goal.dims, criteria=goal.criteria,
                       budget_tokens=goal.budget_tokens)
    plan, decision = size.plan_for(decl, team_plan)
    pdca = PDCA(judge, ledger, plan, produce, vocab, usage=usage,
                max_stage_attempts=max_stage_attempts, cases=cases)
    report = pdca.run(decl, evidence=evidence)
    backlog.mark(goal, "done" if report["passed"] else "failed")
    ledger.append("tick", "autonomy", {"goal": goal.text, "scale": decision.scale,
                                       "passed": report["passed"]})
    return TickResult(True, decision.reason, goal=goal, scale=decision.scale, report=report)