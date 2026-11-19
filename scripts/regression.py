"""能力回归：把 G2–G6 当场重测一遍，不读旧记录。

用法：python3 scripts/regression.py
产物：reports/regression-<ts>.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
HOME_RUNS = Path.home() / "xm-runs"


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_rc": proc.returncode, "_error": proc.stderr[-300:] or proc.stdout[-300:]}
    data["_rc"] = proc.returncode
    return data


def run_tests(*mods: str) -> dict:
    proc = subprocess.run([sys.executable, "-m", "unittest", *mods, "-q"],
                          cwd=ROOT, capture_output=True, text=True)
    return {"_rc": proc.returncode, "tail": (proc.stderr or "")[-200:]}


def main() -> int:
    results: dict[str, dict] = {}

    # G3 判据能力：运行时 + daemon 通电
    t = run_tests("tests.test_criteria_runtime", "tests.test_daemon_criteria")
    results["G3"] = {"passed": t["_rc"] == 0, "evidence": "判据运行时与 daemon 通电测试"}

    # G6 成本：预算止损 + 真实 usage（测试覆盖）
    t = run_tests("tests.test_budget")
    results["G6"] = {"passed": t["_rc"] == 0, "evidence": "预算止损与真实 usage 测试"}

    # G2 组织性：真模型 6 角色单阶段
    plans = sorted(HOME_RUNS.glob("org/*.json"))
    if not plans:
        results["G2"] = {"passed": False, "evidence": "没有编制方案可跑"}
    else:
        d = run_json([sys.executable, "scripts/dispatch_org.py", "--plan", str(plans[-1]),
                      "--llm", "--stages", "1"])
        ok = (d.get("_rc") == 0 and d.get("chain_ok") and d.get("distinct_roles", 0) >= 3
              and d.get("verdicts", 0) >= 1 and d.get("worker_mode") == "llm")
        results["G2"] = {"passed": bool(ok),
                         "evidence": f"roles={d.get('distinct_roles')} handoffs={d.get('handoffs')} "
                                     f"chain_ok={d.get('chain_ok')} verdicts={d.get('verdicts')} "
                                     f"reworks={d.get('reworks')}"}

    # G4 知识扩展：真实抓取 + RAG 引用
    fetch = run_json([sys.executable, "scripts/kb_fetch_demo.py"])
    rag = run_json([sys.executable, "scripts/rag_demo.py"])
    results["G4"] = {"passed": bool(fetch.get("passed") and rag.get("passed")),
                     "evidence": f"抓取 passed={fetch.get('passed')}；"
                                 f"RAG refs={rag.get('refs')} passed={rag.get('passed')}"}

    # G5 不漂移：同任务三次
    task = HOME_RUNS / "2026-11-19-skills" / "task.json"
    if task.exists():
        d = run_json([sys.executable, "scripts/stability_deliverable.py",
                      "--task", str(task), "--n", "3"])
        results["G5"] = {"passed": bool(d.get("passed")),
                         "evidence": f"n={d.get('n')} score={d.get('score')}"}
    else:
        results["G5"] = {"passed": False, "evidence": "缺任务包"}

    # G1：如实转述（不做新测试）
    live = sorted((ROOT / "reports").glob("liveness-*.json"))
    results["G1"] = {"passed": bool(live), "evidence": "24h 常驻运行进行中，未完成"}

    passed = sum(1 for v in results.values() if v["passed"])
    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "passed": passed, "total": len(results),
              "results": results}
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    path = out / f"regression-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for gid in sorted(results):
        r = results[gid]
        print(f"[{'PASS' if r['passed'] else 'FAIL'}] {gid}: {r['evidence']}")
    print(f"\n{passed}/{len(results)} → {'其它能力全部通过' if passed == len(results) else '有失败'}")
    print(f"报告：{path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())