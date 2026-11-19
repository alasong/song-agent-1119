"""sa 跑任务：目标进 → 组织出 → 统一交付 → 独立验收 → 必要时返工。

与单 agent daemon 的区别：daemon 是「一个执行者」；sa 是「会组织执行者的那一层」。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from xm.hiring import plan_org
from xm.kb import KnowledgeBase, as_prompt_block, default_path, writeback_if_passed
from xm.ledger import Ledger
from xm.scheduler import Scheduler


def _call(llm, prompt: str, max_tokens: int = 3000) -> str:
    return llm([{"role": "user", "content": prompt}], max_tokens)


def role_prompt(spec: str, goal: str, role: dict, stage: str,
                upstream: dict | None, fact_block: str = "") -> str:
    """角色提示词。顺序按缓存友好排：共用规格在前，易变内容在后。

    知识底座检索到的已验证事实插在规格之后——只取不用等于买了书只对页码。
    """
    upstream_text = (upstream or {}).get("content", "")[:1200] or "（无，你是第一个）"
    facts = f"\n{fact_block}\n" if fact_block else ""
    return f"""## 任务规格（所有角色共用，判据按它判）
{spec}

## 组织目标
{goal}
{facts}
## 你的角色
你是「{role['name']}」，职责：{role['duty']}
你的验收方式：{role['criteria']}

当前阶段：{stage}
上游交付：
```
{upstream_text}
```

给出你在这一阶段的交付，不超过 300 字，只写交付物本身。"""


def _run_check(check: Path, target: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(check), str(target)],
                          cwd=check.parent, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run(goal: str, task_dir: Path, llm, rounds: int = 3,
        max_roles: int | None = None, max_stages: int | None = None) -> dict:
    run_dir = task_dir / f"sa-run-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    spec = task["spec"]
    format_hint = task.get("format_hint", "")
    check = task_dir / task.get("check", "check.py")
    deliverable = run_dir / "deliverable.md"

    # ① Super：目标 → 编制
    t0 = time.time()
    plan = plan_org(goal, lambda m: llm(m, max_tokens=2000), budget_cap=200_000)
    t_hire = round(time.time() - t0, 2)

    # 流程自优化：依据上一轮的成本收缩编制，但必须保留独立验证角色
    adjustment = None
    if (max_roles and len(plan.roles) > max_roles) or (max_stages and len(plan.process) > max_stages):
        from xm.hiring import OrgPlan
        roles = list(plan.roles)
        if max_roles and len(roles) > max_roles:
            keep = roles[: max_roles - 1]
            verifiers = [r for r in roles if r.kind == "verifier"]
            if verifiers and verifiers[0] not in keep:
                keep.append(verifiers[0])
            roles = keep
        process = plan.process[:max_stages] if max_stages else plan.process
        adjustment = {
            "roles_from": len(plan.roles), "roles_to": len(roles),
            "stages_from": len(plan.process), "stages_to": len(process),
            "reason": "上一轮 6 角色 × 7 阶段 = 42 次派活、约 46 次调用，成本过高；本次收缩编制并保留独立验证角色",
        }
        plan = OrgPlan(goal=plan.goal, roles=roles, process=process)

    ledger.append("org_plan", "super", {
        "goal": goal,
        "roles": [r.name for r in plan.roles],
        "kinds": [r.kind for r in plan.roles],
        "process": plan.process,
        "total_budget": plan.total_budget,
    })

    t1 = time.time()
    # ② 派活：角色带目标干活，逐级交接（先把已验事实检索出来塞进提示词）
    kb = KnowledgeBase(default_path())
    facts = kb.retrieve(goal, limit=3)
    fact_block = as_prompt_block(facts)
    ledger.append("kb_retrieve", "sa", {"count": len(facts), "keys": [f.key for f in facts]})
    collected: list[dict] = []

    def worker(role, stage, upstream):
        prompt = role_prompt(spec, goal, role, stage, upstream, fact_block)
        art = {
            "id": f"{stage}:{role['name']}",
            "upstream": (upstream or {}).get("id"),
            "stage": stage,
            "role": role["name"],
            "content": _call(llm, prompt, max_tokens=800),
        }
        collected.append(art)
        return art

    stats = Scheduler(ledger).run(
        {"roles": [asdict(r) for r in plan.roles], "process": plan.process}, worker=worker)
    t_dispatch = round(time.time() - t1, 2)
    ledger.append("dispatch_done", "scheduler", stats)

    # ③ 主编：把组织产出整合成一份可验收的交付
    joined = "\n\n".join(f"[{a['role']} · {a['stage']}]\n{a['content']}" for a in collected)
    editor_prompt = f"""下面是组织各角色为同一个目标产出的交付片段。请整合成一份完整、连贯的文档。

## 目标
{goal}

## 格式要求（必须逐条满足）
{spec}
{("## 格式样例（照这个写，判据按这个判）" + chr(10) + format_hint) if format_hint else ""}

## 各角色交付
{joined}

只返回文档正文（Markdown），不要任何解释。"""
    t2 = time.time()
    doc = _call(llm, editor_prompt, max_tokens=4000)
    t_edit = round(time.time() - t2, 2)
    deliverable.write_text(doc, encoding="utf-8")

    # ④ 独立验收 + 返工
    rc, out = _run_check(check, deliverable)
    attempts = [{"round": 1, "rc": rc, "detail": out[-400:]}]
    ledger.append("verify", "checker", {"round": 1, "rc": rc})
    round_no = 1
    while rc != 0 and round_no < rounds:
        round_no += 1
        fix_prompt = f"""上一版交付没有通过验收，失败原因：
```
{out[-800:]}
```

请修正后重写完整文档，仍然只返回正文（Markdown），并逐条满足格式要求：
{spec}
{("## 格式样例（照这个写）" + chr(10) + format_hint) if format_hint else ""}

上一版内容：
{doc[:6000]}"""
        doc = _call(llm, fix_prompt, max_tokens=4000)
        deliverable.write_text(doc, encoding="utf-8")
        rc, out = _run_check(check, deliverable)
        attempts.append({"round": round_no, "rc": rc, "detail": out[-400:]})
        ledger.append("verify", "checker", {"round": round_no, "rc": rc})

    # 过判据才回写：没过的结论进底座，等于把错的记成已验证
    written = writeback_if_passed(
        kb, rc == 0, doc,
        [f"artifact:{deliverable}", f"check:{check.name}", "criteria:passed"],
        source="sa_task",
    )
    ledger.append("kb_writeback", "sa", {"written": written.key if written else None,
                                        "pass": rc == 0})

    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "process": {
            "org_adjustment": adjustment,
            "timing_s": {"hire": t_hire, "dispatch": t_dispatch, "edit": t_edit},
            "handoffs": stats.get("handoffs"),
            "chain_ok": stats.get("chain_ok"),
            "roles": [r.name for r in plan.roles],
            "stages": len(plan.process),
            "attempts": len(attempts),
        },
        "kb": {"retrieved": [f.key for f in facts],
               "written": written.key if written else None},
        "goal": goal,
        "org": {"roles": [r.name for r in plan.roles], "process": plan.process,
                "total_budget": plan.total_budget},
        "dispatch": stats,
        "attempts": attempts,
        "passed": rc == 0,
        "deliverable": str(deliverable),
        "chars": len(doc),
        "round": round_no,
    }
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return report