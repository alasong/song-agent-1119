"""健康指标采集（trend 按末两项比较得出 rising/falling/flat）。"""
from __future__ import annotations

NAMES = ["目标偏离度", "校验通过率", "通信效率", "资源利用率", "假设证伪率"]


class MetricsError(RuntimeError):
    pass


class Metrics:
    def __init__(self):
        self._data = {n: [] for n in NAMES}

    def _check(self, name):
        if name not in self._data:
            raise MetricsError(f"未知指标：{name}")

    def record(self, name, value):
        self._check(name)
        self._data[name].append(value)

    def value(self, name):
        self._check(name)
        vals = self._data[name]
        return vals[-1] if vals else None

    def trend(self, name):
        self._check(name)
        vals = self._data[name]
        if len(vals) < 2:
            return "flat"
        prev, last = vals[-2], vals[-1]
        if last > prev:
            return "rising"
        if last < prev:
            return "falling"
        return "flat"

    def snapshot(self):
        return {
            n: {"last": (v[-1] if v else None), "n": len(v)}
            for n, v in self._data.items()
        }
