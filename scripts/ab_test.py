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

from xm import quality
from xm.llm import complete_usage
from xm.sa_task import run as sa_run

ROOT = Path(__file__).resolve().parents[1]
DIMS = ["passed", "rounds", "chars", "calls", "prompt_tokens", "completion_tokens"]


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
    sink: list[dict] = []
    from xm.single import run_single
    res = run_single(task_dir, make_llm(model, sink))
    return {"passed": res["passed"], "rounds": res["rounds"], "chars": res["chars"],
            **usage_stats(sink), "artifact": res["artifact"]}


def arm_org(task_dir: Path, model: str, max_roles: int, max_stages: int) -> dict:
    sink: list[dict] = []
    goal = "如何做 Agent 的 RSI（递归自我改进）"
    report = sa_run(goal, task_dir, make_llm(model, sink), rounds=3,
                    max_roles=max_roles, max_stages=max_stages)
    return {"passed": report["passed"], "rounds": len(report["attempts"]),
            "chars": report["chars"], **usage_stats(sink), "artifact": report["deliverable"]}


def compare(a: dict, b: dict) -> dict:
    dims = list(DIMS)
    if isinstance(a.get("quality_total"), int) and isinstance(b.get("quality_total"), int):
        dims.append("quality_total")   # 质量分越高越好，只有在盲评跑过之后才进比较
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


def judge_pair(a_text: str, b_text: str, model: str, seed: int = 0) -> dict:
    """盲评两臂：送进去的只有正文，顺序按种子打乱，评完再映射回 A/B。"""
    sink: list[dict] = []
    llm = make_llm(model, sink)
    result = quality.judge([a_text, b_text], lambda m: llm(m, max_tokens=1200), seed=seed)
    by_index = {r["index"]: r for r in result["scores"]}
    judge_tokens = sum((u.get("prompt_cache_hit_tokens", 0) or 0)
                       + (u.get("prompt_cache_miss_tokens", 0) or 0)
                       + (u.get("completion_tokens", 0) or 0) for u in sink)
    return {
        "blind": result["blind"], "seed": result["seed"], "rubric": result["rubric"],
        "scores": {"A": by_index.get(0), "B": by_index.get(1)},
        "winner": {0: "A", 1: "B"}.get(result["winner"]),
        "tie": result["tie"],
        "judge_calls": len(sink), "judge_tokens": judge_tokens,
    }


def attach_quality(result: dict, model: str, seed: int = 0) -> dict:
    """对已有两臂产物做盲评，并把质量分并进 Pareto 比较。"""
    texts = [Path(result["A_single_agent"]["artifact"]).read_text(encoding="utf-8"),
             Path(result["B_sa_org"]["artifact"]).read_text(encoding="utf-8")]
    q = judge_pair(texts[0], texts[1], model, seed)
    for arm_key, label in (("A_single_agent", "A"), ("B_sa_org", "B")):
        score = q["scores"].get(label) or {}
        result[arm_key]["quality_total"] = score.get("total")
        result[arm_key]["quality_dims"] = score.get("dims")
    result["quality"] = q
    cmp = compare(result["A_single_agent"], result["B_sa_org"])
    result["better"], result["verdict"] = cmp["better"], cmp["verdict"]
    return result


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="", help="任务目录（--judge-existing 时可省）")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--roles", type=int, default=3)
    ap.add_argument("--stages", type=int, default=1)
    ap.add_argument("--judge", action="store_true", help="跑完两臂再做一次盲评打分")
    ap.add_argument("--judge-existing", default="",
                    help="只对已有 A/B 报告的产物做盲评（不重跑两臂）")
    ap.add_argument("--seed", type=int, default=0, help="盲评顺序种子（可复现）")
    args = ap.parse_args()

    if args.judge_existing:
        src = Path(args.judge_existing).expanduser().resolve()
        result = json.loads(src.read_text(encoding="utf-8"))
        result = attach_quality(result, args.model, args.seed)
        result["judged_from"] = str(src)
        result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        out = ROOT / "reports"
        out.mkdir(exist_ok=True)
        path = out / f"ab-quality-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"verdict": result["verdict"], "better": result["better"],
                          "quality": {"A": result["A_single_agent"].get("quality_total"),
                                      "B": result["B_sa_org"].get("quality_total"),
                                      "winner": result["quality"]["winner"],
                                      "tie": result["quality"]["tie"],
                                      "judge_calls": result["quality"]["judge_calls"]},
                          "saved_to": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if not args.task:
        ap.error("--task 必填（除非用 --judge-existing）")
    task_dir = Path(args.task).expanduser().resolve()
    a = arm_single(task_dir, args.model)
    b = arm_org(task_dir, args.model, args.roles, args.stages)
    result = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": str(task_dir),
              "A_single_agent": a, "B_sa_org": b, **compare(a, b)}
    if args.judge:
        result = attach_quality(result, args.model, args.seed)
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    path = out / f"ab-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"A": {k: a[k] for k in ("passed", "rounds", "chars", "calls", "prompt_tokens")},
                      "B": {k: b[k] for k in ("passed", "rounds", "chars", "calls", "prompt_tokens")},
                      "quality": result.get("quality", {}).get("scores") if args.judge else None,
                      "verdict": result["verdict"], "better": result["better"],
                      "saved_to": str(path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())