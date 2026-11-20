"""任务 I 的判定权：逐项对账本，缺字段或数字错都判红。

刻意不 import `loop/cost_page.py`：判定方自己重算真值，不借用生成方的计算结果。
这样即使渲染逻辑写错，验证器也不会跟着一起错——它红，而不是一起绿。
"""
from __future__ import annotations

import json
from pathlib import Path

FIELDS = ("tokens", "rejects", "redone_count")


def truth(run_dir: str | Path) -> dict:
    data = json.loads((Path(run_dir) / "readings.json").read_text(encoding="utf-8"))
    return {
        "tokens": int((data.get("budget") or {}).get("spent") or 0),
        "rejects": int(data.get("rejects") or 0),
        "redone_count": len(data.get("redone") or []),
    }


def check(page, run_dir: str | Path) -> list[str]:
    if not isinstance(page, dict):
        return ["交付物不是对象"]
    problems = [f"缺字段：{key}" for key in FIELDS if key not in page]
    want = truth(run_dir)
    for key in FIELDS:
        if key in page and page[key] != want[key]:
            problems.append(f"{key}: 写的是 {page[key]!r}，账本是 {want[key]!r}")
    return problems