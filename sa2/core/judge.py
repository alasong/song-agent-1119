"""判定权：跑判据、管登记。**生成方永远不在 authority 里。**

sa 1.0 把「造判据」和「判判据」放在同一个模块（`xm/criteria_runtime.py`）里，
两件事共用一个对象，等于把锁和钥匙拴在一起。2.0 把它拆开：
- 造判据 → `sa2/forge/criteria.py`（只能 propose，产出 Criterion）
- 判定权 → 这里（register 要 authority 里的身份，run 记录谁被执行过）

判据四种形态，全是机械可判的：
    sections  必须出现的章节行（代码围栏内不算——这就是「冒充件」的反例）
    regex     必须出现的正则
    callable  "module:function"，函数收文本返回问题列表
    exec      命令模板，"{target}" 换成临时文件名，rc=0 即通过
"""
from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("sections", "regex", "callable", "exec")


class Unauthorized(RuntimeError):
    """这次登记的身份不在 authority 里——判定权不外借。"""


class CriteriaError(RuntimeError):
    """判据本身不合格：形态不支持、没自测过、名字空。"""


@dataclass(frozen=True)
class Criterion:
    name: str
    kind: str
    spec: dict
    dims: tuple[str, ...] = ()
    self_tested: bool = False
    version: int = 1

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "spec": self.spec,
                "dims": list(self.dims), "self_tested": self.self_tested,
                "version": self.version}

    @classmethod
    def from_dict(cls, data: dict) -> "Criterion":
        return cls(name=data["name"], kind=data["kind"], spec=data.get("spec") or {},
                   dims=tuple(data.get("dims") or ()),
                   self_tested=bool(data.get("self_tested")),
                   version=int(data.get("version") or 1))


@dataclass(frozen=True)
class Verdict:
    name: str
    ok: bool
    problems: tuple[str, ...] = ()
    evidence: str = ""


class Judge:
    """判定权的持有者。authority 里放的是「谁有权登记判据」，不是「谁跑判据」。"""

    def __init__(self, authority=("leader", "verifier"), path: str | Path | None = None,
                 require_self_tested: bool = True):
        self.authority = set(authority)
        self.require_self_tested = require_self_tested
        self.path = Path(path) if path else None
        self._items: dict[str, Criterion] = {}
        self._executed: set[str] = set()
        if self.path and self.path.exists():
            self._load()

    # ── 登记（判定权的入口）──────────────────────────────────────────────
    def register(self, crit: Criterion, proposer: str = "generator") -> Criterion:
        if proposer not in self.authority:
            raise Unauthorized(f"{proposer!r} 不在判定权名单 {sorted(self.authority)} 里：生成方不能给自己发毕业证")
        if not crit.name.strip():
            raise CriteriaError("判据必须有名")
        if crit.kind not in KINDS:
            raise CriteriaError(f"判据形态 {crit.kind!r} 不在 {KINDS}")
        if self.require_self_tested and not crit.self_tested:
            raise CriteriaError(f"判据 {crit.name!r} 没跑过三反例自测，不许登记")
        self._items[crit.name] = crit
        self._persist()
        return crit

    def names(self) -> list[str]:
        return sorted(self._items)

    def get(self, name: str) -> Criterion | None:
        return self._items.get(name)

    def executed(self) -> set[str]:
        return set(self._executed)

    # ── 执行（谁都能跑，但跑了会留痕）──────────────────────────────────
    def run(self, name: str, text: str) -> Verdict:
        crit = self._items.get(name)
        if crit is None:
            return Verdict(name, False, (f"判据未登记：{name}",))
        self._executed.add(name)
        handler = getattr(self, f"_run_{crit.kind}")
        try:
            problems = handler(crit.spec, text)
        except Exception as exc:  # 判据自己坏了也算不通过，不许静默放行
            problems = [f"判据执行异常：{type(exc).__name__}: {exc}"]
        return Verdict(name, not problems, tuple(problems),
                       evidence=f"kind={crit.kind} chars={len(text)}")

    @staticmethod
    def _unfenced(text: str) -> list[str]:
        """代码围栏里的内容是「冒充件」：标题、关键词塞进围栏里都不算数。"""
        out: list[str] = []
        fence = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                fence = not fence
                continue
            if not fence:
                out.append(line)
        return out

    def _run_sections(self, spec: dict, text: str) -> list[str]:
        required = [str(s) for s in (spec.get("required") or [])]
        seen = {line.strip() for line in self._unfenced(text)}
        return [f"缺章节：{h}" for h in required if h not in seen]

    def _run_regex(self, spec: dict, text: str) -> list[str]:
        body = "\n".join(self._unfenced(text))
        literal = bool(spec.get("literal"))
        missing = []
        for pattern in spec.get("patterns") or []:
            target = re.escape(str(pattern)) if literal else str(pattern)
            if not re.search(target, body, re.M):
                missing.append(f"缺{'关键词' if literal else '正则'}：{pattern}")
        return missing

    def _run_callable(self, spec: dict, text: str) -> list[str]:
        module_name, _, func_name = str(spec.get("target", "")).partition(":")
        if not module_name or not func_name:
            return ["callable 形态要求 target 写成 module:function"]
        func = getattr(importlib.import_module(module_name), func_name)
        result = func(text)
        if isinstance(result, bool):
            return [] if result else ["callable 判定为不通过"]
        return [str(x) for x in (result or [])]

    def _run_exec(self, spec: dict, text: str) -> list[str]:
        cmd = [str(c) for c in (spec.get("cmd") or [])]
        if not cmd:
            return ["exec 形态缺少 cmd"]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.txt"
            target.write_text(text, encoding="utf-8")
            argv = [part.replace("{target}", str(target)) for part in cmd]
            proc = subprocess.run(argv, capture_output=True, text=True, cwd=tmp)
        if proc.returncode == 0:
            return []
        detail = (proc.stdout or "") + (proc.stderr or "")
        return [f"命令退出码 {proc.returncode}：{detail.strip()[:200]}"]

    # ── 持久化（判定权要能跨进程复用，但只读回放）────────────────────
    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [self._items[n].as_dict() for n in sorted(self._items)]
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        for item in json.loads(self.path.read_text(encoding="utf-8")):
            crit = Criterion.from_dict(item)
            self._items[crit.name] = crit