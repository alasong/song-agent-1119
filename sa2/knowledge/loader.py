"""知识面：世界知识从文件来，不从代码来。

为什么要有这一层：源、词表、编号形态、阈值这些**这个世界长什么样**的东西，原来散在
`fetch.py` 的常量、`dims.py` 的字典、`evidence.py` 的正则里。每加一个源、每换个编号体系，
都要改 `.py`——知识唯一的进入通道成了「人改代码」，于是每次事故都会被写成一处补丁。

三条硬规则（都是踩过坑才写下来的）：
1. **缺文件、缺键、未知键 ⇒ 当场抛**。配置文件最贵的失败不是崩，是静默落回默认值：
   `thresholds.json` 写错一个键，系统会一声不响地用常量跑下去。
2. **schema 版本必须认识**，不认识就拒载。老格式被新代码读成默认值，比崩更难查。
3. **只解析一次并缓存**。加载发生在进程启动，不在每次派活的路上；测试用 `reload()`。

边界（必须留在代码里）：解析器与判定权。数据只能说「用哪个解析器」「按哪条正则」，
不能自己长出解析逻辑，也不能自己决定谁有判定权。
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).with_name("data")
SCHEMA = 1

# 每份文件允许的顶层键：写错一个键就抛，不静默忽略。加字段必须先进这张表。
_ALLOWED = {
    "sources": {"schema", "sources"},
    "vocab": {"schema", "dims", "kinds", "capabilities", "hand_capabilities", "events"},
    "formats": {"schema", "marker", "reference_ids"},
    "thresholds": {"schema", "values"},
    "classify": {"schema", "failure_patterns"},
}

# 每份文件必填的键
_REQUIRED = {
    "sources": {"schema", "sources"},
    "vocab": {"schema", "dims", "kinds", "capabilities", "hand_capabilities", "events"},
    "formats": {"schema", "marker", "reference_ids"},
    "thresholds": {"schema", "values"},
    "classify": {"schema", "failure_patterns"},
}

_CACHE: dict[str, dict] = {}


class KnowledgeError(RuntimeError):
    """知识加载失败：缺文件、缺键、未知键、版本不认识、值不合规。"""


def _fail(name: str, why: str) -> None:
    raise KnowledgeError(f"知识文件 {name}.json 不合格：{why}")


def _validate_sources(name: str, data: dict) -> None:
    sources = data.get("sources")
    if not isinstance(sources, dict) or not sources:
        _fail(name, "sources 必须是非空对象")
    need = {"host", "url", "query_style", "parser", "capability"}
    for key, cfg in sources.items():
        if not isinstance(cfg, dict):
            _fail(name, f"源 {key} 必须是对象")
        missing = need - set(cfg)
        if missing:
            _fail(name, f"源 {key} 缺字段 {sorted(missing)}")
        extra = set(cfg) - need - {"label", "fallback", "fields"}
        if extra:
            _fail(name, f"源 {key} 有未登记字段 {sorted(extra)}")
        if not str(cfg["url"]).startswith("https://"):
            _fail(name, f"源 {key} 的 url 必须是 https")
        if cfg["host"] not in str(cfg["url"]):
            _fail(name, f"源 {key} 的 host={cfg['host']!r} 不在 url 里——白名单会对不上")
        if cfg["query_style"] not in ("field-prefixed", "plain"):
            _fail(name, f"源 {key} 的 query_style={cfg['query_style']!r} 只能是 "
                        f"field-prefixed / plain")
        if "{q}" not in str(cfg["url"]) or "{n}" not in str(cfg["url"]):
            _fail(name, f"源 {key} 的 url 必须含 {{q}} 与 {{n}} 两个占位符")
        if cfg["parser"] == "json_api":
            fields = cfg.get("fields")
            if not isinstance(fields, dict) or not fields.get("title"):
                _fail(name, f"源 {key} 用的是 json_api，必须给 fields 映射（至少含 title）")
            unknown_field = set(fields) - {"items", "id", "title", "published", "url", "summary"}
            if unknown_field:
                _fail(name, f"源 {key} 的 fields 有未登记字段 {sorted(unknown_field)}")


def _validate_vocab(name: str, data: dict) -> None:
    if not isinstance(data.get("dims"), dict) or not data["dims"]:
        _fail(name, "dims 必须是非空对象")
    for key in ("kinds", "capabilities", "hand_capabilities"):
        if not isinstance(data.get(key), list) or not data[key]:
            _fail(name, f"{key} 必须是非空数组")
    unknown_hand = set(data["hand_capabilities"]) - set(data["capabilities"])
    if unknown_hand:
        _fail(name, f"hand_capabilities 里有未登记的能力 {sorted(unknown_hand)}")
    events = data.get("events")
    if not isinstance(events, dict) or not events:
        _fail(name, "events must be a non-empty object")
    for key, values in events.items():
        if not isinstance(values, list) or not values:
            _fail(name, f"events.{key} 必须是非空数组")


def _validate_formats(name: str, data: dict) -> None:
    if not isinstance(data.get("marker"), str) or not data["marker"].strip():
        _fail(name, "marker 必须是非空正则字符串")
    refs = data.get("reference_ids")
    if not isinstance(refs, list) or not refs:
        _fail(name, "reference_ids 必须是非空数组")
    for item in refs:
        if not isinstance(item, dict) or not {"name", "pattern"} <= set(item):
            _fail(name, "reference_ids 的每一项都要有 name 与 pattern")
        try:
            import re
            compiled = re.compile(item["pattern"])
        except re.error as exc:
            _fail(name, f"reference_ids.{item.get('name')} 正则编不过：{exc}")
        if compiled.groups < 1:
            _fail(name, f"reference_ids.{item.get('name')} 至少要有一个捕获组")


def _validate_thresholds(name: str, data: dict) -> None:
    values = data.get("values")
    if not isinstance(values, dict) or not values:
        _fail(name, "values 必须是非空对象")
    for key, item in values.items():
        if not isinstance(item, dict) or "value" not in item:
            _fail(name, f"阈值 {key} 必须是对象且含 value")
        if not isinstance(item["value"], (int, float)) or isinstance(item["value"], bool):
            _fail(name, f"阈值 {key} 的 value 必须是数")
        # 出处不许省：这个数是从哪次实测来的，比数本身更值钱
        for need in ("source", "date"):
            if not str(item.get(need) or "").strip():
                _fail(name, f"阈值 {key} 缺 {need}：没有出处就不知道哪天该改它")


def _validate_classify(name: str, data: dict) -> None:
    rules = data.get("failure_patterns")
    if not isinstance(rules, list) or not rules:
        _fail(name, "failure_patterns 必须是非空数组")
    kinds = load("vocab")["events"]["failure_kind"]
    for rule in rules:
        if not isinstance(rule, dict) or {"kind", "pattern"} - set(rule):
            _fail(name, "failure_patterns 每项都要有 kind 与 pattern")
        if rule["kind"] not in kinds:
            _fail(name, f"failure_patterns 用了未登记的 failure_kind：{rule['kind']!r}")


_VALIDATORS = {
    "sources": _validate_sources,
    "vocab": _validate_vocab,
    "formats": _validate_formats,
    "thresholds": _validate_thresholds,
    "classify": _validate_classify,
}


def load(name: str) -> dict:
    """读一份知识文件：校验 schema、缺键、未知键、值域，然后缓存。"""
    if name in _CACHE:
        return _CACHE[name]
    if name not in _ALLOWED:
        raise KnowledgeError(f"没有这份知识：{name}（已登记 {sorted(_ALLOWED)}）")
    path = DATA / f"{name}.json"
    if not path.is_file():
        raise KnowledgeError(f"缺知识文件：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KnowledgeError(f"知识文件 {name}.json 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        _fail(name, "顶层必须是对象")
    if data.get("schema") != SCHEMA:
        raise KnowledgeError(f"知识文件 {name}.json 的 schema={data.get('schema')!r}，"
                             f"本代码只认识 {SCHEMA}")
    missing = _REQUIRED[name] - set(data)
    if missing:
        _fail(name, f"缺字段 {sorted(missing)}")
    unknown = set(data) - _ALLOWED[name]
    if unknown:
        _fail(name, f"有未登记字段 {sorted(unknown)}——写错的键不许被静默忽略")
    _VALIDATORS[name](name, data)
    _CACHE[name] = data
    return data


def text(rel: str) -> str:
    """读一段随知识分发的文本（提示词片段）。缺文件照样抛。"""
    path = DATA / rel
    if not path.is_file():
        raise KnowledgeError(f"缺知识文本：{path}")
    return path.read_text(encoding="utf-8")


def reload() -> None:
    """清缓存：测试与「热改数据文件」时用。"""
    _CACHE.clear()