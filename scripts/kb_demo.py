"""知识底座跨领域演示：同一套代码，换数据即换领域（G4 的可得证据）。

不接论文库也能证明机制：两个领域各放几条带证据的事实，检索时只换 domain，不改代码。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.kb import KnowledgeBase
from xm.paths import runs_root

ROOT = Path(__file__).resolve().parents[1]

SOURCES = {
    "agent-skill": [
        ("Skill 的输入契约必须显式声明", ["docs/agent-spec#input-contract"]),
        ("Skill 的失败信息要可行动", ["case/postmortem-07"]),
    ],
    "delivery": [
        ("没有机检判据的任务不算完成", ["docs/ACCEPTANCE.md#G2"]),
        ("产物必须落在项目目录之外", ["README.md#边界"]),
    ],
}


def main() -> int:
    kb_path = runs_root() / "kb" / "kb.jsonl"
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    kb = KnowledgeBase(kb_path)

    for domain, facts in SOURCES.items():
        for claim, evidence in facts:
            kb.add(claim, domain, evidence, source=f"demo:{domain}")

    queries = {"agent-skill": "契约", "delivery": "判据"}
    per_domain = {}
    for domain, query in queries.items():
        hits = kb.search(query, domain=domain)
        per_domain[domain] = {
            "query": query,
            "hits": [h.claim for h in hits],
            "count": len(hits),
        }

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kb_path": str(kb_path),
        "domains": kb.domains(),
        "total_facts": kb.count(),
        "per_domain": per_domain,
        "code_changed_between_domains": False,
        "passed": all(v["count"] >= 1 for v in per_domain.values()) and len(kb.domains()) >= 2,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"kb-demo-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())