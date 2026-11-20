"""S2：派活与接管。

Supervisor 把每次角色调用变成一条**持久派活记录**，并在调用抛错时把它当成一次死亡：
账本记 `role_died` → 同 kind 的同伴接 → 没有同伴就克隆档案当继任 → 仍不成则 `escalated` 并上抛。
继任者拿到的不是一句「你继续」，而是一个接管包（未偿承诺 / 已完成部分 / 上游尾部 / 失败原因）。

边界（S2 不做的事）：
- 超时与租约抢占在 S4（多 worker）；这里只接「调用直接抛错」。
- 不设常驻实例：继任 = 同一 role_id 的 generation+1 档案 + 一次新的 produce 调用。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from ..memory import registry
from ..memory.profiles import RoleProfile, RoleStore


def _tail(text: str, limit: int = 600) -> str:
    text = text or ""
    return text[-limit:]


@dataclass
class Dispatch:
    """一次派活的记录。进程死了记录还在，才谈得上被重派。"""

    id: str
    role_id: str
    stage: str
    duty: str
    criteria: str
    attempt: int
    input_ref: str
    budget: int = 0
    state: str = "leased"          # leased / done / failed
    lease_id: str = ""
    error: str = ""
    updated_at: float = 0.0


class DispatchQueue:
    """追加写的派活队列；同 id 多行以最后一行为准（状态是投影，历史不覆盖）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else registry.ensure() / "dispatches.jsonl"

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows: list[dict] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"派活记录第 {number} 行坏了：{self.path}: {exc}") from exc
        return rows

    def _write(self, dispatch: Dispatch) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = asdict(dispatch)
        row["updated_at"] = time.time()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def put(self, dispatch: Dispatch) -> None:
        self._write(dispatch)

    def finish(self, dispatch_id: str, state: str, error: str = "") -> None:
        latest = self._latest().get(dispatch_id)
        if latest is None:
            raise KeyError(dispatch_id)
        latest.state = state
        latest.error = error
        self._write(latest)

    def _latest(self) -> dict[str, Dispatch]:
        latest: dict[str, Dispatch] = {}
        for row in self._rows():
            data = {k: row[k] for k in Dispatch.__dataclass_fields__ if k in row}
            try:
                dispatch = Dispatch(**data)
            except TypeError as exc:
                raise ValueError(f"派活记录缺字段：{row!r}") from exc
            latest[dispatch.id] = dispatch
        return latest

    def all(self) -> list[Dispatch]:
        return list(self._latest().values())


class Supervisor:
    def __init__(self, produce, ledger, store: RoleStore,
                 queue: DispatchQueue | None = None, roles=(),
                 max_takeovers: int = 1):
        self.produce = produce
        self.ledger = ledger
        self.store = store
        self.queue = queue if queue is not None else DispatchQueue()
        self.roles = tuple(roles)
        self.max_takeovers = max_takeovers

    def dispatch(self, role, stage: str, upstream: str, attempt: int,
                 feedback: str = "", requirements: str = "",
                 partial: str = "", budget: int = 0) -> str:
        return self._run(role, stage, upstream, attempt, feedback, requirements,
                         partial, budget, takeovers=0)

    def _run(self, role, stage, upstream, attempt, feedback, requirements,
             partial, budget, takeovers) -> str:
        dispatch = Dispatch(
            id=f"d-{uuid.uuid4().hex[:10]}", role_id=role.name, stage=stage,
            duty=getattr(role, "duty", ""), criteria=getattr(role, "criteria", ""),
            attempt=attempt, budget=budget,
            input_ref=hashlib.sha1((upstream or "").encode("utf-8")).hexdigest()[:12],
            lease_id=f"l-{uuid.uuid4().hex[:8]}")
        self.queue.put(dispatch)

        try:
            out = self.produce(role, stage, upstream, attempt, feedback, requirements)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.ledger.append("role_died", role.name,
                               {"id": dispatch.id, "stage": stage, "error": error})
            self.queue.finish(dispatch.id, "failed", error)
            package = self._package(role, stage, upstream, partial, error)
            if takeovers >= self.max_takeovers:
                self.ledger.append("escalated", role.name,
                                   {"to": "leader", "dispatch": dispatch.id,
                                    "package": package})
                raise
            successor = self._successor(role)
            self.ledger.append("takeover", successor.name,
                               {"from": role.name, "to": successor.name,
                                "dispatch": dispatch.id, "package": package,
                                "generation": self._generation(successor)})
            return self._run(successor, stage, upstream, attempt,
                             self._handover_text(package, feedback),
                             requirements, partial, budget, takeovers + 1)

        profile = self._profile(role)
        profile.bump("done")
        self.store.save(profile)
        self.queue.finish(dispatch.id, "done")
        return out

    def _profile(self, role) -> RoleProfile:
        try:
            return self.store.get(role.name)
        except KeyError:
            profile = RoleProfile(id=role.name, kind=getattr(role, "kind", ""),
                                  duty=getattr(role, "duty", ""),
                                  tools=tuple(getattr(role, "tools", ()) or ()))
            self.store.save(profile)
            return profile

    def _successor(self, role):
        """同 kind 的同伴先上；没有同伴就同一身份第 generation+1 代。"""
        for peer in self.roles:
            if getattr(peer, "kind", "") == getattr(role, "kind", "") and peer.name != role.name:
                return peer
        profile = self._profile(role)
        profile.generation += 1
        profile.bump("takeovers")
        self.store.save(profile)
        return role

    def _generation(self, role) -> int:
        try:
            return self.store.get(role.name).generation
        except KeyError:
            return 0

    def _package(self, role, stage: str, upstream: str, partial: str, error: str) -> dict:
        package = self._profile(role).handover()
        package.update({"stage": stage, "upstream_tail": _tail(upstream),
                        "partial": partial or "", "last_error": error})
        return package

    @staticmethod
    def _handover_text(package: dict, feedback: str) -> str:
        lines = [feedback] if feedback else []
        lines.append("接管包：")
        lines.append(f"- 上一任在「{package['stage']}」失败：{package['last_error']}")
        if package.get("partial"):
            lines.append(f"- 已完成部分：{package['partial']}")
        if package.get("upstream_tail"):
            lines.append(f"- 上游尾部：{package['upstream_tail']}")
        promises = package.get("promises") or []
        if promises:
            lines.append("- 未偿承诺：" + "；".join(str(x.get("text")) for x in promises))
        return "\n".join(lines)