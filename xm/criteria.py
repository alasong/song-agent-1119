"""判据注册表：带版本号，升格必须过 calibration（设计文档 §15.8(3)）。

人的自我标准是内化的外部评价，各人版本不同。在系统里必须显式化：
判据全同 → 集体盲区；判据互不兼容 → 无法比较、无法校准。
"""
from __future__ import annotations

from typing import Callable

Judge = Callable[[dict], bool]
Calibration = Callable[[dict, dict], bool]


class CriterionError(RuntimeError):
    """判据不存在或重复注册。"""


class Registry:
    def __init__(self):
        self._items: dict[str, dict] = {}

    def register(self, name: str, version: int, judge: Judge) -> None:
        if name in self._items:
            raise CriterionError(f"判据已存在：{name}")
        self._items[name] = {"name": name, "version": version, "judge": judge}

    def get(self, name: str) -> dict:
        if name not in self._items:
            raise CriterionError(f"未注册判据：{name}")
        return dict(self._items[name])

    def propose(self, name: str, version: int, judge: Judge, calibration: Calibration) -> bool:
        """新判据只有在 calibration 通过时才升格为默认版本。

        calibration 的判据（设计文档 §15.8(3)）：新判据下自评准确率不劣于旧版，
        且至少多抓到一条旧版漏掉的错误。这里交给调用方实现，注册表只认结论。
        """
        current = self.get(name)
        candidate = {"name": name, "version": version, "judge": judge}
        if not bool(calibration(current, candidate)):
            return False
        self._items[name] = candidate
        return True