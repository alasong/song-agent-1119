#!/usr/bin/env python3
"""asset-index — 项目全部资产的「骨架索引 + 增量刷新」，零第三方依赖。

一套协议，所有资产同一形状（代码 / 文档 / 数据 / 文本 / 二进制 / Office）：

  1. **骨架先行**：每条资产只暴露 sections（类/函数/章节/键/列）与行区间，
     读细节时拿 `path:start-end` 喂 read 的 offset/limit，不整读。
  2. **增量刷新**：先 stat（size + mtime_ns）判脏，只对脏文件重算 sha256，
     sha 变了才重抽骨架。没变的文件一次 stat 就够。
  3. **索引只是缓存**：`.asset-index/` 可随时删掉重建，不是内容真相；
     骨架行号在读取时必须由 read 现场核对。

用法：
  asset_index.py build   [--root R]            全量重建索引
  asset_index.py refresh [--root R] [--verify-hashes]
                                               增量刷新（只重算脏文件）
  asset_index.py check   [--root R] [--verify-hashes]
                                               校验索引与磁盘一致；漂移 exit 1
  asset_index.py get PATH [--section SUB] [--json]
                                               出骨架；--section 命中则出 path:start-end
  asset_index.py stats   [--root R]            索引规模读数（json）

退出码：0 成功/一致，1 漂移或未命中，2 用法错，3 索引缺失。
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = 1
GENERATOR = "asset-index/1"
INDEX_DIR = ".asset-index"
INDEX_FILE = "index.jsonl"
META_FILE = "meta.json"

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".asset-index", ".DS_Store",
}
MAX_HASH_BYTES = 8 * 1024 * 1024   # 超过只记 size/mtime，不记 sha（check 会报 unverified）
THIN_BYTES = 4096                  # ≤ 此值不落 sections：现算比查索引快（见 docs/ASSET-INDEX.md §3）
OUTLINE = Path.home() / ".dsh" / "bin" / "outline"
CHUNK_LINES = 200                  # 无结构文本的兜底分块

CODE_EXT = {
    ".py": "python", ".pyi": "python",
    ".ts": "js", ".tsx": "js", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".go": "go", ".rs": "rust",
    ".java": "jvm", ".kt": "jvm", ".scala": "jvm", ".cs": "jvm",
    ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c", ".hpp": "c",
    ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".lua": "lua",
}
DOC_EXT = {".md", ".markdown", ".rst", ".adoc"}
DATA_EXT = {".json", ".jsonl", ".ndjson", ".csv", ".tsv",
            ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"}
OFFICE_EXT = {".docx", ".pptx", ".xlsx", ".pdf"}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tgz", ".bz2", ".xz", ".7z", ".dmg", ".so", ".dylib", ".dll", ".exe",
    ".bin", ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov", ".wav",
}

CODE_PATTERNS = {
    "js": re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
                     r"(?:function|class|interface|type|enum|const|let|var)\s+([\w$]+)"),
    "go": re.compile(r"^(?:func|type)\s+\(?[^)]*\)?\s*([\w]+)"),
    "rust": re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
                       r"(?:fn|struct|enum|impl|trait|mod)\s+([\w]+)"),
    "jvm": re.compile(r"^\s*(?:public|private|protected|static|final|abstract|\s)*"
                      r"(?:class|interface|enum|record)\s+(\w+)"),
    "c": re.compile(r"^(?:static\s+|inline\s+|extern\s+)*[\w:*&<>\s]+\s(\w+)\s*\([^;]*$"),
    "ruby": re.compile(r"^(?:def|class|module)\s+([\w:.!?]+)"),
    "php": re.compile(r"^(?:public\s+|private\s+|protected\s+|static\s+)*"
                      r"(?:function|class)\s+(\w+)"),
    "swift": re.compile(r"^(?:public\s+|private\s+|internal\s+|open\s+|static\s+)*"
                        r"(?:func|class|struct|enum|protocol)\s+(\w+)"),
    "shell": re.compile(r"^(?:function\s+)?([\w.-]+)\s*\(\)\s*\{"),
    "lua": re.compile(r"^(?:local\s+)?function\s+([\w.:]+)"),
}
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


# ---------------------------------------------------------------- 文件发现

def walk_assets(root: Path) -> list[Path]:
    """确定性顺序（sorted）列出所有资产文件，跳过缓存/版本库目录。

    用 os.scandir 的 dirent 判类型：`Path.is_file()` 每个文件多两次 stat，
    237 个文件实测 10.0ms → 3ms 级，这一步是每次读都付的固定成本。
    """
    out: list[Path] = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = os.scandir(d)
        except OSError:
            continue
        with entries:
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name in SKIP_DIRS or e.name.startswith(".asset-index"):
                            continue
                        stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False):
                        out.append(Path(e.path))
                except OSError:
                    continue
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())


def classify(path: Path, head: bytes) -> tuple[str, str]:
    """(kind, adapter)。kind 是资产类别，adapter 是抽取器名字。"""
    ext = path.suffix.lower()
    if ext in CODE_EXT:
        lang = CODE_EXT[ext]
        return "code", ("python_ast" if lang == "python" else f"code_regex:{lang}")
    if ext in DOC_EXT:
        return ("doc", "markdown") if ext in {".md", ".markdown"} else ("doc", "text_chunks")
    if ext in DATA_EXT:
        if ext in {".csv", ".tsv"}:
            return "data", "csv_table"
        if ext == ".json":
            return "data", "json_keys"
        if ext in {".jsonl", ".ndjson"}:
            return "data", "jsonl_keys"
        return "data", "config_keys"
    if ext in OFFICE_EXT:
        return "office", "defer_outline"
    if ext in BINARY_EXT or b"\x00" in head:
        return "binary", "binary_summary"
    return "text", "text_chunks"


# ---------------------------------------------------------------- 抽取器

def _clip(lines: list[str], start: int, end: int) -> tuple[int, int]:
    return max(1, start), min(len(lines), end)


def _markdown_sections(lines: list[str]) -> list[dict]:
    heads: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines, start=1):
        m = HEADING.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    out = []
    for idx, (start, level, title) in enumerate(heads):
        end = len(lines)
        for later, later_level, _ in heads[idx + 1:]:
            if later_level <= level:
                end = later - 1
                break
        s, e = _clip(lines, start, end)
        out.append({"label": title, "kind": f"h{level}", "start": s, "end": e})
    return out


def _python_sections(text: str, lines: list[str]) -> tuple[list[dict], str | None]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return [], f"parse-error: {type(exc).__name__}"
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            found.append({"label": node.name, "kind": kind,
                          "start": node.lineno,
                          "end": getattr(node, "end_lineno", node.lineno) or node.lineno})
    found.sort(key=lambda s: (s["start"], s["end"]))
    return found, None


def _regex_sections(lines: list[str], lang: str) -> list[dict]:
    pat = CODE_PATTERNS.get(lang)
    if not pat:
        return []
    hits = [(i, m.group(1)) for i, line in enumerate(lines, start=1)
            if (m := pat.match(line))]
    out = []
    for idx, (start, name) in enumerate(hits):
        end = hits[idx + 1][0] - 1 if idx + 1 < len(hits) else len(lines)
        s, e = _clip(lines, start, end)
        out.append({"label": name, "kind": "symbol", "start": s, "end": e})
    return out


def _json_sections(text: str, lines: list[str]) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return _chunks(lines)
    if not isinstance(data, dict):
        return []
    keys = list(data.keys())
    key_set = set(keys)
    cand: list[tuple[int, int, str]] = []   # (行号, 缩进, key)
    for i, line in enumerate(lines, start=1):
        m = re.match(r'^(\s*)"((?:[^"\\]|\\.)*)"\s*:', line)
        if m and m.group(2) in key_set:
            cand.append((i, len(m.group(1)), m.group(2)))
    if not cand:
        return []
    min_indent = min(c[1] for c in cand)
    top = [(i, k) for i, ind, k in cand if ind == min_indent]
    out = []
    for idx, (start, key) in enumerate(top):
        end = top[idx + 1][0] - 1 if idx + 1 < len(top) else len(lines)
        s, e = _clip(lines, start, end)
        out.append({"label": key, "kind": "key", "start": s, "end": e})
    return out


def _config_sections(text: str, lines: list[str]) -> list[dict]:
    pat = re.compile(r"^([A-Za-z_][\w.-]*)\s*[:=]")
    hits = [(i, m.group(1)) for i, line in enumerate(lines, start=1)
            if (m := pat.match(line))]
    out = []
    for idx, (start, key) in enumerate(hits):
        end = hits[idx + 1][0] - 1 if idx + 1 < len(hits) else len(lines)
        s, e = _clip(lines, start, end)
        out.append({"label": key, "kind": "key", "start": s, "end": e})
    return out


def _csv_sections(text: str) -> list[dict]:
    try:
        row = next(csv.reader(io.StringIO(text)))
    except (StopIteration, csv.Error):
        return []
    return [{"label": col, "kind": "column", "start": None, "end": None} for col in row]


def _jsonl_sections(text: str) -> list[dict]:
    """并集键：只取首行会把后面新出现的字段藏掉（实测 JSONL 的 b/c 永远不可见）。"""
    keys: list[str] = []
    for line in text.splitlines()[:200]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            for k in obj:
                if k not in keys:
                    keys.append(k)
    return [{"label": k, "kind": "field", "start": None, "end": None} for k in keys]


def _chunks(lines: list[str]) -> list[dict]:
    out = []
    for start in range(1, len(lines) + 1, CHUNK_LINES):
        end = min(len(lines), start + CHUNK_LINES - 1)
        out.append({"label": f"L{start}-{end}", "kind": "chunk", "start": start, "end": end})
    return out


def _outline_sections(path: Path) -> dict:
    """Office/PDF 的骨架交给 outline（复用既有抽取器，不在这里重写一遍）。"""
    if not OUTLINE.is_file():
        return {"sections": [], "note": "office: outline 不存在，无法出骨架"}
    try:
        proc = subprocess.run([sys.executable, str(OUTLINE), str(path), "--json"],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"sections": [], "note": f"office: outline 调用失败 {type(exc).__name__}"}
    if proc.returncode != 0:
        return {"sections": [], "note": f"office: outline rc={proc.returncode} "
                                        f"{proc.stderr.strip()[:80]}"}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"sections": [], "note": "office: outline 输出非 JSON"}
    secs = [{"label": seg.get("name", "?"),
             "kind": f"level{seg.get('level', 1)}",
             "start": seg.get("start"), "end": seg.get("end")}
            for seg in data.get("segments", [])]
    return {"sections": secs, "note": f"office via outline unit={data.get('unit')}"}


def extract(path: Path, kind: str, adapter: str, size: int) -> dict:
    """只读这一次文件，返回 {lines, sections, note?, sha256}。"""
    rec: dict = {"lines": None, "sections": [], "note": None}
    if size > MAX_HASH_BYTES:
        rec["note"] = "too-large-for-sha"
    else:
        raw = path.read_bytes()
        rec["sha256"] = hashlib.sha256(raw).hexdigest()
    if adapter == "binary_summary":
        return rec
    if adapter == "defer_outline":
        rec.update(_outline_sections(path))
        return rec
    if size > MAX_HASH_BYTES:
        return rec          # 大文本不整读；check 会报 unverified
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    rec["lines"] = len(lines)
    if adapter == "python_ast":
        rec["sections"], err = _python_sections(text, lines)
        if err:
            rec["note"] = err
    elif adapter.startswith("code_regex:"):
        rec["sections"] = _regex_sections(lines, adapter.split(":", 1)[1])
    elif adapter == "markdown":
        rec["sections"] = _markdown_sections(lines)
    elif adapter == "json_keys":
        rec["sections"] = _json_sections(text, lines)
    elif adapter == "jsonl_keys":
        rec["sections"] = _jsonl_sections(text)
    elif adapter == "config_keys":
        rec["sections"] = _config_sections(text, lines)
    elif adapter == "csv_table":
        rec["sections"] = _csv_sections(text)
    else:
        rec["sections"] = _chunks(lines)
    return rec


def make_record(root: Path, path: Path, rel: str | None = None,
                thin: bool = True) -> dict:
    st = path.stat()
    head = b""
    try:
        with path.open("rb") as fh:
            head = fh.read(4096)
    except OSError:
        pass
    kind, adapter = classify(path, head)
    rec = extract(path, kind, adapter, st.st_size)
    if thin and st.st_size <= THIN_BYTES and rec["sections"]:
        rec["sections"] = []
        rec["note"] = "thin:on-demand"
    return {
        "path": rel or path.relative_to(root).as_posix(),
        "kind": kind,
        "adapter": adapter,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sha256": rec.get("sha256"),
        "lines": rec["lines"],
        "sections": rec["sections"],
        "note": rec["note"],
    }


# ---------------------------------------------------------------- 索引读写

def index_dir(root: Path) -> Path:
    return root / INDEX_DIR


def load_index(root: Path) -> dict[str, dict]:
    f = index_dir(root) / INDEX_FILE
    if not f.is_file():
        die(f"索引不存在：{f}（先跑 build）", 3)
    out: dict[str, dict] = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["path"]] = rec
    return out


def load_meta(root: Path) -> dict:
    f = index_dir(root) / META_FILE
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def save_index(root: Path, records: list[dict], root_label: str) -> None:
    d = index_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True)
                        for r in records) + "\n"
    tmp = d / f"{INDEX_FILE}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(tmp, d / INDEX_FILE)
    finally:
        tmp.unlink(missing_ok=True)
    meta = {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "root": root_label,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "count": len(records),
    }
    (d / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")


def rel_of(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


# ---------------------------------------------------------------- 命令

def cmd_build(args) -> int:
    root = Path(args.root).resolve()
    t0 = time.perf_counter()
    records = [make_record(root, p) for p in walk_assets(root)]
    save_index(root, records, root.as_posix())
    dt = (time.perf_counter() - t0) * 1000
    print(json.dumps({"built": len(records), "elapsed_ms": round(dt, 1)},
                     ensure_ascii=False))
    return 0


def _hash_file(p: Path) -> str | None:
    try:
        if p.stat().st_size > MAX_HASH_BYTES:
            return None
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def cmd_refresh(args) -> int:
    root = Path(args.root).resolve()
    t0 = time.perf_counter()
    old = load_index(root)
    disk = {rel_of(root, p): p for p in walk_assets(root)}
    stats = {"scanned": len(disk), "unchanged": 0, "hashed": 0,
             "rebuilt": 0, "added": 0, "removed": 0, "dirty_meta_only": 0}
    records: list[dict] = []
    for rel in sorted(set(old) | set(disk)):
        p = disk.get(rel)
        prev = old.get(rel)
        if p is None:
            stats["removed"] += 1
            continue
        if prev is None:
            records.append(make_record(root, p))
            stats["added"] += 1
            continue
        st = p.stat()
        same_meta = (st.st_size == prev["size"] and st.st_mtime_ns == prev["mtime_ns"])
        if same_meta and not args.verify_hashes:
            records.append(prev)
            stats["unchanged"] += 1
            continue
        digest = _hash_file(p)
        stats["hashed"] += 1
        if digest is not None and digest == prev.get("sha256") and not args.verify_hashes:
            kept = dict(prev, size=st.st_size, mtime_ns=st.st_mtime_ns)
            records.append(kept)
            stats["dirty_meta_only"] += 1
            continue
        records.append(make_record(root, p))
        stats["rebuilt"] += 1
    stats["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if any(stats[k] for k in ("rebuilt", "added", "removed", "dirty_meta_only", "hashed")):
        save_index(root, records, root.as_posix())
    print(json.dumps(stats, ensure_ascii=False))
    return 0


def cmd_check(args) -> int:
    root = Path(args.root).resolve()
    idx = load_index(root)
    disk = {rel_of(root, p): p for p in walk_assets(root)}
    problems: list[str] = []
    for rel in sorted(idx):
        if rel not in disk:
            problems.append(f"missing-on-disk  {rel}")
    for rel in sorted(disk):
        if rel not in idx:
            problems.append(f"new-on-disk      {rel}")
            continue
        st = disk[rel].stat()
        rec = idx[rel]
        if st.st_size != rec["size"] or st.st_mtime_ns != rec["mtime_ns"]:
            problems.append(f"meta-changed     {rel}")
            continue
        if args.verify_hashes:
            digest = _hash_file(disk[rel])
            if digest is None:
                problems.append(f"unverified       {rel}")
            elif digest != rec.get("sha256"):
                problems.append(f"content-changed  {rel}")
    if problems:
        for line in problems:
            print(line)
        drift = [x for x in problems if not x.startswith("unverified")]
        unverified = len(problems) - len(drift)
        print(json.dumps({"drift": len(drift), "unverified": unverified},
                         ensure_ascii=False))
        if drift:
            return 1
        if unverified and not args.allow_unverified:
            return 4       # 验不了 ≠ 漂移：分开退出码，CI 才能对两类分别处置
        return 0
    print(json.dumps({"drift": 0, "unverified": 0, "count": len(idx)},
                     ensure_ascii=False))
    return 0


def _discover_root(target: str) -> Path:
    """从目标文件往上找 `.asset-index/index.jsonl`，让工具在任何 cwd 都能用。"""
    base = Path(target).resolve()
    start = base if base.is_dir() else base.parent
    for cand in [start, *start.parents][:12]:
        if (cand / INDEX_DIR / INDEX_FILE).is_file():
            return cand
    return Path.cwd()


def _resolve_target(root: Path, arg: str) -> Path:
    """相对路径先按 cwd 解，再按 root 解——子目录里 `get x.py` 不能变成「未登记」。"""
    p = Path(arg)
    if p.is_absolute():
        return p
    cwd_hit = Path.cwd() / p
    if cwd_hit.exists():
        return cwd_hit
    return root / p


def _rel_for(root: Path, target: Path) -> str | None:
    try:
        return target.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def _fmt_section(rel: str, sec: dict) -> str:
    if sec.get("start") is None:
        return f"{rel}  [{sec['kind']}] {sec['label']}  (无行区间，按标签定位)"
    return f"{rel}:{sec['start']}-{sec['end']}  [{sec['kind']}] {sec['label']}"


def cmd_get(args) -> int:
    root = Path(args.root).resolve() if args.root else _discover_root(args.path)
    target = _resolve_target(root, args.path)
    rel = _rel_for(root, target) or Path(args.path).as_posix()
    has_index = (index_dir(root) / INDEX_FILE).is_file()

    if not target.is_file():
        idx = load_index(root) if has_index else {}
        if rel in idx:
            print(f"文件已删除，索引里还有旧记录：{rel}（跑 refresh 清理）", file=sys.stderr)
        else:
            print(f"不存在且未登记：{rel}", file=sys.stderr)
        return 3

    st = target.stat()
    if st.st_size <= THIN_BYTES:
        # 小文件：不加载整张索引，直接现算——这是「骨架无条件」的实际含义
        rec, mode = make_record(root, target, rel, thin=False), "direct-thin"
    else:
        idx = load_index(root) if has_index else {}
        rec = idx.get(rel)
        if rec is None:
            rec, mode = make_record(root, target, rel, thin=False), "direct-unindexed"
        elif st.st_size != rec["size"] or st.st_mtime_ns != rec["mtime_ns"]:
            rec, mode = make_record(root, target, rel, thin=False), "direct-stale"
        else:
            mode = "index"
    if mode != "index":
        print(f"[{mode}] 索引未覆盖/已过期，已现场抽取（跑 refresh 落盘）", file=sys.stderr)

    if args.section:
        needle = args.section.lower()
        hits = [x for x in rec["sections"] if needle in x["label"].lower()]
        if not hits:
            print(f"未命中：{rel} 里没有 label 含 {args.section!r} 的 section",
                  file=sys.stderr)
            return 1
        if len(hits) > 1 and not args.first:
            for x in hits:
                print(_fmt_section(rel, x))
            print(f"多命中 {len(hits)} 个 section（{rel}）：加 --first 取第一个，或换关键词",
                  file=sys.stderr)
            return 1
        sec = hits[0]
        if args.json:
            print(json.dumps({"path": rel, "source_mode": mode, **sec},
                             ensure_ascii=False))
        else:
            print(_fmt_section(rel, sec))
        return 0
    if args.json:
        print(json.dumps({**rec, "source_mode": mode}, ensure_ascii=False, indent=1))
        return 0
    print(f"{rel}  kind={rec['kind']} adapter={rec['adapter']} "
          f"size={rec['size']} lines={rec['lines']}")
    if rec.get("note"):
        print(f"note: {rec['note']}")
    for sec in rec["sections"]:
        rng = f"L{sec['start']}-{sec['end']}" if sec["start"] is not None else "-"
        print(f"  {rng:<14} {sec['kind']:<8} {sec['label']}")
    return 0


def cmd_stats(args) -> int:
    root = Path(args.root).resolve()
    idx = load_index(root)
    by_kind: dict[str, int] = {}
    bytes_by_kind: dict[str, int] = {}
    sections = 0
    for rec in idx.values():
        by_kind[rec["kind"]] = by_kind.get(rec["kind"], 0) + 1
        bytes_by_kind[rec["kind"]] = bytes_by_kind.get(rec["kind"], 0) + rec["size"]
        sections += len(rec["sections"])
    f = index_dir(root) / INDEX_FILE
    out = {
        "assets": len(idx),
        "total_bytes": sum(bytes_by_kind.values()),
        "index_bytes": f.stat().st_size if f.is_file() else 0,
        "sections": sections,
        "by_kind": by_kind,
        "bytes_by_kind": bytes_by_kind,
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def die(msg: str, code: int) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="全资产骨架索引 + 增量刷新")
    p.add_argument("--root", default=".", help="项目根目录（默认当前目录）")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="全量重建")
    b.add_argument("--root", default=".")
    b.set_defaults(fn=cmd_build)

    r = sub.add_parser("refresh", help="增量刷新")
    r.add_argument("--root", default=".")
    r.add_argument("--verify-hashes", action="store_true",
                   help="连 mtime/size 未变的文件也重算 sha（慢，查被保留 mtime 的改动）")
    r.set_defaults(fn=cmd_refresh)

    c = sub.add_parser("check", help="校验索引与磁盘一致")
    c.add_argument("--root", default=".")
    c.add_argument("--verify-hashes", action="store_true")
    c.add_argument("--allow-unverified", action="store_true",
                   help="只有验不了（如 >8MB 无 sha）时也返回 0")
    c.set_defaults(fn=cmd_check)

    g = sub.add_parser("get", help="出骨架 / 定位一节")
    g.add_argument("path")
    g.add_argument("--root", default=None)
    g.add_argument("--section", default=None)
    g.add_argument("--first", action="store_true",
                   help="多命中时取第一个（默认报歧义并 exit 1）")
    g.add_argument("--json", action="store_true")
    g.set_defaults(fn=cmd_get)

    s = sub.add_parser("stats", help="索引规模读数")
    s.add_argument("--root", default=".")
    s.set_defaults(fn=cmd_stats)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())