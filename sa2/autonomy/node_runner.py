"""节点运行器：把节点接到既有环上。

- 叶子 = 单角色单阶段（`size.single_plan`），一次执行；
- 小组 = 调用方给的编制（`team_plan_factory`），仍走同一条 PDCA；
- 每次调用只跑一次，返工由编排层新起节点，复用上下文属于越界。
"""
from __future__ import annotations

from ..core.gate import Declaration
from ..loop import size
from ..loop.pdca import PDCA


def plan_for_node(node, team_plan_factory=None):
    """节点 → (编制, 声明)。小组节点必须有编制工厂，不猜。"""
    decl = Declaration(goal=node.goal, dims=tuple(node.dims),
                       criteria=tuple(node.criteria), budget_tokens=int(node.budget))
    if node.unit == "group":
        if team_plan_factory is None:
            raise ValueError("小组节点需要 team_plan_factory：编制不由运行器现猜")
        return team_plan_factory(decl), decl
    return size.single_plan(decl), decl


def make_runner(judge, ledger, vocab, produce, *, team_plan_factory=None,
                cases=None, artifact_dir=None):
    def run(node) -> dict:
        plan, decl = plan_for_node(node, team_plan_factory)
        pdca = PDCA(judge, ledger, plan, produce, vocab, cases=cases,
                    artifact_dir=artifact_dir)
        report = pdca.run(decl)
        return {"ok": bool(report.get("passed")),
                "text": str(report.get("text") or ""),
                "evidence": tuple(report.get("evidence") or ())}
    return run