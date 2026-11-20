"""手：真的去取一次数据。

源从哪来：`sa2/knowledge/data/sources.json`。host、URL 模板、用哪个解析器、挂着什么能力，
全在数据里——**加一个源改数据文件，不改这个模块**。

这里只剩三件机制上的事，都不该数据化：
1. 白名单校验：host 取自配置，但「只走 https、只认白名单」这条规则不交给数据；
2. 网络层重试一次就停（4xx 与解析失败不重试——重试不会让接口变对）；
3. **失败就大声报**，不返回空列表冒充「没搜到」。

落盘打戳在 `record()`：每次取回都原样落成证据，时间锚点来自系统，不来自模型。
"""
from __future__ import annotations

import time
import urllib.parse
import urllib.request

from . import parsers
from .core.evidence import Evidence, EvidenceBook, digest_of, stamp
from .knowledge import load

MAX_RESULTS = 50
TIMEOUT = 20
RETRY_SLEEP = 2.0


class FetchError(RuntimeError):
    """取数失败。不许静默降级成空结果。"""


def source_names() -> list[str]:
    """配置里登记过的源名。宿主的工具清单也从这里派生。"""
    return sorted(load("sources")["sources"])


def config(source: str) -> dict:
    sources = load("sources")["sources"]
    if source not in sources:
        raise FetchError(f"没有这个源：{source!r}（已登记 {sorted(sources)}）")
    return sources[source]


def query_url(query: str, max_results: int = 5, source: str = "arxiv") -> str:
    cfg = config(source)
    n = max(1, min(int(max_results), MAX_RESULTS))
    return cfg["url"].format(q=urllib.parse.quote_plus((query or "").strip()), n=n)


def _check(url: str, host: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise FetchError(f"只允许 https，拿到 {parsed.scheme!r}")
    if parsed.hostname != host:
        raise FetchError(f"白名单外的 host：{parsed.hostname!r}（这条源登记的是 {host!r}）")


def _default_transport(url: str, timeout: int) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch(source: str, query: str, max_results: int = 5, *, transport=None,
          timeout: int = TIMEOUT) -> list[dict]:
    """按源取一批条目。transport 可注入，测试不碰网络。"""
    if not (query or "").strip():
        raise FetchError("查询为空")
    cfg = config(source)
    n = max(1, min(int(max_results), MAX_RESULTS))
    url = query_url(query, n, source)
    _check(url, str(cfg["host"]))
    send = transport or _default_transport
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            text = send(url, timeout)
        except Exception as exc:              # 网络层：重试一次就停
            last = exc
            if attempt == 1:
                time.sleep(RETRY_SLEEP)
                continue
            break
        try:
            entries = parsers.parse(str(cfg["parser"]), text, cfg)[:n]
        except parsers.ParseError as exc:     # 解析失败是定论，重试不会让接口变对
            raise FetchError(str(exc)) from exc
        # 每条取回的条目都带上来源：证据台账、素材块、事后核查都靠这个字段认路
        return [{**item, "source": source} for item in entries]
    raise FetchError(f"取数失败：{type(last).__name__}: {last}") from last


def arxiv(query: str, max_results: int = 5, *, transport=None,
          timeout: int = TIMEOUT) -> list[dict]:
    return fetch("arxiv", query, max_results, transport=transport, timeout=timeout)


def hn(query: str, max_results: int = 5, *, transport=None,
       timeout: int = TIMEOUT) -> list[dict]:
    return fetch("hn", query, max_results, transport=transport, timeout=timeout)


def search(source: str, query: str, n: int = 5) -> list[dict]:
    """按源取数。源名必须登记过——不许在外面现编一个。"""
    return fetch(source, query, n)


def parse_atom(text: str) -> list[dict]:
    """兼容入口：老的调用方只认 Atom。条目同时给 `id` 与 `arxiv_id`。"""
    try:
        items = parsers.parse("arxiv_atom", text)
    except parsers.ParseError as exc:
        raise FetchError(str(exc)) from exc
    return [{**item, "arxiv_id": item["id"]} for item in items]


def parse_hn(text: str) -> list[dict]:
    """兼容入口：老的调用方只认 HN JSON。条目带上来源。"""
    try:
        items = parsers.parse("hn_json", text)
    except parsers.ParseError as exc:
        raise FetchError(str(exc)) from exc
    return [{**item, "source": "hn"} for item in items]


def record(entries: list[dict], book: EvidenceBook, root, verifier: str,
           start: int = 1) -> list[Evidence]:
    """把取回条目写成证据：内容 = 标题/日期/链接/摘要，落盘并打戳。

    同一份内容只入账一次。账本按内容寻址，五个角色各取一次同一篇论文，
    不该变成 S1–S5 五条「证据」——实测真跑里 5 条证据全是同一篇（同 digest），
    于是「至少 3 条引用」那道门只靠一篇论文就过了。已有内容直接复用原 id，
    写手引 S2 与引 S1 就是同一份材料。
    """
    stamped: list[Evidence] = []
    known = {ev.digest: ev for ev in book.all()}
    for offset, item in enumerate(entries):
        content = (f"{item['title']}\n{item['published']}\n{item['url']}\n"
                   f"{item['summary']}")
        digest = digest_of(content)
        if digest in known:
            stamped.append(known[digest])
            continue
        ev = stamp(item["url"], content, verifier, f"S{start + offset}", root)
        known[digest] = book.add(ev)
        stamped.append(known[digest])
    return stamped