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
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core import gate                         # noqa: E402
from sa2.core.gate import Declaration             # noqa: E402
from sa2.core.evidence import EvidenceBook, citation_problems     # noqa: E402
from sa2.core.judge import Criterion, Judge, replace  # noqa: E402
from sa2 import fetch                              # noqa: E402
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
from sa2.memory.tools import ToolStore            # noqa: E402
from sa2.llm import complete_usage                # noqa: E402

HAND_TOOLS = ("fetch:arxiv",)   # 宿主级的手：要证据的交付，至少得有它
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


def _arxiv_query(llm, goal: str, role) -> str:
    """让模型写一条检索语句：题面里的缩写（如 RSI）只有它自己分得清是哪一行。"""
    ask = (f"给 arXiv API 写一条 search_query，主题：{goal}；检索意图：{role.duty}。"
           f"**只用英文关键词**，不要出现中文；**查询要短：2–4 个词**，不要 AND/OR 列表；"
           f"只返回一条查询语句（形如 all:\"xxx\"），不要解释。")
    raw = llm([{"role": "user", "content": ask}], max_tokens=80) or ""
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    # 中文关键词在 arXiv 上基本等于零命中：先剥成 ASCII，剥完为空就当场报，不硬查
    ascii_only = re.sub(r"[^\x20-\x7e]", " ", first).strip()
    query = re.sub(r"\s+", " ", ascii_only).strip("`").strip()
    if not query:
        raise fetch.FetchError(f"模型没给出可用的英文查询（原始：{first[:60]!r}）")
    return query if ":" in query else f'all:"{query}"'


def _simplify_candidates(query: str) -> list[str]:
    """零命中时按词数递减给出更松的查询，而不是「简化」一次就完。

    实测：`all:"AI research automation planning"`（四词短语）零命中，同名的三词
    有好几条、两词有更多。旧版只取引号里的短语——查询本身已是短语时原样返回，
    于是「降级」降成了原地不动，整轮死在这一次取数上。
    这里返回的候选不含入参本身，也不会重复；词数不足三个时返回空表（真没法再松）。
    """
    ascii_only = re.sub(r"[^\x20-\x7e]", " ", query or "")
    quoted = re.search(r'"([^"]+)"', ascii_only)
    if quoted:
        words = re.findall(r"[A-Za-z][A-Za-z\-]+", quoted.group(1))
    else:
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]+", ascii_only)
                 if w.lower() not in {"and", "or", "not", "all", "latest", "recent"}]
    seen = {query.strip()}
    out: list[str] = []
    for n in range(len(words) - 1, 1, -1):
        candidate = f'all:"{" ".join(words[:n])}"'
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def make_hand(llm, goal: str, book: EvidenceBook, content_dir):
    """手的实现：查一次 arXiv → 落盘打戳成证据 → 交回一段可引用的素材。"""
    def hand(role, stage: str) -> str:
        query = _arxiv_query(llm, goal, role)
        tried = [query]
        items = None
        try:
            items = fetch.arxiv(query, 5)
        except fetch.FetchError as exc:
            first = exc
            for candidate in _simplify_candidates(query):
                tried.append(candidate)
                try:
                    items = fetch.arxiv(candidate, 5)
                except fetch.FetchError:
                    continue
                query = candidate          # 命中的那条进素材标题，读数里能看出退到了哪一档
                break
            if items is None:
                raise fetch.FetchError(f"查询都没取到（试过 {tried}）：{first}") from first
        evs = fetch.record(items, book, content_dir, "leader", start=len(book.all()) + 1)
        lines = [f"## 已取回的证据（正文只能引用这些编号；查询 {query}）"]
        for ev, item in zip(evs, items):
            lines.append(f"[{ev.evidence_id}] {item['title']}（{item['published']}）{item['url']}")
            lines.append(f"  摘要：{item['summary'][:280]}")
        return "\n".join(lines)
    return hand


def _tool_caps(store: ToolStore) -> dict[str, str]:
    """工具名 → 能力标签。编制校验靠它判「这个角色手上是不是真有能用的手」。"""
    caps = {name: str(entry.get("capability") or "") for name, entry in store.all().items()}
    caps["fetch:arxiv"] = "fetch"   # 宿主级的手：不进工具库，但编制可以把它挂到角色上
    return caps


def shelve(store: ToolStore, path, crit, signature: str):
    """把生成的脚本收进工具库，并把判据的 cmd 改指向库里的稳定地址。

    不入库的检查器是「一次性的刀」：run 目录一清，注册表里那条判据的 `cmd`
    就指向一个不存在的文件——真跑里那把断刀就是这么来的。
    """
    entry = store.store(path, name=crit.name, owner="leader", signature=signature,
                        self_test={"ok": True, "cases": "生成时已跑过三反例"})
    crit = replace(crit, spec={**crit.spec,
                               "cmd": [sys.executable, entry["path"], "{target}"]})
    return entry, crit


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
    ap.add_argument("--parallel", action="store_true", help="同一阶段的角色并发派活")
    ap.add_argument("--evidence-min", type=int, default=3,
                    help="交付至少要几条可追引用；0 = 不要求（默认 3）")
    ap.add_argument("--reuse", action="store_true",
                    help="同目标已有判据就复用，不再让模型重新造")
    args = ap.parse_args()

    goal = args.goal
    hand_spec = (Path(args.spec_file).expanduser().read_text(encoding="utf-8")
                 if args.spec_file else SPEC)
    spec = hand_spec

    run_dir = runs_root() / args.name / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    evidence_book = EvidenceBook(run_dir / "evidence.jsonl")
    # 造出来的东西要有家：工具进全局库（不随 run 目录消失），判据的 cmd 指向库里
    tool_store = ToolStore()

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
                                   require_gates=False, available_tools=_tool_caps(tool_store))
                decision = size.SizeDecision("team", f"自生成编制：{len(plan.roles)} 角色 / "
                                                     f"{len(plan.stages)} 阶段", args.budget)
            except fo.OrgError as exc:
                org_error = str(exc)
        if plan is None:
            plan = size.single_plan(provisional, tools=HAND_TOOLS if args.evidence_min else ())
            decision = size.SizeDecision("single", "自动阶段判据需要编制：回退单人", args.budget)

    # ③a 复用：同目标已登记过判据就直接用，省掉一次模型调用
    reused = False
    if args.reuse and not args.fresh and not args.auto_stages:
        index = registry.load_goal_index()
        names = index.get(registry.fingerprint(goal)) or []
        existing = [judge.get(n) for n in names]
        if names and all(existing):
            delivery_specs = [c for c in existing if c and c.scope == "delivery"]
            if delivery_specs:
                reused = True
                notes["reused_from_registry"] = f"{len(delivery_specs)} 条判据（版本 " \
                    + "、".join(str(c.version) for c in delivery_specs) + "）"

    # ③ 造判据：一份交付样例定义结构，各阶段只负责自己的切片（切片互不重叠 → 不重复）
    stage_specs: dict[str, list] = {}
    gates: dict[str, tuple[str, ...]] = {}
    if args.auto_stages:
        made = fc.propose_spec(goal, llm, context=("可参考的任务约束：\n" + hand_spec
                                                  if args.spec_file else ""))
        (run_dir / "proposed_spec.md").write_text(made["raw"], encoding="utf-8")
        sample = (made.get("sample") or "").strip()
        heads = ft.headings_of(sample)
        if not heads:
            print("交付样例里没有 `## ` 标题，无法切分阶段结构，先停机。", file=sys.stderr)
            (run_dir / "readings.json").write_text(json.dumps(
                {"passed": False, "reason": "交付样例无标题", "notes": notes},
                ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        delivery_specs = [fc.tested(fc.propose_sections("交付·章节", heads, dims))]
        try:
            raw, full_tool = ft.checker_from_sections(sample, run_dir / "tools",
                                                      name="delivery-sections",
                                                      allow_foreign=False)
            _, full_tool = shelve(tool_store, raw, full_tool, "<script> <target.md> → rc0/1")
            delivery_specs.append(fc.replace(full_tool, name="交付·正文下限", scope="delivery"))
        except ValueError as exc:
            notes["delivery_checker_fallback"] = str(exc)

        writers = [st for st in plan.stages if st.mode == "replace"] or list(plan.stages)
        chunks = fc.plan_slices(heads, len(writers))
        # 样例给的标题比阶段少时，把多余阶段并进最后一个拿到切片的阶段。
        # 结构由样例定义、编制服从；不让它落进「没切片 → 兜成全部交付判据」那条路。
        plan, writers, dropped = fo.collapse_uncovered(plan, writers, len(chunks))
        if dropped:
            notes["stage_merge"] = (f"{len(dropped)} 个阶段并进「{writers[-1].name}」："
                                    f"样例只给了 {len(heads)} 个标题")
            ledger.append("stage_merge", "live",
                          {"into": writers[-1].name, "dropped": list(dropped)})
        for order, (stage, chunk) in enumerate(zip(writers, chunks)):
            piece = fc.slice_sample(sample, chunk)
            specs = [fc.tested(fc.replace(
                fc.propose_sections(f"{stage.name}·章节", chunk, dims), scope="stage"))]
            try:
                raw, tool = ft.checker_from_sections(
                    piece, run_dir / "tools", name=f"stage-{stage.name}-sections",
                    # 第一个阶段从零写，越界就是错；后面的阶段是追加，上游章节合法。
                    allow_foreign=(order > 0))
                _, tool = shelve(tool_store, raw, tool, "<script> <target.md> → rc0/1")
                specs.append(fc.replace(tool, name=f"{stage.name}·正文下限", scope="stage"))
            except ValueError as exc:
                notes[f"checker_fallback:{stage.name}"] = str(exc)
            stage_specs[stage.name] = specs
            gates[stage.name] = tuple(_register(judge, specs))
            (run_dir / f"slice-{stage.name}.md").write_text(piece, encoding="utf-8")
        for stage in plan.stages:
            if stage.name not in stage_specs:
                stage_specs[stage.name] = list(delivery_specs)
                gates[stage.name] = ()
    elif not reused:
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

    if args.evidence_min > 0:
        # 交付必须带可追证据：判据自己带着台账路径与条数门槛，不把数字写死在代码里
        delivery_specs.append(Criterion(
            name="交付·引用", kind="callable", dims=(), self_tested=True, scope="delivery",
            spec={"target": "sa2.core.evidence:check_citations",
                  "book": str(evidence_book.path), "min": args.evidence_min}))
        # 列了编号就等于声称出处：arXiv id / DOI 必须能在台账里找到，不许凭记忆写
        delivery_specs.append(Criterion(
            name="交付·出处", kind="callable", dims=(), self_tested=True, scope="delivery",
            spec={"target": "sa2.core.evidence:check_references",
                  "book": str(evidence_book.path)}))
    _register(judge, delivery_specs)
    if not args.fresh and not args.auto_stages and delivery_specs:
        registry.remember_goal(goal, [c.name for c in delivery_specs])
    decl = Declaration(goal=goal, dims=dims,
                       criteria=tuple(c.name for c in delivery_specs),
                       budget_tokens=args.budget)

    # ④ 编制收口：补阶段门、最后一阶段装配、交付要求下发到写正文的人
    if args.auto_stages:
        plan = fo.attach_stage_gates(plan, {st.name: gates.get(st.name) or tuple(decl.criteria)
                                            for st in plan.stages})
        # 切片模式：第一个阶段是 replace（它就是第一篇），后面全部 append（各自追加自己那片）。
        # 每个标题只由一个人写一次，所以装配后不会重复——这正是上一版 26 个标题的根因。
        stages = list(plan.stages)
        for i in range(1, len(stages)):
            stages[i] = replace(stages[i], mode="append")
        plan = replace(plan, stages=tuple(stages))
    elif plan is None:
        if args.auto_org:
            try:
                plan = fo.plan_org(goal, llm, budget_cap=args.budget, criteria=judge.names(),
                                   available_tools=_tool_caps(tool_store))
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
            entry, tool_crit = shelve(tool_store, tool_path_obj, tool_crit,
                                      "<script> <target.md> → rc0/1")
            judge.register(tool_crit, proposer="leader")
            first = plan.stages[0]
            plan = fo.attach_stage_gates(plan, {
                **{st.name: st.gate_criteria for st in plan.stages},
                first.name: tuple(first.gate_criteria) + (tool_crit.name,),
            })
            tool_path = entry["path"]
        except (ValueError, OSError) as exc:
            tool_error = str(exc)

    # ⑥ 跑环（带断点）
    state_path = Path(args.resume) if args.resume else run_dir / "state.json"
    # 切片模式下不能再把整份任务规格塞给执笔角色：它一看见六节就会把整篇写出来，
    # 阶段门随即判它越界。每个阶段的「验收要求」已经写明它只该写哪几节。
    scribe = Scribe(llm, spec=("" if args.auto_stages else spec), max_tokens=args.max_tokens)
    pdca = PDCA(judge, ledger, plan, scribe, fd.VOCAB, usage=usage,
                max_stage_attempts=2, cases=cases, parallel=args.parallel,
                state_path=state_path, resume=bool(args.resume),
                artifact_dir=run_dir / "stages",
                hand=make_hand(llm, goal, evidence_book, run_dir / "evidence-content"))
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
        "reused": reused,
        "subtasks": [s.name for s in subtasks] if subtasks else [],
        "org_generated": bool(args.auto_org and not org_error),
        "org_error": org_error,
        "tool": tool_path,
        "evidence_count": len(evidence_book.all()),
        "citation_problems": citation_problems(report.get("text") or "", evidence_book),
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