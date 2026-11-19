"""阶段准出：每个阶段有可机检的准出项，不合格不许进下一阶段（设计文档 §15.4）。

顺序被强制：跳阶段不是「加速」，是「没做」。
"""
from __future__ import annotations

STAGES = ["需求分解", "设计", "实现", "定位", "运维"]

REQUIRED = {
    "需求分解": "判据",
    "设计": "契约",
    "实现": "判据跑过",
    "定位": "复现用例",
    "运维": "回滚演练",
}


class GateFailed(RuntimeError):
    """准出未过：乱序或缺准出项。"""


class GateChain:
    def __init__(self):
        self.passed: list[str] = []

    def check(self, stage: str, artifacts: dict) -> None:
        if stage not in STAGES:
            raise GateFailed(f"未知阶段：{stage}")
        expected = STAGES[len(self.passed)] if len(self.passed) < len(STAGES) else None
        if stage != expected:
            raise GateFailed(f"阶段乱序：应当先过「{expected}」，实际是「{stage}」")
        needed = REQUIRED[stage]
        if not artifacts.get(needed):
            raise GateFailed(f"「{stage}」缺准出项：{needed}")
        self.passed.append(stage)