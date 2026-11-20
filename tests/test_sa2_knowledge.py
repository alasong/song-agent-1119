"""知识面契约：世界知识是数据，机制是代码。

覆盖四块：装载器（load / text / reload / 坏数据校验）、解析器注册表、
数据驱动（fetch / config）、经验（check_when / add / all / match）。
所有写操作只落 tempfile.TemporaryDirectory()，不碰仓库 data 目录，不碰网络。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2 import config, fetch, parsers
from sa2.knowledge import KnowledgeError, load, reload, text
from sa2.knowledge import loader as knowledge_loader
from sa2.memory import lessons

ATOM = """<?xml version="1.0"?><feed>
<entry>
  <id>http://arxiv.org/abs/2611.00001v1</id>
  <published>2026-11-18T00:00:00Z</published>
  <title>Piccolo: Co-Evolving Decision Models</title>
  <summary>We study recursive self improvement.</summary>
  <link href="http://arxiv.org/abs/2611.00001v1"/>
</entry>
</feed>"""

HN = json.dumps({
    "hits": [
        {
            "objectID": "42001",
            "title": "Show HN: A knowledge layer",
            "url": "https://example.org/knowledge",
            "created_at": "2026-11-18T10:00:00Z",
            "story_text": "Data is knowledge, code is mechanism.",
        }
    ]
}, ensure_ascii=False)


class LoaderContractTest(unittest.TestCase):
    """A1、A2、A4：真实 data 目录上的装载契约。"""

    def tearDown(self):
        reload()   # 本类缓存的真实知识不让下一个测试继承

    def test_load_sources_has_schema_and_sources(self):
        data = load("sources")
        self.assertEqual(data["schema"], 1)
        self.assertIsInstance(data["sources"], dict)
        self.assertTrue(data["sources"])

    def test_reload_clears_cache_and_rereads(self):
        first = load("sources")
        reload()
        second = load("sources")
        self.assertEqual(first, second)
        self.assertIsNot(first, second)   # 新对象 = 真的重读了文件，不是命中缓存

    def test_unknown_name_lists_registered_names(self):
        with self.assertRaises(KnowledgeError) as ctx:
            load("不存在的名字")
        message = str(ctx.exception)
        for name in ("sources", "vocab", "formats", "thresholds"):
            self.assertIn(name, message)

    def test_prompt_text_contains_goal(self):
        body = text("prompts/check_tool.md")
        self.assertTrue(body.strip())
        self.assertIn("{goal}", body)

    def test_missing_prompt_text_raises(self):
        with self.assertRaises(KnowledgeError):
            text("prompts/nothing.md")


class LoaderValidationTest(unittest.TestCase):
    """A3：坏数据必须抛 KnowledgeError——patch loader.DATA 到临时目录。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        # 把一份真实知识文件复制成临时文件，再在副本上造坏数据
        shutil.copy(knowledge_loader.DATA / "sources.json",
                    self.data / "sources.json")
        self._patch = mock.patch.object(knowledge_loader, "DATA", self.data)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        reload()
        # LIFO：先清缓存，再恢复 DATA，最后删临时目录
        self.addCleanup(reload)

    def _payload(self) -> dict:
        return json.loads((self.data / "sources.json").read_text(encoding="utf-8"))

    def _rewrite(self, payload: dict) -> None:
        (self.data / "sources.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        reload()

    def test_copy_without_change_still_loads(self):
        # 对照组：证明下面三条红是坏数据引起的，不是临时路径读不到
        self.assertEqual(load("sources")["schema"], 1)

    def test_wrong_schema_raises(self):
        payload = self._payload()
        payload["schema"] = 2
        self._rewrite(payload)
        with self.assertRaisesRegex(KnowledgeError, "schema"):
            load("sources")

    def test_unregistered_field_raises(self):
        payload = self._payload()
        payload["mood"] = "angry"
        self._rewrite(payload)
        with self.assertRaisesRegex(KnowledgeError, "未登记"):
            load("sources")

    def test_missing_required_field_raises(self):
        payload = self._payload()
        payload.pop("sources")
        self._rewrite(payload)
        with self.assertRaisesRegex(KnowledgeError, "缺字段"):
            load("sources")


class ParserContractTest(unittest.TestCase):
    """B5–B7：解析协议在代码，站点在数据。"""

    def test_arxiv_atom_entry_has_core_fields(self):
        entry = parsers.parse("arxiv_atom", ATOM)[0]
        self.assertEqual(entry["id"], "2611.00001v1")
        self.assertIn("Piccolo", entry["title"])
        self.assertEqual(entry["published"], "2026-11-18")
        self.assertEqual(entry["url"], "http://arxiv.org/abs/2611.00001v1")

    def test_empty_atom_feed_raises(self):
        with self.assertRaises(parsers.ParseError):
            parsers.parse("arxiv_atom", "<feed></feed>")

    def test_hn_entry_has_core_fields(self):
        entry = parsers.parse("hn_json", HN)[0]
        self.assertEqual(entry["id"], "hn-42001")
        self.assertIn("knowledge layer", entry["title"])
        self.assertEqual(entry["published"], "2026-11-18")
        self.assertEqual(entry["url"], "https://example.org/knowledge")

    def test_empty_hn_hits_raises(self):
        with self.assertRaises(parsers.ParseError):
            parsers.parse("hn_json", json.dumps({"hits": []}))

    def test_unknown_parser_lists_registered_names(self):
        with self.assertRaises(parsers.ParseError) as ctx:
            parsers.parse("不存在的解析器", "x")
        message = str(ctx.exception)
        for name in parsers.names():
            self.assertIn(name, message)

    def test_names_contains_both_parsers(self):
        names = parsers.names()
        self.assertIn("arxiv_atom", names)
        self.assertIn("hn_json", names)
        self.assertEqual(names, sorted(names))


class DataDrivenContractTest(unittest.TestCase):
    """C8、C10：读取路径由数据决定。"""

    def tearDown(self):
        reload()

    def test_source_names_match_sources_json(self):
        self.assertEqual(fetch.source_names(), sorted(load("sources")["sources"]))

    def test_hn_config_points_at_hn_parser(self):
        self.assertEqual(fetch.config("hn")["parser"], "hn_json")

    def test_provenance_and_get_agree(self):
        provenance = config.provenance("single_floor")
        self.assertIn("source", provenance)
        self.assertIn("date", provenance)
        with mock.patch.dict(os.environ):
            os.environ.pop("XM_SA2_SINGLE_FLOOR", None)   # 环境变量优先，别让它插手
            self.assertEqual(
                config.get("single_floor"),
                load("thresholds")["values"]["single_floor"]["value"])


class AddSourceByDataOnlyTest(unittest.TestCase):
    """C9：只写一份 sources.json 就多一个源——「加源只改数据」的可执行证明。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        payload = {
            "schema": 1,
            "sources": {
                "fake": {
                    "label": "虚构源",
                    "host": "example.org",
                    "url": "https://example.org/search?q={q}&n={n}",
                    "query_style": "plain",
                    "parser": "arxiv_atom",   # 用已登记的解析器，不新增任何 .py
                    "capability": "fetch",
                }
            },
        }
        (self.data / "sources.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._patch = mock.patch.object(knowledge_loader, "DATA", self.data)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        reload()
        self.addCleanup(reload)

    def test_fake_source_is_fetchable_without_touching_code(self):
        self.assertEqual(fetch.source_names(), ["fake"])
        self.assertEqual(fetch.config("fake")["parser"], "arxiv_atom")
        url = fetch.query_url("x", 3, "fake")
        self.assertEqual(url, "https://example.org/search?q=x&n=3")
        self.assertIn("n=3", url)


class LessonContractTest(unittest.TestCase):
    """D11：when 的键与值只能是 vocab.json 里登记过的枚举。"""

    def test_registered_when_passes(self):
        when = {"failure_kind": "zero_hit"}
        self.assertEqual(lessons.check_when(when), when)

    def test_unregistered_key_raises(self):
        with self.assertRaises(lessons.LessonError):
            lessons.check_when({"mood": "angry"})

    def test_unregistered_value_raises(self):
        with self.assertRaises(lessons.LessonError):
            lessons.check_when({"failure_kind": "生气"})

    def test_empty_when_raises(self):
        with self.assertRaises(lessons.LessonError):
            lessons.check_when({})


class LessonStoreContractTest(unittest.TestCase):
    """D12：写进临时 jsonl → all 读回 → match 命中；retired 不参与。"""

    def test_add_all_match_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lessons.jsonl"
            lesson = lessons.add(
                path, "零命中时先换查询词", {"failure_kind": "zero_hit"},
                fix="换更宽的查询", origin="测试")
            self.assertEqual(lesson["stats"], {"injected": 0, "ok": 0, "bad": 0})
            stored = lessons.all(path)
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["text"], "零命中时先换查询词")
            self.assertEqual(stored[0]["when"], {"failure_kind": "zero_hit"})
            self.assertEqual(
                [item["id"] for item in
                 lessons.match(stored, {"failure_kind": "zero_hit"})],
                [lesson["id"]])
            self.assertEqual(
                lessons.match(stored, {"failure_kind": "empty_output"}), [])

    def test_retired_lesson_is_not_matched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lessons.jsonl"
            lesson = lessons.add(path, "这条已退役", {"failure_kind": "zero_hit"})
            retired = dict(lesson, id="Lretired", status="retired")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(retired, ensure_ascii=False) + "\n")
            hits = lessons.match(lessons.all(path), {"failure_kind": "zero_hit"})
            self.assertEqual([item["id"] for item in hits], [lesson["id"]])


if __name__ == "__main__":
    unittest.main()