"""知识文件是判定边界：写错一个键必须当场抛，不许静默落回默认值。

`test_sa2_knowledge.BadDataTest` 只盖了 schema / 未登记 / 缺字段三条通用规则；
这里按每份文件的校验器逐条打——源字段规则、词表、编号正则、阈值出处、
失败分类、依赖一级类，以及 load() 自己的读文件失败分支。

做法：把 DATA 指到临时目录并整份复制真文件（先证明副本能加载），
再逐项改坏一份、断言 KnowledgeError 的措辞。
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sa2.knowledge import KnowledgeError, load, reload
from sa2.knowledge import loader as knowledge_loader

FILES = ("sources", "vocab", "formats", "thresholds", "classify", "deps")


class KnowledgeRejectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        real = knowledge_loader.DATA          # patch 之前先记住真目录
        self._patch = mock.patch.object(knowledge_loader, "DATA", self.data)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(reload)
        for name in FILES:
            shutil.copy(real / f"{name}.json", self.data / f"{name}.json")
        self.base = {name: json.loads((self.data / f"{name}.json").read_text(encoding="utf-8"))
                     for name in FILES}
        reload()

    # -- 工具 -------------------------------------------------------------
    def _payload(self, name: str) -> dict:
        return json.loads(json.dumps(self.base[name]))   # 深拷贝：改坏不污染下一条

    def _write(self, name: str, payload) -> None:
        (self.data / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        reload()

    def _raw(self, name: str, text: str) -> None:
        (self.data / f"{name}.json").write_text(text, encoding="utf-8")
        reload()

    def _reject(self, name: str, payload, pattern: str) -> None:
        self._write(name, payload)
        with self.assertRaisesRegex(KnowledgeError, pattern):
            load(name)

    # -- 对照组：副本本身是合法的 -----------------------------------------
    def test_copied_files_all_load(self):
        for name in FILES:
            self.assertEqual(load(name)["schema"], 1, name)

    # -- load() 的读文件失败 ----------------------------------------------
    def test_unknown_knowledge_name(self):
        with self.assertRaisesRegex(KnowledgeError, "没有这份知识"):
            load("nope")

    def test_missing_file(self):
        (self.data / "sources.json").unlink()
        with self.assertRaisesRegex(KnowledgeError, "缺知识文件"):
            load("sources")

    def test_invalid_json(self):
        self._raw("sources", "{不是 JSON")
        with self.assertRaisesRegex(KnowledgeError, "不是合法 JSON"):
            load("sources")

    def test_top_level_must_be_object(self):
        self._raw("sources", "[]")
        with self.assertRaisesRegex(KnowledgeError, "顶层必须是对象"):
            load("sources")

    # -- sources ----------------------------------------------------------
    def test_sources_must_be_non_empty_object(self):
        payload = self._payload("sources")
        payload["sources"] = {}
        self._reject("sources", payload, "sources 必须是非空对象")

    def test_source_entry_must_be_object(self):
        payload = self._payload("sources")
        payload["sources"]["arxiv"] = 1
        self._reject("sources", payload, "必须是对象")

    def test_source_missing_field(self):
        payload = self._payload("sources")
        payload["sources"]["arxiv"].pop("host")
        self._reject("sources", payload, "缺字段")

    def test_source_unregistered_field(self):
        payload = self._payload("sources")
        payload["sources"]["arxiv"]["mood"] = "angry"
        self._reject("sources", payload, "未登记字段")

    def test_source_url_must_be_https(self):
        payload = self._payload("sources")
        payload["sources"]["arxiv"]["url"] = "http://export.arxiv.org/api?q={q}&n={n}"
        self._reject("sources", payload, "url 必须是 https")

    def test_source_host_must_appear_in_url(self):
        payload = self._payload("sources")
        payload["sources"]["arxiv"]["url"] = "https://other.org/api?q={q}&n={n}"
        self._reject("sources", payload, "不在 url 里")

    def test_source_query_style_is_closed_set(self):
        payload = self._payload("sources")
        payload["sources"]["arxiv"]["query_style"] = "fuzzy"
        self._reject("sources", payload, "query_style")

    def test_source_url_needs_both_placeholders(self):
        payload = self._payload("sources")
        payload["sources"]["arxiv"]["url"] = "https://export.arxiv.org/api?q={q}"
        self._reject("sources", payload, "占位符")

    def test_json_api_source_needs_fields(self):
        payload = self._payload("sources")
        payload["sources"]["crossref"].pop("fields")
        self._reject("sources", payload, "fields 映射")

    def test_json_api_source_fields_are_registered(self):
        payload = self._payload("sources")
        payload["sources"]["crossref"]["fields"]["mood"] = "angry"
        self._reject("sources", payload, "未登记字段")

    # -- vocab ------------------------------------------------------------
    def test_dims_must_be_non_empty_object(self):
        payload = self._payload("vocab")
        payload["dims"] = {}
        self._reject("vocab", payload, "dims 必须是非空对象")

    def test_kinds_must_be_non_empty_list(self):
        payload = self._payload("vocab")
        payload["kinds"] = []
        self._reject("vocab", payload, "kinds 必须是非空数组")

    def test_hand_capability_must_be_registered(self):
        payload = self._payload("vocab")
        payload["hand_capabilities"] = ["fetch", "teleport"]
        self._reject("vocab", payload, "未登记的能力")

    def test_events_must_be_non_empty_object(self):
        payload = self._payload("vocab")
        payload["events"] = {}
        self._reject("vocab", payload, "events")

    def test_event_values_must_be_non_empty_list(self):
        payload = self._payload("vocab")
        payload["events"]["stage_kind"] = []
        self._reject("vocab", payload, "events.stage_kind 必须是非空数组")

    # -- formats ----------------------------------------------------------
    def test_marker_must_be_non_empty_string(self):
        payload = self._payload("formats")
        payload["marker"] = ""
        self._reject("formats", payload, "marker")

    def test_reference_ids_must_be_non_empty_list(self):
        payload = self._payload("formats")
        payload["reference_ids"] = []
        self._reject("formats", payload, "reference_ids 必须是非空数组")

    def test_reference_item_needs_name_and_pattern(self):
        payload = self._payload("formats")
        payload["reference_ids"][0].pop("pattern")
        self._reject("formats", payload, "name 与 pattern")

    def test_reference_pattern_must_compile(self):
        payload = self._payload("formats")
        payload["reference_ids"][0]["pattern"] = "(未闭合"
        self._reject("formats", payload, "正则编不过")

    def test_reference_pattern_needs_capture_group(self):
        payload = self._payload("formats")
        payload["reference_ids"][0]["pattern"] = r"\d{4}"
        self._reject("formats", payload, "至少要有一个捕获组")

    # -- thresholds -------------------------------------------------------
    def test_threshold_values_must_be_non_empty_object(self):
        payload = self._payload("thresholds")
        payload["values"] = {}
        self._reject("thresholds", payload, "values 必须是非空对象")

    def test_threshold_item_needs_value(self):
        payload = self._payload("thresholds")
        payload["values"]["single_floor"] = {"source": "x", "date": "2026-11-19"}
        self._reject("thresholds", payload, "必须是对象且含 value")

    def test_threshold_value_must_be_number(self):
        payload = self._payload("thresholds")
        payload["values"]["single_floor"]["value"] = "20000"
        self._reject("thresholds", payload, "value 必须是数")

    def test_bool_is_not_a_threshold_number(self):
        payload = self._payload("thresholds")
        payload["values"]["single_floor"]["value"] = True
        self._reject("thresholds", payload, "value 必须是数")

    def test_threshold_needs_provenance(self):
        payload = self._payload("thresholds")
        payload["values"]["single_floor"].pop("source")
        self._reject("thresholds", payload, "缺 source")

    def test_threshold_needs_date(self):
        payload = self._payload("thresholds")
        payload["values"]["single_floor"]["date"] = " "
        self._reject("thresholds", payload, "缺 date")

    # -- classify ---------------------------------------------------------
    def test_failure_patterns_must_be_non_empty_list(self):
        payload = self._payload("classify")
        payload["failure_patterns"] = []
        self._reject("classify", payload, "failure_patterns 必须是非空数组")

    def test_failure_rule_needs_kind_and_pattern(self):
        payload = self._payload("classify")
        payload["failure_patterns"][0].pop("kind")
        self._reject("classify", payload, "kind 与 pattern")

    def test_failure_kind_must_be_registered(self):
        payload = self._payload("classify")
        payload["failure_patterns"][0]["kind"] = "teleport"
        self._reject("classify", payload, "未登记的 failure_kind")

    # -- deps -------------------------------------------------------------
    def test_deps_classes_must_be_non_empty_object(self):
        payload = self._payload("deps")
        payload["classes"] = {}
        self._reject("deps", payload, "classes 必须是非空对象")

    def test_deps_classes_are_closed_set(self):
        payload = self._payload("deps")
        payload["classes"].pop("other")
        self._reject("deps", payload, "一级类固定为")

    def test_deps_class_entry_must_be_object(self):
        payload = self._payload("deps")
        payload["classes"]["team"] = "团队"
        self._reject("deps", payload, "必须是对象")

    def test_deps_class_missing_field(self):
        payload = self._payload("deps")
        payload["classes"]["team"].pop("why")
        self._reject("deps", payload, "缺字段")

    def test_deps_class_unregistered_field(self):
        payload = self._payload("deps")
        payload["classes"]["team"]["mood"] = "angry"
        self._reject("deps", payload, "未登记字段")

    def test_deps_class_label_must_be_non_empty(self):
        payload = self._payload("deps")
        payload["classes"]["team"]["label"] = "  "
        self._reject("deps", payload, "不能为空")

    def test_deps_sub_must_be_list(self):
        payload = self._payload("deps")
        payload["classes"]["team"]["sub"] = "组织"
        self._reject("deps", payload, "sub 必须是数组")

    def test_deps_sub_items_are_non_empty_strings(self):
        payload = self._payload("deps")
        payload["classes"]["team"]["sub"] = ["组织", "  "]
        self._reject("deps", payload, "只能是非空字符串")


if __name__ == "__main__":
    unittest.main()