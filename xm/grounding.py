"""引用可溯源：交付里的每条结论必须标注真实存在的知识条目。

这是「取了会用」的机检判据：引用 id 必须能在知识底座里查到，
且数量不少于下限。查不到 = 幻觉引用 = 判红。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from xm.kb import KnowledgeBase

REF = re.compile(r"\[ref:([0-9a-f]{16})\]")


def kb_path() -> Path:
    return Path(os.environ.get("XM_KB_PATH", str(Path.home() / "xm-runs" / "kb" / "kb.jsonl")))


def check_refs(text: str, min_refs: int = 3) -> dict:
    kb = KnowledgeBase(kb_path())
    known = kb.keys()
    refs = REF.findall(text or "")
    missing = [r for r in refs if r not in known]
    return {
        "ok": len(refs) >= min_refs and not missing,
        "refs": len(refs),
        "missing": missing[:3],
        "known": len(known),
    }


def has_valid_refs(payload: dict) -> bool:
    return check_refs(payload.get("text", ""))["ok"]