"""任务 I（一次真跑的成本账）的确定性路径：从 readings.json 渲染，不调模型。

这是内环的第一片切片：真值在本地，同输入必同输出；判定权不在这里，
而在 `sa2/core/cost_check.py`——生成方与判定方分模块，是这条切片的全部意义。
"""
from __future__ import annotations

import json
from pathlib import Path


def render(run_dir: str | Path) -> dict:
    data = json.loads((Path(run_dir) / "readings.json").read_text(encoding="utf-8"))
    return {
        "tokens": int((data.get("budget") or {}).get("spent") or 0),
        "rejects": int(data.get("rejects") or 0),
        "redone_count": len(data.get("redone") or []),
    }