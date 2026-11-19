"""sa 的能力验收 bench：六条判据的可执行检查。

规则：六条全绿才算「够了」；任何一条红，退出码 1。
每条红都要给出「最小下一步」，否则红得没有价值。
"""
from __future__ import annotations

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


def g1_autonomy() -> dict:
    records = sorted((ROOT / "reports").glob("liveness-*.json"))
    long_run = [r for r in records
                if json.loads(r.read_text(encoding="utf-8")).get("hours", 0) >= 24]
    ok = bool(long_run)
    return {
        "passed": ok,
        "evidence": f"24h 常驻运行记录 {len(long_run)} 条（需要 ≥1）",
        "next": "写常驻循环跑满 24h，账本统计自主发起且有进展的任务数",
    }


def g2_organization() -> dict:
    scheduler = _has("xm/scheduler.py")
    records = sorted((ROOT / "reports").glob("scheduler-*.json"))
    best = 0
    if records:
        latest = json.loads(records[-1].read_text(encoding="utf-8"))
        best = latest.get("distinct_roles", 0)
    ok = scheduler and best >= 3
    return {
        "passed": ok,
        "evidence": f"调度器={'有' if scheduler else '无'}；最近一次派活覆盖角色数={best}",
        "next": "按 OrgPlan 派活给 ≥3 个不同角色，并把记录落到 reports/scheduler-*.json",
    }


def g3_criteria() -> dict:
    if not _has("xm/criteria_runtime.py"):
        return {"passed": False, "evidence": "判据运行时不存在",
                "next": "写 criteria_runtime：文字判据→可执行检查，登记版本，生成方不可改"}
    proc = subprocess.run([sys.executable, "-m", "unittest", "tests.test_criteria_runtime", "-q"],
                          cwd=ROOT, capture_output=True, text=True)
    ok = proc.returncode == 0
    return {
        "passed": ok,
        "evidence": "判据运行时存在；越权/执行/版本测试 " + ("通过" if ok else "未通过"),
        "next": "判据必须能被生成方之外的人注册，且生成方改不动",
    }


def g4_knowledge() -> dict:
    if not _has("xm/kb.py"):
        return {"passed": False, "evidence": "知识底座不存在",
                "next": "写 xm/kb.py：检索 + 只收已验证事实；接一个领域源做端到端"}
    records = sorted((ROOT / "reports").glob("kb-demo-*.json"))
    if not records:
        return {"passed": False, "evidence": "有底座但没有跨领域演示记录",
                "next": "跑 scripts/kb_demo.py：两个领域各检索到事实，且不改代码"}
    latest = json.loads(records[-1].read_text(encoding="utf-8"))
    ok = bool(latest.get("passed")) and len(latest.get("domains", [])) >= 2
    return {
        "passed": ok,
        "evidence": f"跨领域演示：{len(latest.get('domains', []))} 个领域，"
                    f"每领域命中={[v['count'] for v in latest.get('per_domain', {}).values()]}",
        "next": "两个领域各检索到事实，且换领域不改代码",
    }


def g5_stability() -> dict:
    records = sorted((ROOT / "reports").glob("stability-*.json"))
    if not records:
        return {"passed": False, "evidence": "没有稳定性探针记录",
                "next": "跑 scripts/stability_probe.py：同目标 N=3，比关键结论"}
    latest = json.loads(records[-1].read_text(encoding="utf-8"))
    ok = latest.get("n", 0) >= 3 and latest.get("score", 0) >= latest.get("threshold", 2 / 3)
    return {
        "passed": ok,
        "evidence": f"N={latest.get('n')}，一致率={latest.get('score')}，阈值={round(latest.get('threshold', 0), 3)}",
        "next": "同一任务/目标重复 N=3，关键结论一致率须 ≥2/3",
    }


def g6_cost() -> dict:
    # 判据不是「文件里有字段」，而是「预算超了真的会停」——用测试证明
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_budget", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    ok = proc.returncode == 0
    return {
        "passed": ok,
        "evidence": "预算止损测试 " + ("通过" if ok else "未通过"),
        "next": "daemon 记账必须有 budget_tokens/spent_tokens/stopped_by_budget，且超支即停",
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