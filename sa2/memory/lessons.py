"""经验：**条件 + 对策**，不是一个全局字符串。

为什么要有它：原来「教训」只有两个存放处——提示词常量（全场景生效）和案例库（`fix` 字段
被写成一句固定话，等于没信息）。经验要能长大，必须先能回答「这条在什么情况下算数」。

`when` 的键与值**只能是 vocab.json 里登记过的枚举**。这一条不许放松：条件一旦可以自由
拼文本，「按情境匹配」就退化成按关键词匹配，最后又变成一条全局规则。

存放位置：运行期（默认跟案例库同一个目录），不进 git。够格的条目由导出脚本
`scripts/knowledge_export.py` 写回仓库，由人 review 后提交——经验不能自己进版本库。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from ..knowledge import load


class LessonError(RuntimeError):
    """经验不合格：条件没登记、缺字段、格式不对。"""


def event_space() -> dict[str, list[str]]:
    return {key: list(values) for key, values in load("vocab")["events"].items()}


def check_when(when: dict) -> dict:
    """校验条件：键必须在事件空间里，值必须在对应枚举里。"""
    space = event_space()
    if not isinstance(when, dict) or not when:
        raise LessonError("when 不能为空：没有条件的经验只能当全局规则，那正是要消灭的东西")
    unknown = set(when) - set(space)
    if unknown:
        raise LessonError(f"when 里有未登记的条件 {sorted(unknown)}（可选 {sorted(space)}）")
    for key, value in when.items():
        if value not in space[key]:
            raise LessonError(f"when.{key}={value!r} 不在 {space[key]} 里——"
                              f"条件值域是枚举，不许现编")
    return dict(when)


def _gid(text: str, when: dict) -> str:
    raw = (text or "").strip() + "|" + json.dumps(when, sort_keys=True, ensure_ascii=False)
    return "L" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def add(path: str | Path, text: str, when: dict, fix: str = "", origin: str = "") -> dict:
    """写一条经验。stats 从零开始，由用它的地方回写。"""
    if not (text or "").strip():
        raise LessonError("经验没有正文：只写「要注意」不算经验")
    lesson = {
        "id": _gid(text, when),
        "when": check_when(when),
        "text": text.strip(),
        "fix": (fix or "").strip(),
        "origin": (origin or "").strip(),
        "stats": {"injected": 0, "ok": 0, "bad": 0},
        "status": "active",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    for row in all(path):
        if row.get("id") == lesson["id"]:
            return row                  # 同一条经验不重复追加：重复只会撑「支持数」的假象
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(lesson, ensure_ascii=False) + "\n")
    return lesson


def all(path: str | Path) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # 坏行跳过而不是整库挂掉：经验库是"可重建"的
    return out


def _rate(lesson: dict) -> float:
    stats = lesson.get("stats") or {}
    injected = int(stats.get("injected") or 0)
    if injected <= 0:
        return 0.5           # 没用过的不排前面，也不判死
    return int(stats.get("ok") or 0) / injected


def match(lessons: list[dict], when: dict, k: int = 3) -> list[dict]:
    """按条件取经验：先精确命中（全部键相等），不足再按命中键数放宽。

    排序：命中键数多者优先，其次成功率高的优先；`retired` 的不参与。
    """
    if not when:
        return []
    space = event_space()
    unknown = set(when) - set(space)
    if unknown:
        raise LessonError(f"查询里有未登记的条件 {sorted(unknown)}")
    scored = []
    for lesson in lessons:
        if str(lesson.get("status") or "active") != "active":
            continue
        cond = lesson.get("when") or {}
        overlap = [key for key, value in when.items() if cond.get(key) == value]
        if not overlap:
            continue
        exact = len(overlap) == len(when) and len(overlap) == len(cond)
        scored.append((1 if exact else 0, len(overlap), _rate(lesson), lesson))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [lesson for *_, lesson in scored[:max(1, int(k))]]

def classify(problems) -> str:
    """把一次拒收的问题文本归到 failure_kind。规则在 `classify.json`，不在代码里。

    没有这一步，「按条件取经验」就没有条件可取——拒收原因只有一段自然语言。
    """
    text = "；".join(str(p) for p in (problems or ()))
    for rule in load("classify")["failure_patterns"]:
        try:
            if re.search(str(rule["pattern"]), text):
                return str(rule["kind"])
        except re.error as exc:
            raise LessonError(f"归类规则 {rule['kind']} 的正则编不过：{exc}") from exc
    return "criteria_rejected"


def bump(path: str | Path, ids, field: str = "injected") -> int:
    """给这几条经验记一笔（injected / ok / bad）。返回改到的条数。

    回写整份 jsonl：经验库本来就小，一次重写的代价远低于引入索引文件。
    """
    wanted = set(ids or ())
    if not wanted or field not in ("injected", "ok", "bad"):
        return 0
    target = Path(path)
    rows = all(target)
    hit = 0
    for row in rows:
        if row.get("id") in wanted:
            stats = row.setdefault("stats", {"injected": 0, "ok": 0, "bad": 0})
            stats[field] = int(stats.get(field) or 0) + 1
            hit += 1
    if hit:
        tmp = target.with_suffix(target.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, target)
    return hit