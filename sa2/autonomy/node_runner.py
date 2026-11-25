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


def make_runner(judge, ledger, vocab, produce=None, *, pool=None, prompt_builder=None,
                job_module="sa2.loop.jobs", job_func="section_llm", max_tokens=1200,
                timeout=300, usage=None, team_plan_factory=None, cases=None,
                artifact_dir=None):
    """运行器：给 produce 就在进程内跑；给 pool + prompt_builder 就让派活进 worker。

    节点一次执行；每次执行记一条 `node_run`（带 node_id / 派活数 / 是否走 worker），
    事后才能回答“哪个节点用了几个进程”。
    """
    built_for_worker = produce is None and pool is not None
    if produce is None:
        if pool is None or prompt_builder is None:
            raise ValueError("要么给 produce，要么给 pool + prompt_builder（节点在子进程执行）")
        from ..loop.pool_producer import PoolProducer
        produce = PoolProducer(pool, prompt_builder, max_tokens=max_tokens,
                               timeout=timeout, job_module=job_module,
                               job_func=job_func, usage=usage)

    def run(node) -> dict:
        plan, decl = plan_for_node(node, team_plan_factory)
        pdca = PDCA(judge, ledger, plan, produce, vocab, cases=cases,
                    artifact_dir=artifact_dir)
        report = pdca.run(decl)
        if ledger is not None:
            ledger.append("node_run", "node_runner",
                          {"id": node.id, "ok": bool(report.get("passed")),
                           "dispatches": int(report.get("dispatches") or 0),
                           "worker": built_for_worker,
                           "rejects": len(report.get("rejects") or []),
                           "reason": str(report.get("reason") or "")})
        return {"ok": bool(report.get("passed")),
                "text": str(report.get("text") or ""),
                "evidence": tuple(report.get("evidence") or ())}
    return run
