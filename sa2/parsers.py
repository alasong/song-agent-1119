"""抓回来的文本 → 同形状条目。**协议在代码，站点在数据。**

为什么解析器必须留在代码里：`sources.json` 只说「用哪个解析器」。让数据去描述任意解析
等于在 JSON 里写解释器——那是把机制伪装成配置。真实边界是：
- 同一个协议换个站点（两个 Atom 源、两个 JSON API）→ 只改 `sources.json`；
- 换一种协议（XML → JSON → RSS → HTML）→ 加一个解析函数。

注册表按**名字**查，不做 importlib 自动发现：靠反射猜约定已经在判据那层猜过一次
（`judge._run_callable` 用 `inspect.signature` 猜参数个数），不再重复。
"""
from __future__ import annotations

import json
import re


class ParseError(RuntimeError):
    """取回的文本解析不出条目：要么接口变了，要么查询真的没人答。不许降级成空列表。"""


def parse_arxiv_atom(text: str) -> list[dict]:
    """Atom feed → 条目。取不到 entry 就是失败，不是「零结果」。"""
    entries: list[dict] = []
    for block in re.findall(r"<entry>(.*?)</entry>", text or "", re.S):
        def pick(tag: str) -> str:
            found = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
            return " ".join(found.group(1).split()) if found else ""

        link = re.search(r'<link[^>]+href="([^"]+)"', block)
        entries.append({
            "id": pick("id").rsplit("/", 1)[-1],
            "title": pick("title"),
            "published": pick("published")[:10],
            "summary": pick("summary"),
            "url": link.group(1) if link else pick("id"),
        })
    if not entries:
        raise ParseError("feed 里没有 entry：要么查询没人答，要么接口变了")
    return entries


def parse_hn_json(text: str) -> list[dict]:
    """Hacker News（Algolia）JSON → 条目。没有外链就指回讨论页。"""
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ParseError(f"HN 返回的不是 JSON：{exc}") from exc
    entries: list[dict] = []
    for hit in data.get("hits") or []:
        title = " ".join(str(hit.get("title") or "").split())
        if not title:
            continue
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        summary = " ".join(str(hit.get("story_text") or title).split())[:600]
        entries.append({
            "id": f"hn-{hit.get('objectID')}",
            "title": title,
            "published": str(hit.get("created_at") or "")[:10],
            "summary": summary,
            "url": link,
        })
    if not entries:
        raise ParseError("HN 没有命中：要么查询没人答，要么接口变了")
    return entries


def _dig(payload, path: str):
    """按点路径取字段：`message.items`、`title.0`、`created.date-parts.0.0`。

    列表用数字下标。取不到返回空串——条目缺字段是常态，不该让整批失败。
    """
    cur = payload
    for part in str(path or "").split("."):
        if cur is None:
            return ""
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return ""
        elif isinstance(cur, dict):
            cur = cur.get(part, "")
        else:
            return ""
    return cur


def _flat(value, limit: int = 600) -> str:
    if isinstance(value, list):
        value = " ".join(str(x) for x in value)
    return " ".join(str(value or "").split())[:limit]


def parse_json_api(text: str, spec: dict | None = None) -> list[dict]:
    """通用 JSON API：字段路径写在 `sources.json` 里，解析器本身不认识任何站点。

    这是「同协议换站点只改数据」的承载点：换成 Crossref 只需一行 mapping，
    不用再写一个 `parse_crossref`。
    """
    fields = dict((spec or {}).get("fields") or {})
    if not fields.get("items") and not fields.get("title"):
        raise ParseError("json_api 缺字段映射：spec.fields 里没有 items/title")
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ParseError(f"返回的不是 JSON：{exc}") from exc
    raw_items = _dig(data, fields["items"]) if fields.get("items") else data
    if not isinstance(raw_items, list):
        raw_items = []
    entries: list[dict] = []
    for item in raw_items:
        title = _flat(_dig(item, fields.get("title", "title")))
        if not title:
            continue
        ident = _flat(_dig(item, fields.get("id", "id")), 120)
        url = _flat(_dig(item, fields.get("url", "url")), 300) or ident
        entries.append({
            "id": ident or title,
            "title": title,
            "published": _flat(_dig(item, fields.get("published", "published")), 20),
            "summary": _flat(_dig(item, fields.get("summary", "summary"))) or title,
            "url": url,
        })
    if not entries:
        raise ParseError("接口里没有可用条目：要么查询没人答，要么字段路径不对")
    return entries


PARSERS = {"arxiv_atom": parse_arxiv_atom, "hn_json": parse_hn_json,
           "json_api": parse_json_api}
# 需要 spec（字段映射）的解析器：显式列出来，不靠数参数个数猜
_NEEDS_SPEC = {"json_api"}


def names() -> list[str]:
    return sorted(PARSERS)


def parse(name: str, text: str, spec: dict | None = None) -> list[dict]:
    """按名字取解析器。名字必须是登记过的——拼错当场报，不许静默落空。"""
    func = PARSERS.get(str(name))
    if func is None:
        raise ParseError(f"没有这个解析器：{name!r}（已登记 {names()}）")
    return func(text, spec) if name in _NEEDS_SPEC else func(text)