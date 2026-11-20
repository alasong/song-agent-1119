"""维度词表：验收只能落在这 8 个词上，词表外要先审批。

与 kaa 的关键区别：kaa 的因子表是**关键词触发**（task 文本命中 auth/pii 就注入 security），
实测对中文任务命中 1.5%；这里的词表只做**值域约束**——选哪几维由生成方决定，
判定侧只检查「选的是不是词表里的、选了有没有判据覆盖」。
换句话说：不猜意图，只验声明。
"""
from __future__ import annotations

from ..knowledge import load

VOCAB: dict[str, str] = dict(load("vocab")["dims"])   # 词表在 sa2/knowledge/data/vocab.json


def validate(selected) -> list[str]:
    dims = [str(d).strip() for d in (selected or ())]
    problems: list[str] = []
    if not dims:
        problems.append("没有选维度：不声明按什么验收，等于没有验收")
    unknown = [d for d in dims if d not in VOCAB]
    if unknown:
        problems.append(f"词表外维度：{unknown}（造新词等于扩大判定空间，要先审批）")
    if len(set(dims)) != len(dims):
        problems.append(f"维度重复：{dims}")
    return problems


def declare(selected) -> tuple[str, ...]:
    problems = validate(selected)
    if problems:
        raise ValueError("；".join(problems))
    return tuple(str(d).strip() for d in selected)


def describe() -> list[tuple[str, str]]:
    return [(key, name) for key, name in VOCAB.items()]