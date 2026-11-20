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


PARSERS = {"arxiv_atom": parse_arxiv_atom, "hn_json": parse_hn_json}


def names() -> list[str]:
    return sorted(PARSERS)


def parse(name: str, text: str) -> list[dict]:
    """按名字取解析器。名字必须是登记过的——拼错当场报，不许静默落空。"""
    func = PARSERS.get(str(name))
    if func is None:
        raise ParseError(f"没有这个解析器：{name!r}（已登记 {names()}）")
    return func(text)