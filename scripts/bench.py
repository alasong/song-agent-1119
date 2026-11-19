"""sa 的能力验收 bench：六条判据的可执行检查。

规则：六条全绿才算「够了」；任何一条红，退出码 1。
每条红都要给出「最小下一步」，否则红得没有价值。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path.home() / "xm-runs"


def _has(*rel_paths: str) -> bool:
    return all((ROOT / p).exists() for p in rel_paths)


def g1_autonomy() -> dict:
    resident = _has("xm/scheduler.py")
    return {
        "passed": resident,
        "evidence": "常驻调度模块 xm/scheduler.py " + ("存在" if resident else "不存在"),
        "next": "写 xm/scheduler.py：心跳循环 + 无进展检测 + 自主派活，跑满 24h 读账本",
    }


def g2_organization() -> dict:
    hiring = _has("xm/hiring.py")
    dispatch = _has("xm/scheduler.py")
    ok = hiring and dispatch
    return {
        "passed": ok,
        "evidence": f"组队={'有' if hiring else '无'}，派活={'有' if dispatch else '无'}",
        "next": "有了 OrgPlan 之后，让 scheduler 按 plan 派给 ≥3 个角色并做交接",
    }


def g3_criteria() -> dict:
    runtime = _has("xm/criteria_runtime.py")
    return {
        "passed": runtime,
        "evidence": "判据运行时 xm/criteria_runtime.py " + ("存在" if runtime else "不存在"),
        "next": "写 criteria_runtime：文字判据→可执行检查，登记版本，生成方不可改",
    }


def g4_knowledge() -> dict:
    kb = _has("xm/kb.py")
    return {
        "passed": kb,
        "evidence": "知识底座 xm/kb.py " + ("存在" if kb else "不存在"),
        "next": "写 xm/kb.py：检索 + 只收已验证事实；接一个领域源做端到端",
    }


def g5_stability() -> dict:
    results = sorted(RUNS.glob("**/result.json")) if RUNS.exists() else []
    same_task = [r for r in results if "repeat" in str(r)]
    ok = len(same_task) >= 3
    return {
        "passed": ok,
        "evidence": f"重复运行记录 {len(same_task)} 条（需要 ≥3）",
        "next": "同一任务跑三次，把三次 result.json 落盘到同一目录下比对",
    }


def g6_cost() -> dict:
    # 判据：每个 run 的 result.json 都要有预算与实耗字段
    results = sorted(RUNS.glob("**/result.json")) if RUNS.exists() else []
    missing = [r for r in results if "budget" not in json.loads(r.read_text(encoding="utf-8"))]
    ok = bool(results) and not missing
    return {
        "passed": ok,
        "evidence": f"{len(results)} 个运行记录，缺预算字段 {len(missing)} 个",
        "next": "daemon 记账时写入 budget/spent/stopped_by_budget 三个字段",
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

    for r in rows:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['id']}: {r['evidence']}")
        if not r["passed"]:
            print(f"       最小下一步：{r['next']}")
    print(f"\n{passed}/{len(rows)} → {report['verdict']}  （报告：{path}）")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())