"""交付稳定性探针：同一个任务跑三次，比结构指纹。

边界（不藏）：自然语言的「结论是否等价」无法自动判定，
这里只机检骨架（章节集合）与要素数量，差异超过 ±1 即判漂移。

用法：python3 scripts/stability_deliverable.py --task ~/xm-runs/2026-11-19-skills/task.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm import delivery
from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger
from xm.llm import complete
from xm.paths import runs_root

ROOT = Path(__file__).resolve().parents[1]
THRESHOLD = 2 / 3


def fingerprint(text: str) -> dict:
    """关键结论 = 命名条目：编号特征名 + 表格首列组件名。"""
    features = set(re.findall(r"^\d+\.\s+\*\*(.+?)\*\*：", text, re.M))
    rows = {r for r in re.findall(r"^\|\s*([^|]+?)\s*\|", text, re.M)
            if r not in {"组件"} and not r.startswith("-") and not r.startswith(":")}
    headings = re.findall(r"^#{2,3} .+$", text, re.M)
    return {"features": sorted(features), "rows": sorted(rows),
            "headings": headings, "chars": len(text)}


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def close_enough(a: dict, b: dict) -> bool:
    """结构同 + 关键条目重合 ≥ 0.7 才算同结论。"""
    structure_same = a["headings"] == b["headings"]
    overlap = (jaccard(a["features"], b["features"]) + jaccard(a["rows"], b["rows"])) / 2
    return structure_same and overlap >= 0.7


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    src_dir = Path(args.task).expanduser().resolve().parent
    task = json.loads((src_dir / "task.json").read_text(encoding="utf-8"))
    base = runs_root() / "stability" / time.strftime("%Y%m%d-%H%M%S")

    runs = []
    for i in range(args.n):
        run_dir = base / f"run{i + 1}"
        run_dir.mkdir(parents=True, exist_ok=True)
        for aux in src_dir.iterdir():
            if aux.is_file() and aux.suffix in {".py", ".json"} and aux.name != "task.json":
                shutil.copy2(aux, run_dir / aux.name)
        target = run_dir / task["target_name"]
        cfg = DaemonConfig(
            spec=task["spec"],
            target_file=str(target),
            tests=[],
            artifacts_root=str(runs_root()),
            verify_cmd=[sys.executable, str(run_dir / "check.py"), str(target)],
            max_rounds=args.rounds,
            patience=2,
            fence_lang=task.get("fence_lang", "markdown"),
        )
        llm = lambda messages: complete(messages, model=args.model,
                                        max_tokens=int(task.get("max_tokens", 8000)),
                                        extra={"thinking": {"type": "disabled"}})
        summary = Daemon(Ledger(run_dir / "ledger.jsonl"), llm, cfg).run()
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        # 自证由系统拼（DNA #9）：稳定性测的必须是真正交付出去的那份文档
        delivery.attach(target, delivery.RunFacts(
            criteria_ok=bool(summary["green_at_round"]), mode="single",
            calls=summary.get("calls", 0), chars=len(text),
            decision="单 agent 直接跑", rejected="组队",
            artifact=str(target)))
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        runs.append({"round": i + 1, "green_at_round": summary["green_at_round"],
                     "fingerprint": fingerprint(text)})

    pairs = [{"pair": [i + 1, j + 1], "close": close_enough(runs[i]["fingerprint"], runs[j]["fingerprint"])}
             for i, j in combinations(range(len(runs)), 2)]
    score = round(sum(1 for p in pairs if p["close"]) / len(pairs), 4) if pairs else 0.0

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "deliverable",
        "task": str(src_dir / "task.json"),
        "model": args.model,
        "n": args.n,
        "pairs": pairs,
        "score": score,
        "threshold": THRESHOLD,
        "passed": score >= THRESHOLD,
        "runs": runs,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"deliverable-stability-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"n": record["n"], "pairs": pairs, "score": score,
                      "passed": record["passed"], "saved_to": str(path)}, ensure_ascii=False, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())