"""配置面：阈值不再写死在代码里。

只放「会随经验调整」的数：规模决策阈值、工具执行上限。
环境变量优先（`XM_SA2_<KEY>`），其次代码默认值——不引第三方依赖、不建配置文件目录。
"""
from __future__ import annotations

import os

DEFAULTS: dict[str, float] = {
    "single_floor": 20_000,   # 低于这个预算不组队
    "team_dims": 2,           # 声明这么多维度就该分工
    "team_criteria": 3,       # 声明这么多判据就该独立验证
    "tool_timeout": 10,       # 生成的检查器单次执行上限（秒）
}


def get(key: str):
    if key not in DEFAULTS:
        raise KeyError(f"未登记的配置项：{key}（要加先写进 DEFAULTS）")
    raw = os.environ.get(f"XM_SA2_{key.upper()}")
    if raw is None:
        return DEFAULTS[key]
    default = DEFAULTS[key]
    try:
        return int(raw) if isinstance(default, int) else float(raw)
    except ValueError as exc:
        raise ValueError(f"配置 XM_SA2_{key.upper()}={raw!r} 无法解析") from exc