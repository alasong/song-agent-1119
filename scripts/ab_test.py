"""A/B 对照：同一任务、同一判据，两种编排谁更优（按可核对的读数，不按我说）。

臂 A：单 agent（daemon 一次跑完）
臂 B：sa 组织（组队 → 派活 → 整合 → 验收）

读数：是否通过、轮次、字数、LLM 调用数、prompt/completion tokens、缓存命中。
判定：只有「在一个维度严格更好且其他维度不更差」才叫占优（Pareto），否则只报平手/互有胜负。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger
from xm.llm import complete_usage
from xm.paths import runs_root
from xm.sa_task import run as sa_run

ROOT = Path(__file__).resolve().parents[1]


def make_llm(model: str, sink: list[dict]):
    def llm(messages, max_tokens=2000):
        text, usage = complete_usage(messages, model=model, max_tokens=max_tokens,
                                     extra={"thinking": {"type": "disabled"}})
        sink.append(usage or {})
        return text
    return llm


def usage_stats(sink: list[dict]) -> dict:
    hit = sum(u.get("prompt_cache_hit_tokens", 0) or 0 for u in sink)
    miss = sum(u.get("prompt_cache_miss_tokens", 0) or 0 for u in sink)
    comp = sum(u.get("completion_tokens", 0) or 0 for u in sink)
    return {"calls": len(sink), "prompt_tokens": hit + miss,
            "completion_tokens": comp, "cache_hit": hit,
            "hit_ratio": round(hit / (hit + miss), 4) if hit + miss else 0.0}


def arm_single(task_dir: Path, model: str) -> dict:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    run_dir = runs_root() / "ab" / f"single-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / task["target_name"]
    sink: list[dict] = []
    cfg = DaemonConfig(
        spec=task["spec"], target_file=str(target), tests=[], artifacts_root=str(runs_root()),
        verify_cmd=[sys.executable, str(task_dir / task.get("check", "check.py")), str(target)],
        max_rounds=3, patience=2, fence_lang=task.get("fence_lang", "markdown"),
        budget_tokens=200_000,
    )
    summary = Daemon(Ledger(run_dir / "ledger.jsonl"), make_llm(model, sink), cfg).run()
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    return {"passed": bool(summary["green_at_round"]), "rounds": summary["rounds_used"],
            "chars": len(text), **usage_stats(sink), "artifact": str(target)}


def arm_org(task_dir: Path, model: str, max_roles: int, max_stages: int) -> dict:
    sink: list[dict] = []
    goal = "如何做 Agent 的 RSI（递归自我改进）"
    report = sa_run(goal, task_dir, make_llm(model, sink), rounds=3,
                    max_roles=max_roles, max_stages=max_stages)
    return {"passed": report["passed"], "rounds": len(report["attempts"]),
            "chars": report["chars"], **usage_stats(sink), "artifact": report["deliverable"]}


def compare(a: dict, b: dict) -> dict:
    dims = ["passed", "rounds", "chars", "calls", "prompt_tokens", "completion_tokens"]
    better = {"A": [], "B": [], "tie": []}
    for d in dims:
        va, vb = a.get(d), b.get(d)
        if va == vb:
            better["tie"].append(d)
        elif d in ("calls", "rounds", "prompt_tokens", "completion_tokens"):
            better["A" if va < vb else "B"].append(d)      # 越少越好
        else:
            better["A" if va > vb else "B"].append(d)      # 越多越好
    if better["A"] and not better["B"]:
        verdict = "A 占优（Pareto：A 更好且 B 不更好）"
    elif better["B"] and not better["A"]:
        verdict = "B 占优（Pareto：B 更好且 A 不更好）"
    else:
        verdict = "互有胜负，无 Pareto 占优"
    return {"better": better, "verdict": verdict}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--roles", type=int, default=3)
    ap.add_argument("--stages", type=int, default=1)
    args = ap.parse_args()

    task_dir = Path(args.task).expanduser().resolve()
    a = arm_single(task_dir, args.model)
    b = arm_org(task_dir, args.model, args.roles, args.stages)
    result = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": str(task_dir),
              "A_single_agent": a, "B_sa_org": b, **compare(a, b)}
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    path = out / f"ab-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"A": {k: a[k] for k in ("passed", "rounds", "chars", "calls", "prompt_tokens")},
                      "B": {k: b[k] for k in ("passed", "rounds", "chars", "calls", "prompt_tokens")},
                      "verdict": result["verdict"], "better": result["better"],
                      "saved_to": str(path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())