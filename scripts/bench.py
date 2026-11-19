"""sa 的能力验收 bench：六条判据的可执行检查。

规则：六条全绿才算「够了」；任何一条红，退出码 1。
每条红都要给出「最小下一步」，否则红得没有价值。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path.home() / "xm-runs"


def _has(*rel_paths: str) -> bool:
    return all((ROOT / p).exists() for p in rel_paths)


# ---------------------------------------------------------------- 读数口径
# 验收锚在「能力最好做到过什么」，不锚「最后一次恰好是多少」。
# 两种会把能力读错的运行必须被排除在验收之外：
#   - experiment：收缩编制、压流程、对照试验；
#   - 没有 goal 的记录：证不了「换一个目标也能干」。
EXPERIMENT = "experiment"
G2_REQUIRED_GOALS = 2


def drop_experiments(records: list[dict]) -> list[dict]:
    """丢掉 purpose=experiment 的运行。老报告没有该字段，按验收运行算。"""
    return [r for r in records if r.get("purpose") != EXPERIMENT]


def acceptance_records(pattern: str) -> list[dict]:
    """读 reports/<pattern> 里的验收运行，按文件名升序；坏文件跳过。"""
    out: list[dict] = []
    for path in sorted((ROOT / "reports").glob(pattern)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data["_file"] = path.name
        out.append(data)
    return drop_experiments(out)


def g2_goal_ok(rec: dict) -> bool:
    """一次派活是否证明了「组织能干活」的全部结构要件。

    返工次数不做必备项：ACCEPTANCE 的 G2 没要求返工，且「这次拒了没有」取决于
    模型当次是否恰好拒稿，拿随机性当判据会让门时红时绿。返工能力另有
    tests/test_scheduler.py 与历史报告（verdict_reject/reworks）为证，这里只报读数。
    """
    return (rec.get("distinct_roles", 0) >= 3
            and bool(rec.get("chain_ok"))
            and rec.get("handoffs", 0) >= 3
            and rec.get("worker_mode") == "llm"
            and rec.get("stages", 0) >= 2
            and bool(rec.get("has_verifier"))
            and rec.get("verdicts", 0) >= 1)


def g2_goals(records: list[dict]) -> dict[str, dict]:
    """按目标归并，同一目标取最强的一次；没有 goal 的记录不算。"""
    best: dict[str, dict] = {}
    for rec in records:
        goal = (rec.get("goal") or "").strip()
        if not goal or not g2_goal_ok(rec):
            continue
        prev = best.get(goal)
        if prev is None or (rec.get("handoffs", 0), rec.get("verdicts", 0)) > \
                (prev.get("handoffs", 0), prev.get("verdicts", 0)):
            best[goal] = rec
    return best


def g2_passed(goals: dict[str, dict]) -> bool:
    """文档要求「连续 2 个新目标都达成」——按目标数算，不按报告数算。"""
    return len(goals) >= G2_REQUIRED_GOALS


def g5_skeleton_ok(report: dict) -> bool:
    """章节骨架一致：几次交付的标题集合必须完全相同，缺指纹不算通过。"""
    heads = [frozenset((r.get("fingerprint") or {}).get("headings") or [])
             for r in report.get("runs") or []]
    return len(heads) >= 2 and all(heads) and len(set(heads)) == 1


def liveness_ok(hours: float, progress_tasks: int, distinct_tasks: int) -> bool:
    """G1 的纯判定：≥24h 且 ≥10 个有进展任务 且 ≥3 类任务。"""
    return hours >= 24 and progress_tasks >= 10 and distinct_tasks >= 3


def g1_autonomy() -> dict:
    records = sorted((ROOT / "reports").glob("liveness-*.json"))
    long_run = []
    for r in records:
        data = json.loads(r.read_text(encoding="utf-8"))
        if liveness_ok(data.get("hours", 0), data.get("progress_tasks", 0),
                       data.get("distinct_tasks", 0)):
            long_run.append(r)
    if long_run:
        return {"passed": True,
                "evidence": f"完成 24h 常驻运行 {len(long_run)} 次", "next": ""}

    # 还没跑满：把「已经跑了多久」报出来，别只报一个 0
    progress = ""
    cp = Path.home() / "xm-runs" / "resident" / "checkpoint.json"
    if cp.exists():
        data = json.loads(cp.read_text(encoding="utf-8"))
        hours = data.get("running_hours")
        ticks = data.get("ticks", 0)
        if hours is not None:
            remain = max(0.0, 24 - float(hours))
            eta = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + remain * 3600))
            progress = (f"；进行中：已跑 {hours}h / 24h（{ticks} 轮），"
                        f"还需 {remain:.2f}h，预计 {eta} 完成（睡眠会顺延）")
        else:
            progress = f"；进行中：已 {ticks} 轮（旧检查点无时长字段）"
    return {
        "passed": False,
        "evidence": "24h 常驻运行记录 0 条（需要 ≥1）" + progress,
        "next": "等常驻循环跑满 24h；跑完会自动写 reports/liveness-*.json",
    }


def g2_organization() -> dict:
    scheduler = _has("xm/scheduler.py")
    records = acceptance_records("scheduler-*.json")
    goals = g2_goals(records)
    ok = scheduler and g2_passed(goals)

    missing_goal = sum(1 for r in records if not (r.get("goal") or "").strip())
    detail = "，".join(f"「{g}」←{r['_file']}" for g, r in list(goals.items())[:4]) or "无"
    strongest = max(goals.values(), key=lambda r: r.get("handoffs", 0)) if goals else {}
    return {
        "passed": ok,
        "evidence": f"达标目标 {len(goals)}/{G2_REQUIRED_GOALS}：{detail}；"
                    f"验收运行 {len(records)} 份（已排除实验运行，其中 {missing_goal} 份没记 goal）"
                    + (f"；最强一次 角色={strongest.get('distinct_roles')} "
                       f"阶段={strongest.get('stages')} 交接={strongest.get('handoffs')} "
                       f"验拒={strongest.get('verdict_reject', 0)} 返工={strongest.get('reworks')}"
                       if strongest else ""),
        "next": "对另一个不同目标再跑一次 dispatch_org --llm，并把 goal/purpose 记进报告",
    }


def g3_criteria() -> dict:
    if not _has("xm/criteria_runtime.py"):
        return {"passed": False, "evidence": "判据运行时不存在",
                "next": "写 criteria_runtime：文字判据→可执行检查，登记版本，生成方不可改"}
    units = subprocess.run([sys.executable, "-m", "unittest",
                            "tests.test_criteria_runtime", "tests.test_daemon_criteria", "-q"],
                           cwd=ROOT, capture_output=True, text=True)
    ok = units.returncode == 0
    return {
        "passed": ok,
        "evidence": "判据运行时 + daemon 通电（未注册判据即判红）；"
                    + ("测试通过" if ok else "测试未通过"),
        "next": "判据必须能被生成方之外的人注册，生成方改不动，且执行链路真的用它",
    }


def g4_knowledge() -> dict:
    if not _has("xm/kb.py"):
        return {"passed": False, "evidence": "知识底座不存在",
                "next": "写 xm/kb.py：检索 + 只收已验证事实；接一个领域源做端到端"}
    records = sorted((ROOT / "reports").glob("kb-fetch-*.json"))
    if not records:
        return {"passed": False, "evidence": "只有手写演示，没有真实获取记录",
                "next": "跑 scripts/kb_fetch_demo.py：从公开源取两个领域并入底座"}
    latest = json.loads(records[-1].read_text(encoding="utf-8"))
    per = latest.get("per_domain", {})
    fetched_ok = bool(latest.get("passed"))

    rags = sorted((ROOT / "reports").glob("rag-*.json"))
    rag_ok = False
    rag_refs = 0
    if rags:
        rag = json.loads(rags[-1].read_text(encoding="utf-8"))
        rag_ok = bool(rag.get("passed"))
        rag_refs = rag.get("refs", 0)

    return {
        "passed": fetched_ok and rag_ok,
        "evidence": "取：" + "，".join(f"{d} {v.get('stored', 0)} 条" for d, v in per.items())
                    + f"；用：RAG 引用 {rag_refs} 条，可溯源={rag_ok}",
        "next": "两个领域各取到 ≥2 条带 URL 的事实，且交付里能引用到真实条目",
    }


def g5_stability() -> dict:
    records = acceptance_records("deliverable-stability-*.json")
    if not records:
        return {"passed": False, "evidence": "没有交付稳定性记录（只测过组队稳定，不算）",
                "next": "同一交付任务跑 N=3，比对命名条目重合度与章节骨架"}
    latest = records[-1]
    score = latest.get("score", 0)
    n = latest.get("n", 0)
    skeleton = g5_skeleton_ok(latest)
    ok = n >= 3 and score >= latest.get("threshold", 2 / 3) and skeleton
    return {
        "passed": ok,
        "evidence": f"同一交付任务 N={n}，结论条目重合率={score}"
                    f"（阈值 {round(latest.get('threshold', 0), 3)}），"
                    f"章节骨架一致={skeleton}",
        "next": "三次交付的命名条目要重合 ≥2/3，且章节标题集合完全一致",
    }


def g6_cost() -> dict:
    # 判据：预算超了真的会停（测试证明）+ 记账用的是模型返回的真实 usage（运行记录证明）
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_budget", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    unit_ok = proc.returncode == 0
    records = acceptance_records("usage-*.json")
    latest = records[-1] if records else {}
    exact_ok = bool(latest.get("passed"))
    return {
        "passed": unit_ok and exact_ok,
        "evidence": "预算止损测试 " + ("通过" if unit_ok else "未通过")
                    + f"；真实用量记账轮数={latest.get('exact_usage_rounds', 0)}"
                    + f"，实耗={latest.get('spent_tokens', '-')} tokens",
        "next": "记账必须用模型返回的真实 usage，超支即止",
    }


CHECKS = [
    ("G1 自主性", g1_autonomy),
    ("G2 组织性", g2_organization),
    ("G3 判据能力", g3_criteria),
    ("G4 知识扩展", g4_knowledge),
    ("G5 不漂移", g5_stability),
    ("G6 成本可控", g6_cost),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="只输出机器可读结果")
    args = ap.parse_args()

    rows = []
    for name, fn in CHECKS:
        try:
            result = fn()
        except Exception as exc:  # 检查本身坏了也要记账，不能静默
            result = {"passed": False, "evidence": f"检查异常：{type(exc).__name__}: {exc}",
                      "next": "修检查脚本本身"}
        rows.append({"id": name, **result})

    passed = sum(1 for r in rows if r["passed"])
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "passed": passed,
        "total": len(rows),
        "verdict": "够了" if passed == len(rows) else "不够",
        "checks": rows,
    }
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    path = out / f"bench-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if passed == len(rows) else 1

    for r in rows:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['id']}: {r['evidence']}")
        if not r["passed"]:
            print(f"       最小下一步：{r['next']}")
    print(f"\n{passed}/{len(rows)} → {report['verdict']}  （报告：{path}）")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())