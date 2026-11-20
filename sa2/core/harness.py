"""M5：WorkItem 状态机 —— 一台所有活都能挂上来的 harness。

为什么要有它：一种活一个壳（PDCA 写文档、DevLoop 改代码、daemon 领队列），
加一种活就再写一个循环，组织层的流程就不可控。这里只留一台状态机：

- 控制流程 = 控制 `EDGES` 这张边表；加一种活 = `register()` 一个类型，不加壳；
- 判定权不在生成方：处理器可以声称 `passed`，账本会留痕，但状态只按
  「产物存在」与「注册时给定的校验命令」推进——校验命令来自注册方，
  不从产出里读，所以模型无法给自己判卷；
- 账本是唯一真源：`state()` 每次从事件重放，不读可变快照，进程被打死
  也能从断点续上，已走过的边不会重跑。

边界：只做流程控制，不做活的本身（写文档/改代码留给边处理器）；不接
分布式锁与并发争用，同一工单的并发推进靠调用方串行。
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ledger import Ledger

ARTIFACT = "artifact"
REASON = "reason"
VERIFY_TIMEOUT = 120


@dataclass(frozen=True)
class Edge:
    """一条迁移：谁 → 谁，要什么证据，判不判。"""

    src: str
    dst: str
    requires: tuple[str, ...] = ()
    verify: bool = False
    label: str = ""


EDGES: dict[tuple[str, str], Edge] = {
    (e.src, e.dst): e
    for e in (
        Edge("declared", "routed", label="路由"),
        Edge("routed", "running", label="开跑"),
        Edge("running", "checked", requires=(ARTIFACT,), label="交产物"),
        Edge("checked", "done", verify=True, label="判过"),
        Edge("checked", "failed", requires=(REASON,), label="判不过"),
    )
}
TERMINAL = ("done", "failed")


class HarnessRefused(RuntimeError):
    """迁移被拒：边不存在、证据不全、类型未注册、校验命令非零。"""


@dataclass
class Route:
    handler: Callable[[dict, str], dict] | None = None
    verify_cmd: str | None = None


class Harness:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.ledger = Ledger(self.root / "harness.jsonl")
        self.routes: dict[str, Route] = {}
        # 注册也进账本：重启后不用人再声明一遍，各类型的判据从历史里重放出来
        for event in self.ledger.read():
            payload = event.get("payload") or {}
            if event.get("kind") == "register":
                self.routes[payload["task_type"]] = Route(verify_cmd=payload.get("verify_cmd"))

    # -- 注册：校验命令由注册方给，不从产出里读 -------------------------
    def register(self, task_type: str, *, handler=None, verify_cmd: str | None = None) -> None:
        """登记一种活。判据一旦登记就不许悄悄换（换判据必须换类型名或新版本）。"""
        known = self.routes.get(task_type)
        if known is None:
            self.ledger.append("register", "leader",
                               {"task_type": task_type, "verify_cmd": verify_cmd})
            known = Route(verify_cmd=verify_cmd)
            self.routes[task_type] = known
        elif known.verify_cmd != verify_cmd:
            raise HarnessRefused(
                f"判据不许悄悄换：{task_type} 已登记 {known.verify_cmd!r}，"
                f"这次给 {verify_cmd!r}")
        if handler is not None:
            known.handler = handler

    # -- 写 -------------------------------------------------------------
    def declare(self, *, task_type: str, criteria, item_id: str | None = None) -> str:
        item_id = item_id or f"w-{uuid.uuid4().hex[:8]}"
        if self.item(item_id) is not None:
            raise HarnessRefused(f"工单已存在：{item_id}")
        self.ledger.append("declare", "harness", {
            "item": item_id,
            "task_type": task_type,
            "criteria": list(criteria),
        })
        return item_id

    def advance(self, item_id: str, to: str, *, artifacts: dict | None = None) -> dict:
        state = self.state(item_id)
        if state is None:
            raise HarnessRefused(f"没有这张工单：{item_id}")
        if state in TERMINAL:
            raise HarnessRefused(f"已经结项：{item_id}={state}")
        edge = EDGES.get((state, to))
        if edge is None:
            raise HarnessRefused(f"没有这条边：{state}→{to}（账本记着走过哪些边，不许跳步或重走）")

        item = self.item(item_id)
        assert item is not None
        route = self.routes.get(item["task_type"])
        arts = dict(artifacts or {})

        if (state, to) == ("declared", "routed") and route is None:
            self._reject(item_id, state, to, f"未注册的类型：{item['task_type']}")
            raise HarnessRefused(f"未注册的类型，不许路由：{item['task_type']}")

        missing = [key for key in edge.requires if not self._has(arts, key)]
        if missing:
            self._reject(item_id, state, to, f"证据不全：缺 {missing}")
            raise HarnessRefused(f"证据不全，拒绝 {state}→{to}：缺 {missing}")

        claim = None
        if route is not None and route.handler is not None:
            try:
                claim = route.handler(item, to)
            except Exception as exc:  # 处理器崩了不许静默推进
                self._reject(item_id, state, to, f"处理器异常：{exc}")
                raise HarnessRefused(f"处理器异常，拒绝推进：{exc}") from exc
            self.ledger.append("claim", item["task_type"],
                               {"item": item_id, "to": to, "claim": claim})

        verify_rc: int | None = None
        if edge.verify:
            if route is None or not route.verify_cmd:
                self._reject(item_id, state, to, f"类型没有注册校验命令：{item['task_type']}")
                raise HarnessRefused(f"类型没有注册校验命令，不许结项：{item['task_type']}")
            verify_rc = self._run_verify(item_id, route.verify_cmd)
            if verify_rc != 0:
                self._reject(item_id, state, to, f"校验命令返回非零：{verify_rc}")
                raise HarnessRefused(f"校验不过，拒绝 {state}→{to}：rc={verify_rc}")

        return self.ledger.append("advance", "harness", {
            "item": item_id,
            "from": state,
            "to": to,
            "evidence": sorted(arts),
            "verify_rc": verify_rc,
            "label": edge.label,
        })

    # -- 读：状态是账本的投影 -------------------------------------------
    def item(self, item_id: str) -> dict | None:
        for event in self.ledger.read():
            payload = event.get("payload") or {}
            if event.get("kind") == "declare" and payload.get("item") == item_id:
                return {
                    "item": item_id,
                    "task_type": payload.get("task_type"),
                    "criteria": payload.get("criteria") or [],
                }
        return None

    def state(self, item_id: str) -> str | None:
        if self.item(item_id) is None:
            return None
        state = "declared"
        for event in self.ledger.read():
            payload = event.get("payload") or {}
            if event.get("kind") == "advance" and payload.get("item") == item_id:
                state = payload.get("to")
        return state

    def history(self, item_id: str) -> list[dict]:
        return [event for event in self.ledger.read()
                if (event.get("payload") or {}).get("item") == item_id]

    def items(self) -> list[str]:
        return [event["payload"]["item"] for event in self.ledger.read()
                if event.get("kind") == "declare"]

    # -- 内部 -----------------------------------------------------------
    def _has(self, artifacts: dict, key: str) -> bool:
        if key == ARTIFACT:
            value = artifacts.get(ARTIFACT)
            if not value:
                return False
            path = Path(value)
            if not path.is_absolute():
                path = self.root / path
            return path.is_file() and path.stat().st_size > 0
        value = artifacts.get(key)
        return bool(value)

    def _run_verify(self, item_id: str, cmd: str) -> int:
        try:
            done = subprocess.run(cmd, shell=True, cwd=self.root, capture_output=True,
                                  text=True, timeout=VERIFY_TIMEOUT)
            rc = done.returncode
            tail = ((done.stdout or "") + (done.stderr or "")).strip()[-400:]
        except subprocess.TimeoutExpired:
            rc = 124
            tail = f"超时 {VERIFY_TIMEOUT}s"
        self.ledger.append("verify", "harness",
                           {"item": item_id, "cmd": cmd, "rc": rc, "tail": tail})
        return rc

    def _reject(self, item_id: str, src: str, dst: str, reason: str) -> None:
        self.ledger.append("reject", "harness",
                           {"item": item_id, "from": src, "to": dst, "reason": reason})