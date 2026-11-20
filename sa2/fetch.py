"""手：真的去取一次数据。

为什么是宿主级模块而不是模型生成的工具：模型写的取数脚本没法自证——它说抓到了就是抓到了。
这里只做一件事：给查询，返回条目（编号/标题/发布日期/摘要/链接），并且**每次取回都原样
落盘、由系统打戳成证据**（`sa2/core/evidence.py`）。时间锚点因此来自系统，不来自模型。

边界（写死，不做成配置）：
- 只走 https，只允许白名单里的 host（现在只有 arXiv 的 export 域名）；
- 单次超时 20s、最多 50 条、失败重试 1 次；
- **失败就大声报错**，不返回空列表冒充「没搜到」。
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request

from .core.evidence import Evidence, EvidenceBook, digest_of, stamp

ALLOWED_HOSTS = ("export.arxiv.org",)
BASE = "https://export.arxiv.org/api/query"
MAX_RESULTS = 50
TIMEOUT = 20
RETRY_SLEEP = 2.0


class FetchError(RuntimeError):
    """取数失败。不许静默降级成空结果。"""


def _check(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise FetchError(f"只允许 https，拿到 {parsed.scheme!r}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise FetchError(f"白名单外的 host：{parsed.hostname!r}（允许 {ALLOWED_HOSTS}）")


def _default_transport(url: str, timeout: int) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def query_url(query: str, max_results: int = 5) -> str:
    return BASE + "?" + urllib.parse.urlencode({
        "search_query": query, "start": 0, "max_results": max_results,
        "sortBy": "submittedDate", "sortOrder": "descending",
    })


def parse_atom(text: str) -> list[dict]:
    """把 Atom feed 拆成条目。取不到条目就是失败，不是「零结果」。"""
    entries: list[dict] = []
    for block in re.findall(r"<entry>(.*?)</entry>", text or "", re.S):
        def pick(tag: str) -> str:
            found = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
            return " ".join(found.group(1).split()) if found else ""

        link = re.search(r'<link[^>]+href="([^"]+)"', block)
        entries.append({
            "arxiv_id": pick("id").rsplit("/", 1)[-1],
            "title": pick("title"),
            "published": pick("published")[:10],
            "summary": pick("summary"),
            "url": link.group(1) if link else pick("id"),
        })
    if not entries:
        raise FetchError("feed 里没有 entry：要么查询没人答，要么接口变了")
    return entries


def arxiv(query: str, max_results: int = 5, *, transport=None,
          timeout: int = TIMEOUT) -> list[dict]:
    """取一批条目。transport 可注入，测试不碰网络。"""
    if not (query or "").strip():
        raise FetchError("查询为空")
    n = max(1, min(int(max_results), MAX_RESULTS))
    url = query_url(query.strip(), n)
    _check(url)
    send = transport or _default_transport
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            return parse_atom(send(url, timeout))[:n]
        except FetchError:
            raise
        except Exception as exc:              # 网络层：重试一次就停
            last = exc
            if attempt == 1:
                time.sleep(RETRY_SLEEP)
    raise FetchError(f"取数失败：{type(last).__name__}: {last}") from last


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