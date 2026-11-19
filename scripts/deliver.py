"""交付入口：先一个人干，判不过再组队。

用法：python3 scripts/deliver.py --task ~/xm-runs/2026-11-19-rsi --goal "如何做 Agent 的 RSI"

产物写 reports/deliver-<ts>.json（决策 + 各次尝试的读数），供人核对「该不该组队」。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm import deliver as deliver_mod
from xm.kb import KnowledgeBase, default_path, writeback_if_passed
from xm.llm import complete_usage
from xm.sa_task import run as sa_run
from xm.single import run_single

ROOT = Path(__file__).resolve().parents[1]


def make_llm(model: str, sink: list[dict]):
    def llm(messages, max_tokens: int = 2000):
        text, usage = complete_usage(messages, model=model, max_tokens=max_tokens,
                                     extra={"thinking": {"type": "disabled"}})
        sink.append(usage or {})
        return text
    return llm


def usage_stats(sink: list[dict]) -> dict:
    hit = sum(u.get("prompt_cache_hit_tokens", 0) or 0 for u in sink)
    miss = sum(u.get("prompt_cache_miss_tokens", 0) or 0 for u in sink)
    comp = sum(u.get("completion_tokens", 0) or 0 for u in sink)
    return {"calls": len(sink), "prompt_tokens": hit + miss, "completion_tokens": comp}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--goal", required=True)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--max-roles", type=int, default=None)
    ap.add_argument("--max-stages", type=int, default=None)
    args = ap.parse_args()

    task_dir = Path(args.task).expanduser().resolve()
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    single_sink: list[dict] = []
    org_sink: list[dict] = []

    def single_fn() -> dict:
        res = run_single(task_dir, make_llm(args.model, single_sink))
        written = writeback_if_passed(
            KnowledgeBase(default_path()), res["passed"], res["text"],
            [f"artifact:{res['artifact']}", "path:single", "criteria:passed"],
            source="deliver:single")
        body = {k: v for k, v in res.items() if k != "text"}
        return {**body, **usage_stats(single_sink),
                "kb_written": written.key if written else None}

    def org_fn() -> dict:
        rep = sa_run(args.goal, task_dir, make_llm(args.model, org_sink),
                     max_roles=args.max_roles, max_stages=args.max_stages)
        return {"passed": rep["passed"], "rounds": len(rep["attempts"]),
                "chars": rep["chars"], "artifact": rep["deliverable"],
                **usage_stats(org_sink)}

    report = deliver_mod.deliver(args.goal, task, single_fn, org_fn)
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    path = out / f"deliver-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "mode": report["mode"], "passed": report["passed"], "org_called": report["org_called"],
        "reasons": report["decision"]["reasons"],
        "attempts": [{k: a.get(k) for k in ("mode", "via", "passed", "calls", "chars")}
                     for a in report["attempts"]],
        "saved_to": str(path),
    }, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())