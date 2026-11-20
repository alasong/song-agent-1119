"""S6：L0–L2 判定。「更优」不是形容词，是四件套齐全时的一个可复跑读数。

四件套（`docs/OPTIMALITY.md` §3）：候选集、预算 B、判据版本、与 baseline 的差值。
缺任意一件，最高只能判 L0（合格），不许声称 L1/L2。

判据（同文件 §2）：
- L0 合格：判据通过；
- L1 占优：同一组判据与预算下，相对 baseline **帕累托严格更好**（至少一维更好，其余不更差）；
- L2 未发现更优：在预算 B 内试了 N 个候选，没有出现 L1 占优者。
"""
from __future__ import annotations


def dominates(a: dict, b: dict, dims: dict[str, int]) -> bool:
    """a 是否帕累托严格优于 b。dims: 维度 → +1 越大越好 / -1 越小越好。"""
    better = False
    for dim, direction in dims.items():
        av, bv = a.get(dim), b.get(dim)
        if av is None or bv is None:
            return False
        if direction > 0:
            if av < bv:
                return False
            better = better or av > bv
        else:
            if av > bv:
                return False
            better = better or av < bv
    return better


def pareto(arms: dict[str, dict], dims: dict[str, int]) -> list[str]:
    return [name for name, arm in arms.items()
            if not any(n != name and dominates(other, arm, dims)
                       for n, other in arms.items())]


def verdict(arms: dict[str, dict], *, budget=None, criteria_version: str = "",
            dims: dict[str, int] | None = None) -> dict:
    arms = dict(arms or {})
    problems: list[str] = []
    if len(arms) < 2:
        problems.append(f"候选集不足 2（当前 {len(arms)}）")
    if not budget:
        problems.append("没有记录预算 B")
    if not (criteria_version or "").strip():
        problems.append("没有判据版本")

    if dims is None:
        dims = {"tokens": -1}
        if arms and all("chars" in a for a in arms.values()):
            dims["chars"] = 1
    usable = {k: v for k, v in dims.items()
              if arms and all(a.get(k) is not None for a in arms.values())}
    base = next(iter(arms), None)
    readings = {name: {k: arm.get(k) for k in usable} for name, arm in arms.items()}
    deltas = {name: {k: readings[name][k] - readings[base][k] for k in usable}
              for name in arms}
    out = {
        "level": "", "winner": None, "problems": problems,
        "dims": list(usable), "baseline": base, "deltas": deltas,
        "readings": readings, "budget": budget,
        "criteria_version": criteria_version, "candidates": len(arms),
    }

    failed = [name for name, arm in arms.items() if not arm.get("passed")]
    if failed:
        out["level"] = "不合格"
        out["problems"] = problems + [f"{name} 未过判据" for name in failed]
        return out
    if not usable:
        out["problems"] = problems + ["没有可比较的维度"]
    if out["problems"]:
        out["level"] = "L0"
        return out

    winners = [name for name, arm in arms.items()
               if all(other == name or dominates(arm, arms[other], usable)
                      for other in arms)]
    if winners:
        out["level"] = "L1"
        out["winner"] = winners[0]
        return out

    out["level"] = "L2"
    out["note"] = f"在预算 B={budget} 内试了 {len(arms)} 个候选，没有 L1 占优者"
    return out