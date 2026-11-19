"""质量判据：同一张评分表 + 盲评，让「谁更好」可以判，而不是我说了算。

三条设计约束：
- **盲**：送进去的只有「文档 1 / 文档 2」，不含出处（哪个是组织写的、哪个是单 agent）。
  评分者知道身份就会按身份打，那评出来的不是质量，是立场。
- **可核对**：每个维度 0–3 分并给一句理由；总分是维度之和，不做加权——
  加权会引入一个没人同意的隐藏假设。
- **fail-closed**：解析不出分数就抛错，不猜、不补默认分。宁可这次没用，也不能伪造读数。
"""
from __future__ import annotations

import json
import random
import re
from typing import Callable

MAX = 3

RUBRIC: list[tuple[str, str]] = [
    ("结论", "开篇一句话说清做成了什么、没做成什么，且与正文一致"),
    ("证据", "关键断言有可核对的依据（命令、读数、文件路径），不是形容词堆砌"),
    ("取舍", "给出候选与取舍理由，说明否掉了什么、为什么否"),
    ("局限", "明写未验证项、依赖条件、只验了哪一层"),
    ("可执行", "读者能据此做出下一步决定，而不是看完还得再问一次"),
]
TOTAL_MAX = len(RUBRIC) * MAX
DIMS = [name for name, _ in RUBRIC]


class QualityError(RuntimeError):
    """评分不可用。宁可报错，也不许编一个分数出来。"""


def blind_prompt(texts: list[str]) -> str:
    """构造盲评提示：只有编号与正文，没有任何能指向出处的字样。"""
    blocks = [f"### 文档 {i + 1}\n{text.strip()[:6000]}" for i, text in enumerate(texts)]
    rubric = "\n".join(f"- {name}（0–{MAX}）：{desc}" for name, desc in RUBRIC)
    example = json.dumps(
        {"scores": [{"doc": i + 1,
                     "dims": {name: 0 for name in DIMS},
                     "note": "不超过 40 字的理由"} for i in range(len(texts))]},
        ensure_ascii=False,
    )
    return f"""你是独立评审，只按下面的评分表给分。你不知道这些文档是谁写的，也不要去猜。

## 评分表（每维 0–{MAX} 分）
{rubric}

## 待评文档
{chr(10).join(blocks)}

## 输出
只返回一个 JSON，不要任何解释或代码块标记：
{example}

要求：每一项都要给整数分；分数要能被文档里的原句支撑，不要给中间分凑数。"""


def parse_scores(raw: str, n: int) -> list[dict]:
    """解析评分；缺维度、越界、数量不对都算失败。"""
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise QualityError("评分输出里没有 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise QualityError(f"评分 JSON 解析失败：{exc}") from exc
    items = data.get("scores") or []
    if len(items) != n:
        raise QualityError(f"应有 {n} 份评分，实际 {len(items)} 份")
    out = []
    for item in items:
        dims = item.get("dims") or {}
        missing = [d for d in DIMS if d not in dims]
        if missing:
            raise QualityError(f"文档 {item.get('doc')} 缺维度：{missing}")
        for name in DIMS:
            value = dims[name]
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX:
                raise QualityError(f"文档 {item.get('doc')} 的「{name}」分数非法：{value!r}")
        out.append({"doc": item.get("doc"),
                    "dims": {name: dims[name] for name in DIMS},
                    "total": sum(dims[name] for name in DIMS),
                    "note": str(item.get("note", ""))[:200]})
    return out


def order_for(n: int, seed: int) -> list[int]:
    """用种子决定文档顺序：避免「总是 A 在前」带来的位置偏差，且可复现。"""
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    return idx


def judge(texts: list[str], llm: Callable[[list[dict]], str], seed: int = 0) -> dict:
    """盲评。返回的 order[k] 是「文档 k+1」对应的原始下标，调用方据此映射回去。"""
    if len(texts) < 2:
        raise QualityError("至少要有两份文档才谈得上比较")
    order = order_for(len(texts), seed)
    shuffled = [texts[i] for i in order]
    raw = llm([{"role": "user", "content": blind_prompt(shuffled)}])
    scored = parse_scores(raw, len(texts))
    by_label = {item["doc"]: item for item in scored}
    ranked = []
    for pos, original in enumerate(order, 1):
        item = by_label.get(pos)
        if item is None:
            raise QualityError(f"缺「文档 {pos}」的评分")
        ranked.append({"index": original, **item})
    best = max(r["total"] for r in ranked)
    winners = [r["index"] for r in ranked if r["total"] == best]
    return {
        "blind": True,
        "seed": seed,
        "rubric": [{"dim": name, "max": MAX, "desc": desc} for name, desc in RUBRIC],
        "scores": ranked,
        "winner": winners[0] if len(winners) == 1 else None,
        "tie": len(winners) > 1,
    }