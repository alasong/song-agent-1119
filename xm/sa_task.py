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
from xm.ledger import Ledger
from xm.scheduler import Scheduler


def _call(llm, prompt: str, max_tokens: int = 3000) -> str:
    return llm([{"role": "user", "content": prompt}], max_tokens)


def _run_check(check: Path, target: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(check), str(target)],
                          cwd=check.parent, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run(goal: str, task_dir: Path, llm, rounds: int = 3) -> dict:
    run_dir = task_dir / f"sa-run-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    spec = task["spec"]
    check = task_dir / task.get("check", "check.py")
    deliverable = run_dir / "deliverable.md"

    # ① HR：目标 → 编制
    plan = plan_org(goal, lambda m: llm(m, max_tokens=2000), budget_cap=200_000)
    ledger.append("org_plan", "hr", {
        "goal": goal,
        "roles": [r.name for r in plan.roles],
        "kinds": [r.kind for r in plan.roles],
        "process": plan.process,
        "total_budget": plan.total_budget,
    })

    # ② 派活：角色带目标干活，逐级交接
    collected: list[dict] = []

    def worker(role, stage, upstream):
        prompt = f"""你是「{role['name']}」，职责：{role['duty']}
你的验收方式：{role['criteria']}

组织正在完成的总体目标：{goal}

当前阶段：{stage}
上游交付：
```
{(upstream or {}).get('content', '')[:1200] or '（无，你是第一个）'}
```

给出你在这一阶段的交付，不超过 300 字，只写交付物本身。"""
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
    ledger.append("dispatch_done", "scheduler", stats)

    # ③ 主编：把组织产出整合成一份可验收的交付
    joined = "\n\n".join(f"[{a['role']} · {a['stage']}]\n{a['content']}" for a in collected)
    editor_prompt = f"""下面是组织各角色为同一个目标产出的交付片段。请整合成一份完整、连贯的文档。

## 目标
{goal}

## 格式要求（必须逐条满足）
{spec}

## 各角色交付
{joined}

只返回文档正文（Markdown），不要任何解释。"""
    doc = _call(llm, editor_prompt, max_tokens=4000)
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

上一版内容：
{doc[:6000]}"""
        doc = _call(llm, fix_prompt, max_tokens=4000)
        deliverable.write_text(doc, encoding="utf-8")
        rc, out = _run_check(check, deliverable)
        attempts.append({"round": round_no, "rc": rc, "detail": out[-400:]})
        ledger.append("verify", "checker", {"round": round_no, "rc": rc})

    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
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