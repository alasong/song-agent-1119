"""L2：PDCA 环。声明 → 前置门 → 逐阶段（产出 → 阶段门）→ 交付门 → 证据门。

与 sa 1.0 的实质差别只有一条，但它是全部价值所在：
**被拒时只重做这一阶段**，不是整篇重来。1.0 的返工是「把整篇文档再写一遍」，
所以一次拒绝的代价是整篇的 token；这里拒绝的代价只有这一阶段的产出。

阶段门与交付门是两层，不许合并：
- 阶段门判「这一段能不能进下一段」（结构、要素齐不齐）
- 交付门判「整篇能不能交」（声明里的全部判据）
合并的后果是——中间某一格不合格要到最后一刻才被发现，等于又回到 1.0。
"""
from __future__ import annotations

from pathlib import Path

from ..core import gate
from ..core.budget import Budget
from ..core.gate import Declaration
from ..core.judge import Judge
from ..core.ledger import Ledger
from ..forge.org import OrgPlan


class PDCA:
    def __init__(self, judge: Judge, ledger: Ledger, plan: OrgPlan, produce: "callable",
                 vocab, usage: list[dict] | None = None,
                 max_stage_attempts: int = 2):
        """produce(role, stage, upstream, attempt, feedback) -> str。

        feedback 是上一轮这一阶段被拒的原因；第一次尝试为空串。
        带上它的理由很实际：sa 1.0 的整篇重写虽然也带反馈，但代价是整篇；
        2.0 只重做一格，如果这一格不知道上次错在哪，等于把省下的钱又亏回去。
        """
        self.judge = judge
        self.ledger = ledger
        self.plan = plan
        self.produce = produce
        self.vocab = vocab
        self.usage = usage
        self.max_stage_attempts = max_stage_attempts

    def run(self, decl: Declaration, seed: str = "", evidence=None) -> dict:
        # ① 前置门：任何一条不成立，一次调用都不发
        pre = gate.pre_flight(decl, self.judge, self.vocab)
        if not pre["ok"]:
            self.ledger.append("preflight_reject", "gate", {"problems": pre["problems"]})
            return self._report(False, "前置门未过", problems=pre["problems"])

        budget = Budget(decl.budget_tokens, usage=self.usage if self.usage is not None else [])
        text = seed
        ran: set[str] = set()
        rejects: list[dict] = []
        redone: list[str] = []
        dispatches = 0

        for stage in self.plan.stages:
            feedback = ""                      # 上一轮被拒的原因：重做必须带着它，否则是盲重做
            for attempt in range(1, self.max_stage_attempts + 1):
                parts: list[str] = []
                for role_name in stage.roles:
                    if budget.exhausted():
                        self.ledger.append("budget_stop", "loop", budget.snapshot())
                        return self._report(False, budget.why(f"{stage.name}·{role_name} 之前"),
                                            redone=redone, rejects=rejects,
                                            dispatches=dispatches, budget=budget)
                    role = self.plan.role(role_name)
                    out = self.produce(role, stage.name, text, attempt, feedback)
                    budget.note(out)
                    dispatches += 1
                    self.ledger.append("dispatch", role_name,
                                       {"stage": stage.name, "attempt": attempt, "chars": len(out)})
                    parts.append(out)

                candidate = "\n\n".join(p for p in parts if p and p.strip())
                problems: list[str] = []
                for name in stage.gate_criteria:
                    verdict = self.judge.run(name, candidate)
                    ran.add(name)
                    problems.extend(verdict.problems)

                if not problems:
                    text = candidate
                    self.ledger.append("stage_ok", stage.name, {"attempt": attempt})
                    break

                feedback = "；".join(problems)
                rejects.append({"stage": stage.name, "attempt": attempt, "problems": problems})
                self.ledger.append("reject", "stage_gate",
                                   {"stage": stage.name, "attempt": attempt, "problems": problems})
                if attempt == self.max_stage_attempts:
                    return self._report(
                        False, f"阶段「{stage.name}」连续 {attempt} 次未过阶段门",
                        redone=redone, rejects=rejects, dispatches=dispatches, budget=budget)
                # 只重做这一阶段：下游还没跑，上游不用重来
                redone.append(stage.name)
                self.ledger.append("redo_stage", stage.name, {"attempt": attempt})

        # ② 交付门：声明里的全部判据
        delivery: list[str] = []
        for name in decl.criteria:
            verdict = self.judge.run(name, text)
            ran.add(name)
            delivery.extend(f"{name}: {p}" for p in verdict.problems)

        # ③ 证据门 + ④ 不静默失败
        evidence = list(evidence or ())
        evidence_problems = gate.check_evidence(evidence)
        silent = gate.check_silent_failure(self.judge, decl, ran)
        problems = delivery + evidence_problems + silent
        passed = not problems
        self.ledger.append("delivery", "gate",
                           {"passed": passed, "problems": problems, "chars": len(text)})
        return self._report(passed, "" if passed else "交付门/证据门未过",
                            redone=redone, rejects=rejects, dispatches=dispatches,
                            budget=budget, problems=problems, evidence=evidence,
                            chars=len(text), ran=sorted(ran))

    def _report(self, passed: bool, reason: str, *, problems=(), redone=(), rejects=(),
                dispatches: int = 0, budget: Budget | None = None, evidence=(),
                chars: int = 0, ran=()) -> dict:
        return {
            "passed": passed,
            "reason": reason,
            "problems": list(problems),
            "redone": list(redone),
            "rejects": list(rejects),
            "dispatches": dispatches,
            "budget": budget.snapshot() if budget else None,
            "evidence": list(evidence),
            "ran": list(ran),
            "chars": chars,
            "ledger": str(self.ledger.path) if isinstance(self.ledger.path, Path) else str(self.ledger.path),
        }