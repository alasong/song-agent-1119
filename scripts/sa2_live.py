"""用真实模型跑一轮 sa2。五个自生成回路都能单独开，另外支持断点续跑。

  --auto-goal      造目标：forge/goal.decompose
  --auto-criteria  造判据：模型出「规格 + 最小合格样例」，整组四反例
  --auto-stages    造阶段判据（scope=stage），并让**交付判据与编制同源**
  --auto-org       造组织：forge/org.plan_org（被自己校验拒了带原因重试）
  --auto-tools     造工具：生成 Python 检查器，三反例准入
  --fresh          不用跨运行判据库（默认用 ~/xm-runs/sa2/registry）
  --resume PATH    从某个 state.json 续跑

退出码：0 = 环跑完且拿到真实 usage；1 = 通道/流程出错。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core import gate                         # noqa: E402
from sa2.core.gate import Declaration             # noqa: E402
from sa2.core.judge import Judge, replace         # noqa: E402
from sa2.core.ledger import Ledger                # noqa: E402
from sa2.forge import criteria as fc              # noqa: E402
from sa2.forge import dims as fd                  # noqa: E402
from sa2.forge import goal as fg                  # noqa: E402
from sa2.forge import org as fo                   # noqa: E402
from sa2.forge import tools as ft                 # noqa: E402
from sa2.forge.scribe import Scribe               # noqa: E402
from sa2.loop import size                         # noqa: E402
from sa2.loop.pdca import PDCA                    # noqa: E402
from sa2.memory import registry                   # noqa: E402
from sa2.memory.cases import CaseBook             # noqa: E402
from xm.llm import complete_usage                 # noqa: E402

GOAL = "写一份「Agent 递归自我改进的最小可行实验」方案"

SPEC = """必须包含：## 一、基线
必须包含：## 二、改动
必须包含：## 三、止损
必须出现：验收方式：
"""


def runs_root() -> Path:
    return Path(os.environ.get("XM_RUNS", str(Path.home() / "xm-runs"))).expanduser()


def make_llm(usage: list[dict]):
    def llm(messages, max_tokens: int = 1200):
        text, u = complete_usage(messages, model="deepseek-flash", max_tokens=max_tokens,
                                 extra={"thinking": {"type": "disabled"}})
        usage.append(u or {})
        return text
    return llm


def _register(judge: Judge, specs) -> list[str]:
    for crit in specs:
        judge.register(crit, proposer="leader")
    return [c.name for c in specs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--goal", default=GOAL)
    ap.add_argument("--spec-file", default=None)
    ap.add_argument("--budget", type=int, default=60_000)
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--name", default="sa2-live")
    ap.add_argument("--auto-goal", action="store_true")
    ap.add_argument("--auto-criteria", action="store_true")
    ap.add_argument("--auto-stages", action="store_true")
    ap.add_argument("--auto-org", action="store_true")
    ap.add_argument("--auto-tools", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="不用跨运行判据库")
    ap.add_argument("--resume", default=None, help="从 state.json 续跑")
    args = ap.parse_args()

    goal = args.goal
    hand_spec = (Path(args.spec_file).expanduser().read_text(encoding="utf-8")
                 if args.spec_file else SPEC)
    spec = hand_spec

    run_dir = runs_root() / args.name / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")

    if args.fresh:
        judge = Judge(authority=("leader",), path=run_dir / "criteria.json",
                      history=run_dir / "criteria-history.jsonl", ledger=ledger)
        cases = CaseBook(run_dir / "cases.jsonl")
        registry_used = ""
    else:
        judge = Judge(authority=("leader",), path=registry.criteria_path(),
                      history=registry.criteria_history_path(), ledger=ledger)
        cases = CaseBook(registry.cases_path())
        registry_used = str(registry.root())

    usage: list[dict] = []
    llm = make_llm(usage)
    notes: dict[str, str] = {}

    # ① 造目标
    subtasks = None
    if args.auto_goal:
        subtasks = fg.decompose(goal, llm, fd.VOCAB)
        (run_dir / "subtasks.json").write_text(json.dumps(
            [{"name": s.name, "deliverable": s.deliverable, "dims": list(s.dims)} for s in subtasks],
            ensure_ascii=False, indent=2), encoding="utf-8")
        dims = tuple(sorted({d for s in subtasks for d in s.dims}))
    else:
        dims = ("correctness",)

    provisional = Declaration(goal=goal, dims=dims, criteria=(), budget_tokens=args.budget)

    # ② 先定编制（自动阶段判据需要编制才能按阶段造）
    org_error = ""
    plan = None
    decision = None
    if args.auto_stages:
        if args.auto_org:
            try:
                plan = fo.plan_org(goal, llm, budget_cap=args.budget, criteria=judge.names(),
                                   require_gates=False)
                decision = size.SizeDecision("team", f"自生成编制：{len(plan.roles)} 角色 / "
                                                     f"{len(plan.stages)} 阶段", args.budget)
            except fo.OrgError as exc:
                org_error = str(exc)
        if plan is None:
            plan = size.single_plan(provisional)
            decision = size.SizeDecision("single", "自动阶段判据需要编制：回退单人", args.budget)

    # ③ 造阶段判据；交付判据 = 最后一个「写正文」阶段的判据的 delivery 副本（同源）
    stage_specs: dict[str, list] = {}
    gates: dict[str, tuple[str, ...]] = {}
    if args.auto_stages:
        for stage in plan.stages:
            made = fc.propose_spec(goal, llm,
                                   context=f"当前阶段：{stage.name}\n本阶段要交的东西：{stage.output}")
            try:
                specs = fc.tested_set(fc.instantiate_all(made["spec"], dims,
                                                         prefix=f"{stage.name}·", scope="stage"),
                                      sample=made["sample"] or None)
            except ValueError as exc:
                notes[f"stage_spec_fallback:{stage.name}"] = str(exc)
                specs = []
            stage_specs[stage.name] = specs
            gates[stage.name] = tuple(_register(judge, specs)) if specs else ()
            (run_dir / f"stage-spec-{stage.name}.md").write_text(made["raw"], encoding="utf-8")

        empty = [st.name for st in plan.stages if not stage_specs.get(st.name)]
        if empty:
            # 静默给它塞交付判据 = 又回到「假分层」：中间阶段被迫交完整文档。
            # 判据造不出来就不开工，比跑一遍注定红的环便宜。
            print(f"这些阶段没有可用判据：{empty}；判据不可满足或自测未过，先停机。",
                  file=sys.stderr)
            (run_dir / "readings.json").write_text(json.dumps(
                {"passed": False, "reason": f"阶段判据缺失：{empty}", "notes": notes},
                ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        writers = [st for st in plan.stages if st.mode == "replace"] or list(plan.stages)
        writer = writers[-1]
        delivery_specs = [replace(c, name=f"交付·{c.name}", scope="delivery")
                          for c in stage_specs.get(writer.name, [])]
        if not delivery_specs:
            notes["delivery_source"] = f"写正文阶段「{writer.name}」没有判据，退回人工规格"
    else:
        delivery_specs = []
        if args.auto_criteria:
            made = fc.propose_spec(goal, llm, context=("可参考的任务约束：\n" + hand_spec
                                                      if args.spec_file else ""))
            (run_dir / "proposed_spec.md").write_text(made["raw"], encoding="utf-8")
            try:
                delivery_specs = fc.tested_set(fc.instantiate_all(made["spec"], dims),
                                               sample=made["sample"] or None)
                spec = made["spec"]
            except ValueError as exc:
                notes["criteria_fallback"] = f"自拟判据未过四反例，退回人工规格：{exc}"
        if not delivery_specs:
            struct_items, content_items = fc.split_spec(hand_spec)
            cands = []
            if struct_items:
                cands.append(fc.propose_sections("章节齐全", struct_items, dims))
            if content_items:
                cands.append(fc.propose_content("关键要素", content_items, dims))
            if not cands:
                print("没有可用的判据来源", file=sys.stderr)
                return 1
            delivery_specs = fc.tested_set(cands) if len(cands) > 1 else [fc.tested(cands[0])]

    _register(judge, delivery_specs)
    decl = Declaration(goal=goal, dims=dims,
                       criteria=tuple(c.name for c in delivery_specs),
                       budget_tokens=args.budget)

    # ④ 编制收口：补阶段门、最后一阶段装配、交付要求下发到写正文的人
    if args.auto_stages:
        plan = fo.attach_stage_gates(plan, {st.name: gates.get(st.name) or tuple(decl.criteria)
                                            for st in plan.stages})
        stages = list(plan.stages)
        if len(stages) > 1:
            stages[-1] = replace(stages[-1], mode="append")
        plan = replace(plan, stages=tuple(stages))
        plan = fo.close_with_delivery(plan, decl.criteria)
    elif plan is None:
        if args.auto_org:
            try:
                plan = fo.plan_org(goal, llm, budget_cap=args.budget, criteria=judge.names())
                decision = size.SizeDecision("team", f"自生成编制：{len(plan.roles)} 角色 / "
                                                     f"{len(plan.stages)} 阶段", args.budget)
            except fo.OrgError as exc:
                org_error = str(exc)
        if plan is None:
            plan, decision = size.plan_for(decl)

    # ⑤ 造工具：给第一个阶段挂一个生成的检查器
    tool_error = ""
    tool_path = ""
    if args.auto_tools and plan.stages:
        first_specs = stage_specs.get(plan.stages[0].name) or delivery_specs
        required = [h for c in first_specs if c.kind == "sections"
                    for h in (c.spec.get("required") or [])]
        try:
            tool_path_obj, tool_crit = ft.generate_checker(
                goal, required, llm, run_dir / "tools", name="stage1_checker")
            judge.register(tool_crit, proposer="leader")
            first = plan.stages[0]
            plan = fo.attach_stage_gates(plan, {
                **{st.name: st.gate_criteria for st in plan.stages},
                first.name: tuple(first.gate_criteria) + (tool_crit.name,),
            })
            tool_path = str(tool_path_obj)
        except (ValueError, OSError) as exc:
            tool_error = str(exc)

    # ⑥ 跑环（带断点）
    state_path = Path(args.resume) if args.resume else run_dir / "state.json"
    scribe = Scribe(llm, spec=spec, max_tokens=args.max_tokens)
    pdca = PDCA(judge, ledger, plan, scribe, fd.VOCAB, usage=usage,
                max_stage_attempts=2, cases=cases,
                state_path=state_path, resume=bool(args.resume),
                artifact_dir=run_dir / "stages")
    report = pdca.run(decl, evidence=[])

    artifact = run_dir / "deliverable.md"
    artifact.write_text(report.get("text") or "", encoding="utf-8")
    evidence = [f"{artifact}:1", f"dispatches={report['dispatches']}"]
    evidence_problems = gate.check_evidence(evidence)
    delivery_ok = report["passed"] and not evidence_problems

    readings = {
        "goal": goal,
        "scale": decision.scale if decision else "",
        "scale_reason": decision.reason if decision else "",
        "passed": delivery_ok,
        "delivery_passed": report["passed"],
        "reason": report["reason"],
        "problems": report["problems"],
        "evidence_problems": evidence_problems,
        "dispatches": report["dispatches"],
        "rejects": len(report["rejects"]),
        "redone": report["redone"],
        "chars": report["chars"],
        "budget": report["budget"],
        "exact_usage": bool((report["budget"] or {}).get("exact")),
        "criteria": judge.names(),
        "delivery_criteria": [c.name for c in delivery_specs],
        "subtasks": [s.name for s in subtasks] if subtasks else [],
        "org_generated": bool(args.auto_org and not org_error),
        "org_error": org_error,
        "tool": tool_path,
        "tool_error": tool_error,
        "notes": notes,
        "registry": registry_used,
        "plan": {"roles": [r.name for r in plan.roles],
                 "stages": [st.name for st in plan.stages],
                 "modes": [st.mode for st in plan.stages],
                 "gates": {st.name: list(st.gate_criteria) for st in plan.stages}},
        "ledger": str(ledger.path),
        "run_dir": str(run_dir),
    }
    (run_dir / "readings.json").write_text(json.dumps(readings, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    ok = bool(readings["exact_usage"]) and report["dispatches"] >= 1

    if args.json:
        print(json.dumps({**readings, "ok": ok}, ensure_ascii=False, indent=2))
    else:
        print("sa 2.0 真模型跑一轮")
        print(f"  目标：{goal}")
        if subtasks:
            print(f"  自造目标：{len(subtasks)} 个子任务")
        print(f"  交付判据：{'、'.join(c.name for c in delivery_specs)}（"
              f"{'与编制同源' if args.auto_stages else '来自规格'}）")
        if args.auto_stages:
            for st in plan.stages:
                print(f"      阶段「{st.name}」[{st.mode}] 门：{'、'.join(st.gate_criteria)}")
        if args.auto_org:
            print(f"  自造编制：{'成功' if not org_error else '失败→回退'} "
                  f"（{len(plan.roles)} 角色 / {len(plan.stages)} 阶段）")
            if org_error:
                print(f"      拒收原因：{org_error}")
        if args.auto_tools:
            print(f"  自造工具：{'成功 ' + tool_path if tool_path else '失败：' + tool_error}")
        for key, note in notes.items():
            print(f"  注：{key} — {note}")
        print(f"  派活 {report['dispatches']} 次，拒绝 {len(report['rejects'])} 次，"
              f"重做 {report['redone'] or '无'}")
        b = report["budget"] or {}
        print(f"  预算：{b.get('spent')}/{b.get('tokens')} tokens "
              f"（{'真实 usage' if b.get('exact') else '字符估算'}），调用 {b.get('calls')} 次")
        print(f"  证据门：{'过' if not evidence_problems else evidence_problems}")
        print(f"  结果：passed={delivery_ok}" + (f"，{report['reason']}" if report["reason"] else ""))
        for problem in report["problems"]:
            print(f"      红：{problem}")
        print(f"  账本：{readings['ledger']}")
        print(f"  读数：{run_dir / 'readings.json'}")
        print(f"结论：{'跑通' if ok else '未跑通'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())