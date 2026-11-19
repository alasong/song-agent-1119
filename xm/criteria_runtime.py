"""判据运行时：把「文字判据」变成可执行检查，并且**生成方无权注册或修改**。

这是 G3 的核心机制：判据一旦由生成方掌握，验收就退化成自我评价。
三种可执行形式：
- exec   ：跑一条命令，rc=0 即通过
- regex  ：对给定文本匹配正则
- callable：解析 "module:function" 并调用，返回真即通过
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

KINDS = {"exec", "regex", "callable"}
OWNER = "criteria_owner"


class CriteriaError(RuntimeError):
    """判据操作非法：越权、格式错、不存在。"""


@dataclass(frozen=True)
class Criterion:
    name: str
    version: int
    kind: str
    spec: dict
    author: str


class CriteriaRuntime:
    def __init__(self, path: str | Path | None = None, writer: str = "generator"):
        self.writer = writer
        self._items: dict[str, Criterion] = {}
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            self._load()

    # ---------- 存储 ----------
    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                self._items[d["name"]] = Criterion(**d)

    def _append(self, crit: Criterion) -> None:
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(crit), ensure_ascii=False) + "\n")

    # ---------- 注册 ----------
    def register(self, name: str, kind: str, spec: dict, author: str = "human") -> Criterion:
        if self.writer != OWNER:
            raise CriteriaError(f"writer={self.writer} 无权注册判据——生成方不能给自己定验收")
        if kind not in KINDS:
            raise CriteriaError(f"未知判据类型：{kind}")
        if not spec:
            raise CriteriaError("判据必须给出可执行的 spec")
        version = 1
        if name in self._items:
            raise CriteriaError(f"判据已存在：{name}，改判据请用 revise")
        crit = Criterion(name, version, kind, spec, author)
        self._items[name] = crit
        self._append(crit)
        return crit

    def revise(self, name: str, spec: dict, author: str = "human") -> Criterion:
        if self.writer != OWNER:
            raise CriteriaError("只有判据 owner 能修订判据")
        old = self.get(name)
        crit = Criterion(name, old.version + 1, old.kind, spec, author)
        self._items[name] = crit
        self._append(crit)
        return crit

    def get(self, name: str) -> Criterion:
        if name not in self._items:
            raise CriteriaError(f"未注册判据：{name}")
        return self._items[name]

    def digest(self, name: str) -> str:
        crit = self.get(name)
        return hashlib.sha256(
            json.dumps(asdict(crit), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    # ---------- 执行 ----------
    def check(self, name: str, payload: dict | None = None) -> dict:
        crit = self.get(name)
        payload = payload or {}
        try:
            if crit.kind == "exec":
                proc = subprocess.run(crit.spec["cmd"], cwd=payload.get("cwd"),
                                      capture_output=True, text=True)
                return {"ok": proc.returncode == 0, "detail": (proc.stderr or proc.stdout)[-400:]}
            if crit.kind == "regex":
                text = payload.get("text", "")
                return {"ok": re.search(crit.spec["pattern"], text) is not None, "detail": ""}
            if crit.kind == "callable":
                module, _, func = crit.spec["target"].partition(":")
                fn = getattr(importlib.import_module(module), func)
                return {"ok": bool(fn(payload)), "detail": ""}
        except Exception as exc:  # 判据自己坏了，也要如实报错，不能静默通过
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        raise CriteriaError(f"未知判据类型：{crit.kind}")