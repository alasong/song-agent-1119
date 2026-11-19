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
    latest = json.loads(records[-1].read_text(encoding="utf-8")) if records else {}
    roles = latest.get("distinct_roles", 0)
    chain_ok = bool(latest.get("chain_ok"))
    handoffs = latest.get("handoffs", 0)
    mode = latest.get("worker_mode", "stub")
    stages = latest.get("stages", 0)
    has_verifier = bool(latest.get("has_verifier"))
    verdicts = latest.get("verdicts", 0)
    reworks = latest.get("reworks", 0)
    ok = (scheduler and roles >= 3 and chain_ok and handoffs >= 3
          and mode == "llm" and stages >= 2 and has_verifier and verdicts >= 1
          and reworks >= 1)
    return {
        "passed": ok,
        "evidence": f"角色={roles}；阶段={stages}；交接={handoffs}；链完整={chain_ok}；"
                    f"执行方={mode}；独立验证角色={has_verifier}；"
                    f"验证员裁决={verdicts} 次（拒 {latest.get('verdict_reject', 0)}），"
                    f"被拒后返工={reworks} 次",
        "next": "角色由真模型执行、跨 ≥2 阶段交接、验证员裁决并触发返工",
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
    records = sorted((ROOT / "reports").glob("deliverable-stability-*.json"))
    if not records:
        return {"passed": False, "evidence": "没有交付稳定性记录（只测过组队稳定，不算）",
                "next": "同一交付任务跑 N=3，比对命名条目重合度"}
    latest = json.loads(records[-1].read_text(encoding="utf-8"))
    score = latest.get("score", 0)
    ok = latest.get("n", 0) >= 3 and score >= latest.get("threshold", 2 / 3)
    return {
        "passed": ok,
        "evidence": f"同一交付任务 N={latest.get('n')}，结论条目重合率={score}"
                    f"（阈值 {round(latest.get('threshold', 0), 3)}）",
        "next": "三次交付的命名条目要重合 ≥2/3；当前每次都换一套说法",
    }


def g6_cost() -> dict:
    # 判据：预算超了真的会停（测试证明）+ 记账用的是模型返回的真实 usage（运行记录证明）
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.test_budget", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    )
    unit_ok = proc.returncode == 0
    records = sorted((ROOT / "reports").glob("usage-*.json"))
    latest = json.loads(records[-1].read_text(encoding="utf-8")) if records else {}
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