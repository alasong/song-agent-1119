"""入口编排（V2）：只分发、不生产；节点短命，交接只走产物与证据。

它不是“第三个 Agent”：没有正文产出权，只产任务树、路由与装配结果。
每个节点一次执行；要返工就新起节点，复用上下文属于越界。
"""
from __future__ import annotations

from .. import config
from . import tree


class Orchestrator:
    def __init__(self, *, runner, splitter, ledger=None, expand_on_failure: bool = False):
        self.runner = runner          # runner(node) -> {"ok", "text", "evidence"}
        self.splitter = splitter      # splitter(node) -> [{"goal","dims","criteria","headings"}]
        self.ledger = ledger
        self.expand_on_failure = expand_on_failure
        self.nodes = 0

    def run(self, root: tree.Node) -> dict:
        self.nodes = 0
        problems: list[str] = []
        try:
            ok = self._walk(root, problems)
        except tree.TreeError as exc:
            self._log("tree_refused", {"reason": str(exc)})
            return {"ok": False, "nodes": self.nodes,
                    "problems": [*problems, str(exc)], "artifact": ""}
        return {"ok": bool(ok and not problems), "nodes": self.nodes,
                "problems": problems, "artifact": root.artifact}

    def _walk(self, node: tree.Node, problems: list[str]) -> bool:
        self.nodes += 1
        if self.nodes > config.get("tree_nodes_max"):
            raise tree.TreeError(
                f"节点数 {self.nodes} > 上限 {config.get('tree_nodes_max')}")
        unit, reason = tree.choose_unit(
            dims=node.dims, criteria=node.criteria, budget=node.budget,
            headings=node.headings, depth=node.depth)
        node.unit, node.reason = unit, reason
        self._log("node_started", {"id": node.id, "unit": unit, "reason": reason})

        if unit == tree.RECURSE:
            children = tree.expand(node, self.splitter(node))
            for child in children:
                self._walk(child, problems)
            text, assembly = tree.assemble(children)
            node.artifact = text
            # 证据跟着产物往上走：递归节点没有自己的取回记录，但它的证据是子节点的并集
            node.evidence = tuple(sorted({e for child in children for e in child.evidence}))
            problems.extend(f"{node.id}: {item}" for item in assembly)
            node.status = ("done" if not assembly
                           and all(child.status == "done" for child in children)
                           else "failed")
        else:
            out = self.runner(node) or {}
            node.artifact = str(out.get("text") or "")
            node.evidence = tuple(out.get("evidence") or ())
            node.status = "done" if out.get("ok") else "failed"
            if node.status == "failed" and self.expand_on_failure and not node.expanded:
                go, why = tree.should_expand(rejects=int(out.get("rejects") or 0),
                                             delivery_red=True,
                                             failure_kinds=out.get("failure_kinds") or (),
                                             depth=node.depth)
                if go:
                    try:
                        children = tree.expand(node, self.splitter(node))
                    except tree.TreeError as exc:
                        self._log("node_expand_refused", {"id": node.id, "reason": str(exc)})
                        problems.append(f"{node.id}: {exc}")
                    else:
                        node.expanded = True
                        self._log("node_expanded", {"id": node.id,
                                                    "children": len(children),
                                                    "reason": why})
                        for child in children:
                            self._walk(child, problems)
                        text, assembly = tree.assemble(children)
                        node.artifact = text
                        node.evidence = tuple(sorted({e for child in children
                                                      for e in child.evidence}))
                        problems.extend(f"{node.id}: {item}" for item in assembly)
                        node.status = ("done" if not assembly
                                       and all(child.status == "done" for child in children)
                                       else "failed")

        self._log("node_done", {"id": node.id, "status": node.status})
        return node.status == "done"

    def _log(self, kind: str, payload: dict) -> None:
        if self.ledger is not None:
            self.ledger.append(kind, "orchestrator", payload)