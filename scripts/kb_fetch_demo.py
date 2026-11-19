"""真实知识获取演示：从公开论文源取两个领域，入知识底座（带 URL 作为证据）。

G4 的判据要的是「换领域只换知识源、不改代码」——这里每个领域只换查询词。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.fetcher import fetch_arxiv
from xm.kb import KnowledgeBase
from xm.paths import runs_root

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "rl": "cat:cs.LG AND abs:reinforcement learning",
    "nlp": "cat:cs.CL AND abs:large language model",
}


def main() -> int:
    kb_path = runs_root() / "kb" / "kb.jsonl"
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    kb = KnowledgeBase(kb_path)

    per_domain: dict[str, dict] = {}
    for domain, query in SOURCES.items():
        try:
            papers = fetch_arxiv(query, max_results=3)
        except Exception as exc:  # 取不到就记失败，不拿假数据顶
            per_domain[domain] = {"query": query, "fetched": 0, "error": f"{type(exc).__name__}: {exc}"}
            continue
        stored = 0
        for paper in papers:
            kb.add(claim=paper.title, domain=domain, evidence=[paper.url], source="arxiv")
            stored += 1
        per_domain[domain] = {
            "query": query,
            "fetched": len(papers),
            "stored": stored,
            "samples": [p.title[:80] for p in papers[:2]],
        }

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kb_path": str(kb_path),
        "domains": kb.domains(),
        "total_facts": kb.count(),
        "per_domain": per_domain,
        "passed": all(v.get("stored", 0) >= 2 for v in per_domain.values())
                  and len([d for d, v in per_domain.items() if v.get("stored", 0) >= 2]) >= 2,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"kb-fetch-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())