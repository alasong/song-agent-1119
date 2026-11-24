"""四道过程门。它们判的是「这一步能不能开始/能不能进下一步」，不是「结果好不好」。

结果好不好由判据管（`judge.py`），这里只管道工序：

    G1 声明先于执行   没声明目标/维度/判据/预算，一次调用都不许发
    G2 判据可执行     每条判据都已登记、形态合法、且跑过三反例自测
    G3 证据可定位     每条证据要么是 path:line（且文件与行号真实），要么是命令或读数
    G4 不静默失败     声明了的维度必须有判据覆盖；声明了的判据必须真的被执行过

G4 是这几道里最容易被跳过、也最贵的一道：声明了没人读，等于承诺没兑现且没人知道。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .judge import KINDS, Judge


@dataclass(frozen=True)
class Declaration:
    """开工前必须交出来的东西。它是 L0 与 L1 之间的契约。"""
    goal: str
    dims: tuple[str, ...]
    criteria: tuple[str, ...]
    budget_tokens: int


_EVIDENCE = (
    re.compile(r"^[\w./~+-]+:\d+$"),      # path:line
    re.compile(r"^\$ "),                   # 命令
    re.compile(r"^[^:]+=\S+"),             # 读数 key=value
)


def check_declaration(decl: Declaration, vocab) -> list[str]:
    problems: list[str] = []
    if not str(decl.goal or "").strip():
        problems.append("声明缺目标")
    dims = [str(d).strip() for d in decl.dims if str(d).strip()]
    if not dims:
        problems.append("声明缺维度：不声明按什么验收，等于没有验收")
    if len(set(dims)) != len(dims):
        problems.append(f"维度重复声明：{dims}")
    unknown = [d for d in dims if d not in vocab]
    if unknown:
        problems.append(f"维度不在词表内：{unknown}（词表外的维度要先审批）")
    if not [c for c in decl.criteria if str(c).strip()]:
        problems.append("声明缺判据")
    if not isinstance(decl.budget_tokens, int) or decl.budget_tokens <= 0:
        problems.append(f"预算必须是正整数，当前 {decl.budget_tokens!r}")
    return problems


def check_criteria(judge: Judge, decl: Declaration) -> list[str]:
    problems: list[str] = []
    for name in decl.criteria:
        crit = judge.get(name)
        if crit is None:
            problems.append(f"判据未登记：{name}")
            continue
        if crit.kind not in KINDS:
            problems.append(f"判据 {name} 形态不支持：{crit.kind}")
        if not crit.self_tested:
            problems.append(f"判据 {name} 没跑过三反例自测")
        outside = [d for d in crit.dims if d not in decl.dims]
        if outside:
            problems.append(f"判据 {name} 覆盖了未声明的维度：{outside}")
    return problems


def check_dependencies(note) -> list[str]:
    """step 级输入门：这一步想过依赖没有。

    note 为 None = 没提交断言单 = 没想过依赖；空清单同样拒。
    只判「写成什么样才算想过」，不判依赖够不够——那是结果门与验证方的事。
    """
    from .deps import check

    if note is None:
        return ["这一步没有提交依赖断言单：等于没想过依赖，不许开工"]
    return check(note)


def check_evidence(items) -> list[str]:
    problems: list[str] = []
    for raw in items or ():
        text = str(raw).strip()
        if not any(shape.search(text) for shape in _EVIDENCE):
            problems.append(f"证据不可定位：{text!r}（要 path:line、命令或读数）")
            continue
        if _EVIDENCE[0].search(text):
            path_part, _, line_part = text.rpartition(":")
            path = Path(path_part).expanduser()
            if not path.exists():
                problems.append(f"证据路径不存在：{text}")
            elif len(path.read_text(encoding="utf-8").splitlines()) < int(line_part):
                problems.append(f"证据行号超出文件长度：{text}")
    return problems


def check_silent_failure(judge: Judge, decl: Declaration, executed) -> list[str]:
    problems: list[str] = []
    declared = set(decl.criteria)
    for dim in decl.dims:
        covering = [n for n in declared
                    if judge.get(n) and dim in (judge.get(n).dims or ())]
        if not covering:
            problems.append(f"维度 {dim} 没有判据覆盖：声明了却没人读")
    for name in sorted(declared - set(executed)):
        problems.append(f"判据 {name} 声明了但本轮从未执行：声明了却没人读")
    return problems


def pre_flight(decl: Declaration, judge: Judge, vocab) -> dict:
    """开工前的合门：任何一条不成立，就不许发第一次调用。"""
    problems = check_declaration(decl, vocab) + check_criteria(judge, decl)
    return {"ok": not problems, "problems": problems}


def check_min_chars(text: str, spec: dict | None = None) -> list[str]:
    """交付体量判据：不许拿提纲当报告。

    阈值来自 `thresholds.json` 的 `delivery_min_chars`，spec 里带 min；不写死在代码里，
    因为「多少字才算够」是随经验调整的数，不是机制。
    """
    need = int((spec or {}).get("min") or 0)
    body = "".join(ch for ch in (text or "") if not ch.isspace())
    if need <= 0 or len(body) >= need:
        return []
    return [f"交付正文只有 {len(body)} 字 < 要求 {need} 字——门只查了「有没有」，没查「够不够」"]
