"""时效自检：说「最新」就得比今天新，拿不出日期就别叫最新。

为什么放在 core 而不是 forge：它不含业务词，判的只是「文本里的时间与今天的关系」，
也不需要模型参与——只用系统时间和交付里写的日期。这是第四种判据形态（callable）的
第一个用途：**不需要任何外部能力的自检**。

四条规则，每条都能判红：

- R1 占位引用：`xxxx` / 待填 / 待补充 / TODO / 占位——读者拿不到可核验的东西
- R2 标题承诺「最新 / 近期 / 进展 / 趋势」，正文却一个日期都没有——那是凭记忆写的
- R3 有日期，但最新一条距今超过上限（默认 180 天）——「最新」两个字是假的
- R4 出现未来日期——那是编的

代码围栏里的内容不参与判定（和交付检查同一口径）。
"""
from __future__ import annotations

import re
from datetime import date

DEFAULT_MAX_AGE_DAYS = 180
DATE = re.compile(r"(20\d{2})[-/年.](\d{1,2})(?:[-/月.](\d{1,2}))?")
PLACEHOLDER = re.compile(r"x{4,}|待填|待补充|待核实|TODO|占位", re.I)
CLAIM_WORDS = ("最新", "近期", "进展", "趋势", "前沿")
FENCE = re.compile(r"^\s*```")


def _unfenced(text: str) -> list[str]:
    """去掉代码围栏内的行：围栏里讨论日期或占位符不算声称。"""
    out: list[str] = []
    inside = False
    for line in (text or "").splitlines():
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return out


def dates(text: str) -> list[date]:
    found: list[date] = []
    for line in _unfenced(text):
        for year, month, day in DATE.findall(line):
            try:
                found.append(date(int(year), int(month), int(day or 1)))
            except ValueError:
                continue
    return found


def stale_problems(text: str, today: date | None = None,
                   max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> list[str]:
    """返问题清单；空 ⇒ 通过。给 judge 当 callable 判据用（只传 text）。"""
    now = today or date.today()
    body = _unfenced(text)
    problems: list[str] = []

    placeholders = [ln.strip()[:60] for ln in body if PLACEHOLDER.search(ln)]
    if placeholders:
        problems.append(f"R1 有 {len(placeholders)} 处占位引用（示例：{placeholders[0]}）")

    found = dates(text)
    claimed = [ln.strip().lstrip("#").strip() for ln in body
               if ln.lstrip().startswith("#") and any(w in ln for w in CLAIM_WORDS)]
    if claimed and not found:
        problems.append(f"R2 标题承诺「{claimed[0][:20]}」，全文没有一个日期——"
                        f"没有时间锚点的「最新」是凭记忆写的")

    future = [d for d in found if d > now]
    if future:
        problems.append(f"R4 有 {len(future)} 个未来日期（最新 {max(future).isoformat()}，"
                        f"晚于今天 {now.isoformat()}）——那是编的")

    past = [d for d in found if d <= now]
    if past:
        newest = max(past)
        age = (now - newest).days
        if age > max_age_days:
            problems.append(f"R3 最新日期 {newest.isoformat()}，距今 {age} 天 > {max_age_days} 天"
                            f"——这个时间锚点撑不起「最新」")
    return problems