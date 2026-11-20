"""M2：门按任务类型分层。

判据本身不改，改的是**挂哪几条**：
- default：要外部证据（引用 ≥3、出处可查、体量达标）——原来的口径；
- annotation：没有外部证据可引（标注/判定类任务），只保体量，不挂引用与出处；
- engineering：必须有验收命令（测试）；没有测试的工程任务不算交付。

为什么不在判据里写 if：那会把“任务类型”塞进判定逻辑，类型一变判据就得改。
这里只做装配，判据仍由 judge 执行。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateProfile:
    name: str
    min_citations: int
    require_references: bool
    min_chars: int | None      # None = 用调用方的默认体量阈值


PROFILES = {
    "default": GateProfile("default", min_citations=3, require_references=True, min_chars=None),
    "annotation": GateProfile("annotation", min_citations=0, require_references=False, min_chars=200),
    "engineering": GateProfile("engineering", min_citations=0, require_references=False, min_chars=None),
}


def get(name: str) -> GateProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise KeyError(f"未知任务类型：{name}（可选：{sorted(PROFILES)}）") from None


def delivery_specs(profile: GateProfile, *, book: str, volume_min: int) -> list[dict]:
    """按 profile 装配交付判据的 spec；不执行，只描述。"""
    specs: list[dict] = []
    if profile.min_citations > 0:
        specs.append({"name": "交付·引用",
                      "spec": {"target": "sa2.core.evidence:check_citations",
                               "book": book, "min": profile.min_citations}})
        specs.append({"name": "交付·体量",
                      "spec": {"target": "sa2.core.gate:check_min_chars",
                               "min": int(volume_min)}})
    elif profile.min_chars is not None:
        specs.append({"name": "交付·体量",
                      "spec": {"target": "sa2.core.gate:check_min_chars",
                               "min": int(profile.min_chars)}})
    if profile.require_references:
        specs.append({"name": "交付·出处",
                      "spec": {"target": "sa2.core.evidence:check_references",
                               "book": book}})
    return specs


def check_task(profile: GateProfile, *, test_cmd=None) -> list[str]:
    """开跑前的任务级检查。工程型没测试命令 → 拒，一次调用都不发。"""
    if profile.name == "engineering" and not test_cmd:
        return ["工程型任务必须带验收命令（test_cmd）：没有测试的工程任务不算交付"]
    return []