"""工具库：造出来的东西必须有家，否则「边干边造」就是「边干边扔」。

原状（2026-11-20 真跑实测）：生成的检查器写在 run 目录的 `tools/` 里，判据的 exec
`cmd` 指向那一串绝对路径；run 目录一清，注册表里那条判据就是一把断刀。

这里按**内容寻址**：脚本的 sha256 决定它在库里的名字。
- 同一份脚本再入库：不升版本，只记一次使用（重复造同一把刀不该算改进）；
- 同名不同内容：版本 +1，历史留一行，替换前的版本可查；
- 没有自测读数的工具不许入库——生成方不能说「我造的工具好使」。

和判据库同构（`sa2/memory/registry.py`）：有主人、有版本、有历史、有使用账。
使用账是「磨刀值不值」的唯一信号：没人用的工具应该被淘汰，而不是越攒越多。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import registry


class ToolError(RuntimeError):
    """工具库拒绝。"""


def root() -> Path:
    path = registry.root() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


class ToolStore:
    def __init__(self, path: str | Path | None = None):
        self.root = Path(path).expanduser() if path else root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.history_path = self.root / "history.jsonl"

    # ── 索引 ────────────────────────────────────────────────────────────────
    def _load(self) -> dict:
        if not self.index_path.exists():
            return {}
        return json.loads(self.index_path.read_text(encoding="utf-8") or "{}")

    def _save(self, data: dict) -> None:
        self.index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    def _history(self, line: dict) -> None:
        with self.history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), **line}, ensure_ascii=False) + "\n")

    # ── 入库 ────────────────────────────────────────────────────────────────
    def store(self, script: str | Path, name: str, owner: str,
              signature: str = "", self_test: dict | None = None,
              capability: str = "checker") -> dict:
        """把一份脚本收进库，返回登记项。

        `owner` 是登记方（不是生成方）；`self_test` 必须是真跑过的读数
        （`{"ok": True, ...}`），没有就拒——工具「好使」不能由造它的人自己说。
        `capability` 写这把刀能干什么（checker / fetch / search / ...）：
        编制校验靠它判「这个角色手上是不是真有能用的手」，而不是光看有没有挂名字。
        """
        src = Path(script).expanduser()
        if not src.is_file():
            raise ToolError(f"要入库的脚本不存在：{src}")
        if not (isinstance(self_test, dict) and self_test.get("ok")):
            raise ToolError(f"工具 {name} 没有自测通过的读数，不许入库")
        digest = _digest(src)
        target = self.root / f"{digest}.py"
        if not target.exists():
            target.write_bytes(src.read_bytes())

        data = self._load()
        old = data.get(name)
        if old and old.get("digest") == digest:
            # 同一份脚本：不升版本，记一次使用
            old["uses"] = int(old.get("uses") or 0) + 1
            old["last_used"] = _now()
            data[name] = old
            self._save(data)
            return dict(old)

        version = int(old.get("version") or 0) + 1 if old else 1
        entry = {
            "name": name, "digest": digest, "path": str(target), "signature": signature,
            "capability": capability,
            "owner": owner, "version": version, "self_test": self_test,
            "added": _now(), "uses": 0, "last_used": "",
        }
        data[name] = entry
        self._save(data)
        self._history({"action": "replaced" if old else "registered", "name": name,
                       "version": version, "digest": digest, "owner": owner,
                       "replaced_version": old.get("version") if old else None})
        return dict(entry)

    # ── 取用 ────────────────────────────────────────────────────────────────
    def get(self, name: str) -> dict:
        entry = self._load().get(name)
        if entry is None:
            raise ToolError(f"库里没有这个工具：{name}")
        return entry

    def resolve(self, name: str) -> Path:
        """拿到能直接执行的路径。登记了但文件不在，就是断刀——当场报，不许静默。"""
        entry = self.get(name)
        path = Path(entry["path"])
        if not path.is_file():
            raise ToolError(f"工具 {name} 有登记但脚本不见了（断刀）：{path}")
        return path

    def touch(self, name: str) -> dict:
        """记一次使用。使用账是淘汰的唯一依据，所以取用必须留痕。"""
        data = self._load()
        entry = self.get(name)
        entry["uses"] = int(entry.get("uses") or 0) + 1
        entry["last_used"] = _now()
        data[name] = entry
        self._save(data)
        return dict(entry)

    def of_path(self, path: str | Path) -> dict | None:
        """按脚本地址反查登记项：判据的 cmd 指向库里的哪把刀。"""
        target = str(Path(path).expanduser().resolve())
        for entry in self._load().values():
            if str(Path(entry.get("path") or "").expanduser().resolve()) == target:
                return entry
        return None

    def all(self) -> dict:
        return self._load()