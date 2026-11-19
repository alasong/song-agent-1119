"""知识获取：从公开论文源取材料（只取公开元数据，不碰付费库）。

只做两件事：请求 + 解析。是否入库由 KnowledgeBase 决定（它只收带证据的事实）。
"""
from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_API = "http://export.arxiv.org/api/query"


@dataclass(frozen=True)
class Paper:
    title: str
    summary: str
    url: str
    published: str


def parse_atom(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        summary = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
        url = (entry.findtext(f"{ATOM}id") or "").strip()
        published = (entry.findtext(f"{ATOM}published") or "").strip()
        if title and url:
            papers.append(Paper(title, summary, url, published))
    return papers


def fetch_arxiv(query: str, max_results: int = 3, timeout: int = 20) -> list[Paper]:
    url = ARXIV_API + "?" + urllib.parse.urlencode(
        {"search_query": query, "start": 0, "max_results": max_results}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "sa-research/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_atom(resp.read().decode("utf-8", "ignore"))