"""S6：盲评。送进评委的只有「文档1 / 文档2」，不含出处；顺序可以翻，映射回来由系统做。

为什么要有这一层：模型给的绝对分进门等于模型自评（`docs/OPTIMALITY.md` §4），
所以它只能当**对比工具**——同一组判据下比较两份稿子，不参与准出。
"""
from __future__ import annotations

import json
import re

DIMS = ("结论", "证据", "取舍", "局限", "可执行")

PROMPT = """你是独立评委，不知道下面两份文档分别出自谁。
请按 5 个维度各打 0-3 分：结论、证据、取舍、局限、可执行。
只输出 JSON（不要解释、不要代码围栏）：
{"1": {"结论": 0, "证据": 0, "取舍": 0, "局限": 0, "可执行": 0},
 "2": {"结论": 0, "证据": 0, "取舍": 0, "局限": 0, "可执行": 0}}
"""


def _parse(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("评委输出里没有 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"评委输出不是合法 JSON：{exc}") from exc
    for key in ("1", "2"):
        scores = data.get(key)
        if not isinstance(scores, dict):
            raise ValueError(f"缺文档{key}的分数")
        for dim in DIMS:
            value = scores.get(dim)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
                raise ValueError(f"文档{key}「{dim}」的分数不合法：{value!r}")
    return data


def blind_score(first: str, second: str, llm, flip: bool = False) -> dict:
    """返回 {"first": 分数, "second": 分数, "order": straight|flipped}。"""
    docs = {"1": second if flip else first, "2": first if flip else second}
    prompt = f"{PROMPT}\n文档1：\n{docs['1']}\n\n文档2：\n{docs['2']}"
    data = _parse(llm([{"role": "user", "content": prompt}]))
    if flip:
        return {"first": data["2"], "second": data["1"], "order": "flipped"}
    return {"first": data["1"], "second": data["2"], "order": "straight"}