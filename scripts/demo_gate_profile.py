#!/usr/bin/env python3
"""M2 演示：同一套判据，按任务类型挂不同的门。

跑法：python3 scripts/demo_gate_profile.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core.gate_profiles import check_task, delivery_specs, get  # noqa: E402

for name in ("default", "annotation", "engineering"):
    profile = get(name)
    specs = delivery_specs(profile, book="evidence.jsonl", volume_min=1200)
    shown = [(s["name"], s["spec"].get("min")) for s in specs] or "无交付判据"
    print(f"{name:<11} 交付判据={shown}")
    print(f"{'':<11} 开跑前检查={check_task(profile, test_cmd=None) or '过'}")

print("\n结论：default 仍要引用 ≥3；annotation 只保体量 200（标注/判定类不再被误杀）；")
print("      engineering 没有 test_cmd 直接拒，不由交付门兜底。")