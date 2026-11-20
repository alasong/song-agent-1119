"""配置面：阈值不再写死在代码里。

只放「会随经验调整」的数：规模决策阈值、工具执行上限。
环境变量优先（`XM_SA2_<KEY>`），其次代码默认值——不引第三方依赖、不建配置文件目录。
"""
from __future__ import annotations

import os

from .knowledge import load


def values() -> dict[str, float]:
    """现有阈值：数在数据文件里，代码里没有默认值可落。"""
    return {key: item["value"] for key, item in load("thresholds")["values"].items()}


def provenance(key: str) -> dict:
    """这个数从哪次实测来、哪天定的。改它之前先看这里。"""
    table = load("thresholds")["values"]
    if key not in table:
        raise KeyError(f"未登记的配置项：{key}（要加先进 thresholds.json）")
    return dict(table[key])


def get(key: str):
    table = load("thresholds")["values"]
    if key not in table:
        raise KeyError(f"未登记的配置项：{key}（要加先进 thresholds.json）")
    default = table[key]["value"]
    raw = os.environ.get(f"XM_SA2_{key.upper()}")
    if raw is None:
        return default
    try:
        return int(raw) if isinstance(default, int) else float(raw)
    except ValueError as exc:
        raise ValueError(f"配置 XM_SA2_{key.upper()}={raw!r} 无法解析") from exc