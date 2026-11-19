"""sa 2.0：一个薄且固定的判定层 + 三圈可自生成的载体。

sa 1.0（`xm/`）已于 2026-11-20 退役；本包是照「重来骨架」重写的唯一实现，
用来验证那条骨架是否成立。退役记录见 `docs/SA2.md` §9.8。

四层（只有第 0 层不许自生成）：
    core/    L0  判定权、账本、预算闸、四道过程门 —— 永不改变，不含业务词
    forge/   L1  目标、编制、流程、维度声明、判据实例、检查工具 —— sa 自己造
    loop/    L2  PDCA 环：声明 → 前置门 → 执行 → 阶段门 → 交付门
    memory/      案例库：失败案例优先

红线：**生成方永不对判据拥有判定权**。`Judge` 的 authority 只放外部方
（领导 / 独立验证方），`forge` 只能 propose，propose 出来的判据必须先过三反例自测。
"""
from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["core", "forge", "loop", "memory"]