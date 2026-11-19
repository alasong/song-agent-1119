"""RAG 闭环演示：检索知识底座 → 注入提示 → 产出标注引用的交付 → 判据校验引用真实。

这一步补的是 G4 的另一半：**取了要会用**。模型看不到底座就写不出真引用，
所以事实必须进提示（上一轮受控词表踩过同一个坑）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.criteria_runtime import OWNER, CriteriaRuntime
from xm.daemon import Daemon, DaemonConfig
from xm.grounding import check_refs
from xm.kb import KnowledgeBase
from xm.ledger import Ledger
from xm.llm import complete
from xm.paths import runs_root

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    kb_path = runs_root() / "kb" / "kb.jsonl"
    os.environ["XM_KB_PATH"] = str(kb_path)
    kb = KnowledgeBase(kb_path)

    facts = [f for f in kb.search("", domain="rl")][:5]
    if len(facts) < 3:
        print(json.dumps({"error": f"rl 领域事实不足：{len(facts)} 条"}, ensure_ascii=False))
        return 2

    lines = "\n".join(f"- [{f.key}] {f.claim}" for f in facts)
    spec = f"""写一份简短综述（≥400 字），总结强化学习方向的近期工作。

## 可用事实（只能引用下面这些，引用时写 [ref:键值]）
{lines}

## 要求
- 至少 3 条结论，每条结论后面必须标注它依据的事实键，格式 `[ref:<键值>]`
- 只能引用上面列出的事实，不许编造键值
- 结尾用一段话说明这些事实的共同局限
"""

    run_dir = runs_root() / "rag" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    criteria_path = run_dir / "criteria.jsonl"

    owner = CriteriaRuntime(criteria_path, writer=OWNER)
    owner.register("引用可溯源", "callable", {"target": "xm.grounding:has_valid_refs"})

    target = run_dir / "summary.md"
    cfg = DaemonConfig(
        spec=spec,
        target_file=str(target),
        tests=[],
        artifacts_root=str(runs_root()),
        criteria=["引用可溯源"],
        criteria_path=str(criteria_path),
        max_rounds=3,
        patience=2,
        fence_lang="markdown",
        budget_tokens=20_000,
    )
    llm = lambda messages: complete(messages, model="deepseek-flash", max_tokens=4000,
                                    extra={"thinking": {"type": "disabled"}})
    summary = Daemon(Ledger(run_dir / "ledger.jsonl"), llm, cfg).run()

    text = target.read_text(encoding="utf-8") if target.exists() else ""
    ref_result = check_refs(text)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "rag",
        "facts_offered": len(facts),
        "green_at_round": summary["green_at_round"],
        "final_rc": summary["final_rc"],
        "refs": ref_result["refs"],
        "missing_refs": ref_result["missing"],
        "chars": len(text),
        "passed": bool(summary["green_at_round"]) and ref_result["ok"],
        "target": str(target),
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"rag-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**record, "saved_to": str(path)}, ensure_ascii=False, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())