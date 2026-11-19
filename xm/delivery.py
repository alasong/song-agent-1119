"""交付自证：sa 自己的产物也要过三段检查，不能只靠宿主 agent 记得。

这是 DNA #9「交付可自证」的运行时。规则只有五条，每条都能判红：

- R1 三段齐全：结论 / 依据 / 证据
- R2 结论首行带读数（数字 + 单位）——「已完成」不是结论
- R3 依据 1–3 条，且至少一条写了否掉
- R4 证据段含可定位物（报告路径、`path:line`、提交号、命令+退出码）
- R5 没有裸称「最优」（引号里讨论不算）

判不了的明说：格式过了不等于内容对，这个模块只判「有没有自证」，不判「自证得对不对」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

READING = re.compile(r"\d+(?:\.\d+)?\s*(?:次|个|条|分|%|tokens|小时|轮|处|行|人)")
EVIDENCE = re.compile(
    r"(?:reports/[\w.\-]+"          # 报告文件
    r"|[\w./\-]+\.(?:py|md|json):\d+"  # path:line
    r"|\b[0-9a-f]{7,40}\b"          # 提交号
    r"|exit\s*=?\s*\d+|退出码\s*\d+)"  # 命令退出码
)
BARE = "最优"
QUOTED = re.compile(r"「[^」]*」|“[^”]*”|\"[^\"]*\"|`[^`]*`")
FENCE = re.compile(r"^\s*```")

# 三种写法都认：`## 结论`、`**结论**：`、`结论：`
HEADINGS = {
    "结论": re.compile(r"^(?:#{1,4}\s*结论|\*\*结论\*\*\s*[:：]?|结论\s*[:：])", re.M),
    "依据": re.compile(r"^(?:#{1,4}\s*依据|\*\*依据\*\*\s*[:：]?|依据\s*[:：])", re.M),
    "证据": re.compile(r"^(?:#{1,4}\s*证据|\*\*证据\*\*\s*[:：]?|证据\s*[:：])", re.M),
}
BULLET = re.compile(r"^\s*(?:[-*]|\d+[.、)])\s+", re.M)
NEGATED = ("否掉", "不采用", "放弃了", "而不是", "排除")


def bare_optimal_lines(text: str) -> list[tuple[int, str]]:
    """未加引号、不在代码块里、同行没有读数的「最优」——调用方决定怎么报。"""
    out: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate((text or "").splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if BARE in QUOTED.sub("", line) and not READING.search(line):
            out.append((lineno, line.strip()))
    return out


def sections(text: str) -> dict[str, str]:
    """按三个标题切段；标题之间的内容归到该段，到下一个标题为止。"""
    found: list[tuple[int, int, str]] = []
    for name, pattern in HEADINGS.items():
        for match in pattern.finditer(text or ""):
            found.append((match.start(), match.end(), name))
    found.sort()
    cuts: dict[str, str] = {}
    for idx, (start, end, name) in enumerate(found):
        stop = found[idx + 1][0] if idx + 1 < len(found) else len(text)
        body = text[end:stop]
        cuts[name] = (cuts.get(name, "") + "\n" + body).strip()
    return cuts


def check(text: str) -> dict:
    """返回 {ok, missing, reasons}。ok=False 时 missing 说明缺哪条。"""
    parts = sections(text)
    missing: list[str] = []
    reasons: list[str] = []

    for name in ("结论", "依据", "证据"):
        if not parts.get(name):
            missing.append(f"R1 缺「{name}」段")

    body = parts.get("结论", "")
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if body and not READING.search(first):
        missing.append("R2 结论首行没有读数（数字+单位）")
        reasons.append(f"结论首行：{first[:60]!r}")

    bullets = BULLET.findall(parts.get("依据", ""))
    if parts.get("依据"):
        if not bullets:
            missing.append("R3 依据不是条目式（用 - 或数字列表）")
        elif len(bullets) > 3:
            missing.append(f"R3 依据 {len(bullets)} 条，超过 3 条")
        elif not any(word in parts["依据"] for word in NEGATED):
            missing.append("R3 依据里没有一条写「否掉了什么」")

    if parts.get("证据") and not EVIDENCE.search(parts["证据"]):
        missing.append("R4 证据段没有可定位物（报告路径 / path:line / 提交号 / 退出码）")

    bad = bare_optimal_lines(text)
    if bad:
        missing.append(f"R5 有 {len(bad)} 处裸称「最优」")
        reasons += [f"第 {ln} 行：{ln_text[:60]}" for ln, ln_text in bad[:3]]

    return {"ok": not missing, "missing": missing, "reasons": reasons}

@dataclass(frozen=True)
class RunFacts:
    """拼自证要用的事实。全部来自运行记录，不由模型提供。"""
    criteria_ok: bool
    mode: str                 # single / org
    calls: int
    chars: int
    decision: str             # 为什么这么选
    rejected: str             # 否掉了什么
    artifact: str
    extra: tuple[str, ...] = ()


def compose(facts: RunFacts) -> str:
    """把运行事实拼成三节。缺字段就不编——空证据会被 check() 判红。"""
    verdict = "exit 0" if facts.criteria_ok else "未通过"
    conclusion = (f"判据 {verdict}；{facts.mode} 路径；"
                  f"{facts.calls} 次调用；正文 {facts.chars} 字。")
    lines = [f"- 选 {facts.mode} → 否掉了{facts.rejected}，因为{facts.decision}。"]
    evidence = [f"- `check.py` exit {0 if facts.criteria_ok else 1}",
                f"- 产物 {facts.artifact}",
                "- 记录 ~/xm-runs/history/history.jsonl"]
    evidence += [f"- {item}" for item in facts.extra]
    return ("\n## 结论\n" + conclusion +
            "\n\n## 依据\n" + "\n".join(lines) +
            "\n\n## 证据\n" + "\n".join(evidence) + "\n")


def attach(path, facts: RunFacts) -> bool:
    """把自证追加到产物末尾；已有就不再追加（产物是证据，不许重写）。"""
    target = Path(path)
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8")
    if "## 结论" in text and "## 证据" in text:
        return False
    target.write_text(text.rstrip() + "\n" + compose(facts), encoding="utf-8")
    return True
