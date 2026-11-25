"""任务树（V2）：入口只分发，节点自己决定用多大组织。

三条约束的物理形态：
- 入口不生产内容：本模块与编排器只产节点、路由与装配结果；
- 每个单位短命：节点只跑一次，返工是新起节点，不复用上下文；
- 数量不写死：上限来自 thresholds.json 的 tree_* 资源项，不是角色/阶段的公式。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config

LEAF = "leaf"        # 1 个短命 Agent
GROUP = "group"      # 3–6 角色单层 PDCA
RECURSE = "recurse"  # 继续拆成子节点


class TreeError(RuntimeError):
    """树长不成：超出深度/扇出/节点数，或装配不合契约。"""


@dataclass
class Node:
    id: str
    goal: str
    dims: tuple = ()
    criteria: tuple = ()
    budget: int = 0
    depth: int = 0
    headings: int = 0
    unit: str = ""
    reason: str = ""
    artifact: str = ""
    evidence: tuple = ()
    status: str = "pending"
    expanded: bool = False
    children: list = field(default_factory=list)

    def add(self, child: "Node") -> "Node":
        self.children.append(child)
        return child


def choose_unit(*, dims, criteria, budget, needs_hand=False, headings=0, depth=0):
    """这一格用多大组织。不按“档位”命名，只回答节点类型。"""
    if int(budget) < config.get("single_floor"):
        return LEAF, f"预算 {budget} < 单人下限 {config.get('single_floor')}"
    if int(headings) >= 3 and depth < config.get("tree_depth_max"):
        return RECURSE, f"交付结构 {headings} 节：按节拆子节点"
    if len(dims) >= config.get("team_dims") or len(criteria) >= config.get("team_criteria"):
        return GROUP, f"维度 {len(dims)} / 判据 {len(criteria)}：需要分工与独立复核"
    if needs_hand:
        return LEAF, "需要外部取数：单人挂手"
    return LEAF, "单一维度、判据不超过 2 条：单人"


def expand(node: Node, subtasks) -> list[Node]:
    """按子任务长出一层；越界直接抛，不静默截断。"""
    subs = list(subtasks or ())
    if not subs:
        raise TreeError("没有子任务：不能靠空气展开")
    if len(subs) > config.get("tree_fan_out"):
        raise TreeError(f"扇出 {len(subs)} > 上限 {config.get('tree_fan_out')}")
    if node.depth + 1 > config.get("tree_depth_max"):
        raise TreeError(f"深度 {node.depth + 1} > 上限 {config.get('tree_depth_max')}")
    reserve = int(node.budget * 0.3) if node.budget else 0
    each = (node.budget - reserve) // len(subs) if node.budget else 0
    for index, sub in enumerate(subs, 1):
        node.add(Node(id=f"{node.id}.{index}", goal=str(sub.get("goal") or node.goal),
                      dims=tuple(sub.get("dims") or ()),
                      criteria=tuple(sub.get("criteria") or ()),
                      budget=each, depth=node.depth + 1,
                      headings=int(sub.get("headings") or 0)))
    return list(node.children)


def assemble(children) -> tuple[str, list[str]]:
    """装配契约：每份都有产物与证据、标题不许重；返回 (正文, 问题)。"""
    problems: list[str] = []
    texts: list[str] = []
    seen: set[str] = set()
    for child in children:
        text = str(child.artifact or "").strip()
        if not text:
            problems.append(f"{child.id} 没有产物")
            continue
        heads = [line.strip() for line in text.splitlines()
                 if line.strip().startswith("## ")]
        dup = [head for head in heads if head in seen]
        if dup:
            problems.append(f"{child.id} 标题重复：{dup[:2]}")
        seen.update(heads)
        if not child.evidence:
            problems.append(f"{child.id} 没有证据编号")
        texts.append(text)
    return "\n\n".join(texts), problems


def should_expand(*, rejects: int, delivery_red: bool, failure_kinds=(), depth: int):
    """失败后要不要拆小：只在节点边界发生，绝不在节点内部改组。"""
    if depth >= config.get("tree_depth_max"):
        return False, "已到深度上限"
    if rejects >= 2 or delivery_red:
        kinds = set(failure_kinds or ())
        if not kinds or kinds & {"criteria_rejected", "org_rejected", "unsigned_reference"}:
            return True, "门连续拒/交付红：拆小再跑"
    return False, "未触发展开"


def should_contract(*, l2_streak: int, efficiency=None):
    """不占优或效率低就收缩，防止组织税固化。"""
    if l2_streak >= 3:
        return True, "连续 3 次没有占优者"
    if efficiency is not None and efficiency < 50:
        return True, "每千 token 产出不足 50 字"
    return False, "未触发收缩"