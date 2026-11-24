"""依赖断言：开工前必须回答「这一步依赖什么、质量如何」。

一条依赖只有写成可证伪的一句话才算被想过：

    claim      断言：要带可观察结果（数、路径、命令、rc）
    verify     验法：cmd: / path: / value: / read: 前缀，决定谁来验
    if_false   若假怎么办：换用 / 造工具 / 降级

空清单不许开工——这是「每一步都做依赖优化」的物理形态：不写，就进不去门。
一级类词表在 `knowledge/data/deps.json`，集合由 loader 固定（新增一类要人审）；
本模块只做「写成什么样才算想过」的机械校验，不判依赖够不够。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..knowledge import load

VERIFY_KINDS = ("cmd", "path", "value", "read")
MIN_CLAIM = 8


class DepError(RuntimeError):
    """断言单不合格：形状不对，不是内容好坏。"""


@dataclass(frozen=True)
class Assertion:
    name: str
    cls: str
    claim: str
    verify: str
    if_false: str


@dataclass(frozen=True)
class DepNote:
    step: str
    items: tuple[Assertion, ...]
    gaps: tuple[str, ...] = ()


def classes() -> tuple[str, ...]:
    """一级类，按数据文件里的顺序。"""
    return tuple(load("deps")["classes"])


def parse(data: dict) -> DepNote:
    """从模型输出或调用方给的 dict 解析断言单；形状不对就抛。"""
    if not isinstance(data, dict):
        raise DepError("断言单必须是对象")
    raw = data.get("items")
    if not isinstance(raw, list):
        raise DepError("断言单缺 items 数组")
    items: list[Assertion] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise DepError(f"第 {i} 条依赖必须是对象")
        missing = {"name", "cls", "claim", "verify", "if_false"} - set(item)
        if missing:
            raise DepError(f"第 {i} 条依赖缺字段 {sorted(missing)}")
        items.append(Assertion(**{
            key: str(item[key]).strip()
            for key in ("name", "cls", "claim", "verify", "if_false")
        }))
    gaps = data.get("gaps") or []
    if not isinstance(gaps, list):
        raise DepError("gaps 必须是数组")
    return DepNote(str(data.get("step") or "").strip(), tuple(items),
                   tuple(str(g).strip() for g in gaps))


def check(note: DepNote) -> list[str]:
    """返回问题列表；空列表才算「这一步想过依赖了」。"""
    problems: list[str] = []
    if not note.step.strip():
        problems.append("断言单缺步骤名：不知道该给哪一步用")
    if not note.items:
        problems.append("这一步没有登记任何依赖：等于没想过依赖，不许开工")
    known = classes()
    seen: set[str] = set()
    for item in note.items:
        if not item.name:
            problems.append("依赖缺名字")
        elif item.name in seen:
            problems.append(f"依赖重名：{item.name}")
        seen.add(item.name)
        if item.cls not in known:
            problems.append(f"依赖 {item.name or '?'} 的类 {item.cls!r} 不在 {list(known)}")
        if len(item.claim) < MIN_CLAIM:
            problems.append(f"依赖 {item.name or '?'} 的断言太短：要写出可观察结果（≥{MIN_CLAIM} 字）")
        kind, sep, body = item.verify.partition(":")
        if not sep or kind not in VERIFY_KINDS or not body.strip():
            problems.append(f"依赖 {item.name or '?'} 的验法要写成 "
                            f"{'/'.join(k + '：' for k in VERIFY_KINDS)} 前缀")
        if not item.if_false:
            problems.append(f"依赖 {item.name or '?'} 没写「若假怎么办」")
    for gap in note.gaps:
        if gap not in seen:
            problems.append(f"缺口 {gap!r} 没有对应的依赖条目")
    return problems


def acyclic(edges) -> list[str]:
    """依赖图找环；返回一条环路径（首尾同点），空列表表示无环。"""
    graph: dict[str, list[str]] = {}
    for left, right in edges:
        graph.setdefault(left, []).append(right)
        graph.setdefault(right, [])
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> list[str]:
        state[node] = 1
        path.append(node)
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                return path[path.index(nxt):] + [nxt]
            if state.get(nxt, 0) == 0:
                found = visit(nxt)
                if found:
                    return found
        state[node] = 2
        path.pop()
        return []

    for node in list(graph):
        if state.get(node, 0) == 0:
            found = visit(node)
            if found:
                return found
    return []


def depth_ok(depth: int) -> dict:
    """深度上限：超过 go_depth_max 的层必须人确认，不许自己往下拆。"""
    limit = int(config.get("go_depth_max"))
    if depth <= limit:
        return {"ok": True, "limit": limit}
    return {"ok": False, "limit": limit,
            "why": f"深度 {depth} 超过上限 {limit}：第 {limit + 1} 层起必须人确认"}


def missed(note: DepNote, problems) -> list[str]:
    """结果门红了：问题里没点到的依赖，算漏报——断言没覆盖到真正出错的地方。"""
    text = "；".join(str(p) for p in (problems or ()))
    return [item.name for item in note.items if item.name not in text]


def dispatch(item: Assertion, *, verifier=None, ledger=None, stage="") -> dict:
    """三档验证：cmd/path 自验；method 交独立验证方；其余挂起。

    返回 {"status": "verified"|"falsified"|"pending", ...}。
    pending 不等于通过——调用方不许拿它当就绪。
    给了 ledger 就把验真/证伪记账，指标才数得出来。
    """
    result = _check(item, verifier)
    if ledger is not None and result["status"] in ("verified", "falsified"):
        ledger.append("claim_verified" if result["status"] == "verified" else "claim_falsified",
                      "deps", {"stage": stage, "name": item.name, "cls": item.cls,
                               "verify_kind": result.get("kind", ""),
                               "detail": result.get("detail", "")[:120]})
    return result


def _check(item: Assertion, verifier) -> dict:
    kind, _, body = item.verify.partition(":")
    body = body.strip()
    if kind == "cmd":
        try:
            proc = subprocess.run(body, shell=True, capture_output=True, text=True,
                                  timeout=config.get("tool_timeout"))
        except subprocess.TimeoutExpired:
            return {"status": "falsified", "kind": kind, "detail": "验证命令超时"}
        ok = proc.returncode == 0
        detail = (proc.stdout or proc.stderr or "").strip()[:120]
        return {"status": "verified" if ok else "falsified",
                "kind": kind, "detail": detail}
    if kind == "path":
        ok = Path(body).expanduser().exists()
        return {"status": "verified" if ok else "falsified",
                "kind": kind, "detail": body}
    if item.cls == "method":
        if verifier is None:
            return {"status": "pending", "kind": kind,
                    "why": "方法质量要独立验证方，不能自验"}
        ok = bool(verifier(item))
        return {"status": "verified" if ok else "falsified", "kind": "verifier"}
    return {"status": "pending", "kind": kind,
            "why": f"{kind} 型断言还没有对应的验证器"}