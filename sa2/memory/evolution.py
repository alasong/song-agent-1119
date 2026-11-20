"""经验 → 机制候选。**只产候选，不生效。**

这条通道的意义：经验如果永远只是「每次多注入一句话」，它就长不成机制，系统每遇到一个
新场景仍要人改代码。够格的经验应该能提出「把这条变成机制」的候选——但**不能自己生效**：
生成方对自己的判据永远没有判定权。所以这里只写 `candidates.jsonl`，进 `registry` 要人登记。

提升判据（可机检，不看感觉）：
- 同一 `when` 下至少有 `min_support` 条经验；
- 这些经验被注入过（`injected > 0`）；
- 平均成功率 `ok/injected ≥ min_rate`。

候选形态现在只做一种：`prompt_note`（把同类经验并成一条注入片段）。生成判据代码、生成
解析器这类候选等有了独立验收手段再说——现在放开等于让经验库直接改判定。
"""
from __future__ import annotations

import json
from pathlib import Path

from .lessons import _rate


def candidates(lessons: list[dict], min_support: int = 2, min_rate: float = 0.8) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for lesson in lessons:
        if str(lesson.get("status") or "active") != "active":
            continue
        key = json.dumps(lesson.get("when") or {}, sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, []).append(lesson)

    out: list[dict] = []
    for key, items in groups.items():
        if len(items) < min_support:
            continue
        injected = sum(int((item.get("stats") or {}).get("injected") or 0) for item in items)
        if injected <= 0:
            continue
        rate = sum(_rate(item) for item in items) / len(items)
        if rate < min_rate:
            continue
        out.append({
            "when": dict(items[0].get("when") or {}),
            "ids": [str(item.get("id")) for item in items],
            "support": len(items),
            "injected": injected,
            "rate": round(rate, 3),
            "proposal": {
                "kind": "prompt_note",
                "text": " / ".join(str(item.get("text") or "").strip() for item in items),
            },
            "status": "proposed",     # 不生效：等 registry 登记
        })
    return out


def write(path: str | Path, found: list[dict]) -> int:
    """把候选追加进文件。同一条（when + ids）不重复写。"""
    if not found:
        return 0          # 没有候选就别建文件：空文件会让人以为「提升过一轮，结果是空的」
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            seen.add((json.dumps(row.get("when"), sort_keys=True, ensure_ascii=False),
                      tuple(row.get("ids") or ())))
    added = 0
    with target.open("a", encoding="utf-8") as fh:
        for item in found:
            key = (json.dumps(item.get("when"), sort_keys=True, ensure_ascii=False),
                   tuple(item.get("ids") or ()))
            if key in seen:
                continue
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            seen.add(key)
            added += 1
    return added