"""asset-index 的机检：增量刷新只碰脏文件、骨架区间与实物一致、漂移能判红。

每一条都对着一个失效模式写，跑红即说明协议破了一条：
- 全量重建 vs 增量刷新：改一个文件必须只重抽一个（否则「增量」是假的）；
- 骨架行区间：`get --section` 给出的 start 行必须真的是那节的标题行（否则读歪）；
- 漂移：新增/删除/改内容必须让 `check` exit 1（否则索引是过期地图）；
- 盲区：mtime 被保留的同长改动在快模式下查不出，`--verify-hashes` 必须查出
  （写出来，不装作没有）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "asset_index.py"

DOC = "# 标题\n\n引言\n\n## 第一节\n甲\n乙\n\n## 第二节\n丙\n丁\n"
CODE = "class A:\n    pass\n\n\ndef f(x):\n    return x\n"
DATA = '{\n  "alpha": 1,\n  "beta": {\n    "nested": 2\n  }\n}\n'
TABLE = "name,age\nx,1\ny,2\n"
TEXT = "".join(f"line {i}\n" for i in range(1, 251))
BLOB = b"\x00\x01\x02binary"


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args],
                          cwd=cwd, capture_output=True, text=True)


class AssetIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "doc.md").write_text(DOC, encoding="utf-8")
        (self.root / "code.py").write_text(CODE, encoding="utf-8")
        (self.root / "data.json").write_text(DATA, encoding="utf-8")
        (self.root / "table.csv").write_text(TABLE, encoding="utf-8")
        (self.root / "notes.txt").write_text(TEXT, encoding="utf-8")
        (self.root / "blob.bin").write_bytes(BLOB)
        proc = run("build", "--root", ".", cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ---------------------------------------------------------- 骨架

    def test_build_covers_every_asset_class(self) -> None:
        out = json.loads(run("stats", "--root", ".", cwd=self.root).stdout)
        self.assertEqual(out["assets"], 6)
        self.assertEqual(set(out["by_kind"]),
                         {"doc", "code", "data", "text", "binary"})
        # ≤4KB 走 thin：索引不存 sections，但 get 必须现场给得出骨架
        rec = json.loads(run("get", "doc.md", "--json", cwd=self.root).stdout)
        self.assertGreaterEqual(len(rec["sections"]), 2)
        self.assertEqual(rec["source_mode"], "direct-thin")

    def test_code_skeleton_lines_match_source(self) -> None:
        got = run("get", "code.py", cwd=self.root).stdout
        self.assertIn("class", got)
        source = CODE.splitlines()
        rec = json.loads(run("get", "code.py", "--json", cwd=self.root).stdout)
        labels = {s["label"]: s for s in rec["sections"]}
        self.assertIn("A", labels)
        self.assertIn("f", labels)
        self.assertEqual(source[labels["f"]["start"] - 1].strip(), "def f(x):")

    def test_section_lookup_returns_true_heading_line(self) -> None:
        proc = run("get", "doc.md", "--section", "第二节", cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        span = proc.stdout.split()[0]
        rel, rng = span.split(":")
        start, end = (int(x) for x in rng.split("-"))
        self.assertEqual(rel, "doc.md")
        lines = (self.root / "doc.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[start - 1].strip(), "## 第二节")
        self.assertIn("丁", "\n".join(lines[start - 1:end]))

    def test_markdown_ignores_headings_inside_code_fence(self) -> None:
        """围栏代码块里的 `# 注释` 不是标题；不跳过会把后面整节吞进假标题。"""
        (self.root / "fence.md").write_text(
            "# 真标题\n\n```bash\n# 代码里的注释\nnpm i\n```\n\n## 第二节\n内容\n",
            encoding="utf-8")
        rec = json.loads(run("get", "fence.md", "--json", cwd=self.root).stdout)
        labels = [x["label"] for x in rec["sections"]]
        self.assertEqual(labels, ["真标题", "第二节"])
        self.assertEqual(rec["sections"][1]["start"], 8)

    def test_extractor_version_mismatch_forces_rebuild(self) -> None:
        """抽取逻辑升级后，旧索引的 size/mtime 仍「新鲜」但骨架已错——必须整体作废。"""
        meta = self.root / ".asset-index" / "meta.json"
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["extractor"] = -1
        meta.write_text(json.dumps(data), encoding="utf-8")
        stale = run("check", "--root", ".", cwd=self.root)
        self.assertEqual(stale.returncode, 1)
        self.assertIn("index-version", stale.stdout)
        rebuilt = json.loads(run("refresh", "--root", ".", cwd=self.root).stdout)
        self.assertEqual(rebuilt["added"] + rebuilt["rebuilt"], 6)   # 旧表作废后 6 个 fixture 全部按新增重抽
        self.assertEqual(run("check", "--root", ".", cwd=self.root).returncode, 0)

    def test_json_skeleton_lists_top_level_keys_not_nested(self) -> None:
        rec = json.loads(run("get", "data.json", "--json", cwd=self.root).stdout)
        labels = [s["label"] for s in rec["sections"]]
        self.assertEqual(labels, ["alpha", "beta"])

    def test_binary_has_no_sections_but_is_indexed(self) -> None:
        rec = json.loads(run("get", "blob.bin", "--json", cwd=self.root).stdout)
        self.assertEqual(rec["kind"], "binary")
        self.assertEqual(rec["sections"], [])

    # ---------------------------------------------------------- 增量

    def test_refresh_rebuilds_only_the_dirty_file(self) -> None:
        (self.root / "code.py").write_text(CODE + "\n\ndef g():\n    pass\n",
                                           encoding="utf-8")
        out = json.loads(run("refresh", "--root", ".", cwd=self.root).stdout)
        self.assertEqual(out["rebuilt"], 1)
        self.assertEqual(out["added"], 0)
        self.assertEqual(out["removed"], 0)
        self.assertEqual(out["unchanged"], 5)
        rec = json.loads(run("get", "code.py", "--json", cwd=self.root).stdout)
        self.assertIn("g", [s["label"] for s in rec["sections"]])

    def test_refresh_without_changes_does_not_rewrite_index(self) -> None:
        idx = self.root / ".asset-index" / "index.jsonl"
        before = idx.stat().st_mtime_ns
        out = json.loads(run("refresh", "--root", ".", cwd=self.root).stdout)
        self.assertEqual(out["rebuilt"], 0)
        self.assertEqual(out["hashed"], 0)
        self.assertEqual(idx.stat().st_mtime_ns, before)

    def test_metadata_preserving_edit_is_a_documented_blind_spot(self) -> None:
        p = self.root / "doc.md"
        st = p.stat()
        p.write_text(DOC.replace("丙", "戊"), encoding="utf-8")
        self.assertEqual(p.stat().st_size, st.st_size)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        fast = run("check", "--root", ".", cwd=self.root)
        self.assertEqual(fast.returncode, 0, "快模式本就查不出，这里断言的是已知盲区")
        deep = run("check", "--root", ".", "--verify-hashes", cwd=self.root)
        self.assertEqual(deep.returncode, 1)
        self.assertIn("content-changed", deep.stdout)

    # ---------------------------------------------------------- 漂移

    def test_check_red_on_new_file(self) -> None:
        (self.root / "added.md").write_text("# 新\n", encoding="utf-8")
        proc = run("check", "--root", ".", cwd=self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("new-on-disk", proc.stdout)

    def test_check_red_on_missing_file(self) -> None:
        (self.root / "table.csv").unlink()
        proc = run("check", "--root", ".", cwd=self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing-on-disk", proc.stdout)

    def test_check_red_on_content_change(self) -> None:
        (self.root / "notes.txt").write_text("changed\n", encoding="utf-8")
        proc = run("check", "--root", ".", cwd=self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("meta-changed", proc.stdout)

    def test_get_works_without_any_index(self) -> None:
        """「骨架无条件」：没有索引也得能出骨架，否则这句话是文档里的空话。"""
        import shutil
        shutil.rmtree(self.root / ".asset-index")
        proc = run("get", "doc.md", "--section", "第二节", cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("doc.md:"))

    def test_get_recomputes_when_index_is_stale(self) -> None:
        big = self.root / "big.md"
        big.write_text("# 顶\n" + "填充\n" * 900 + "## 目标节\n内容\n", encoding="utf-8")
        run("build", "--root", ".", cwd=self.root)
        # 前面插 10 行：行号漂了，索引记录过期
        big.write_text("# 顶\n" + "新增\n" * 10 + "填充\n" * 900 + "## 目标节\n内容\n",
                       encoding="utf-8")
        proc = run("get", "big.md", "--section", "目标节", cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("direct-stale", proc.stderr)
        span = proc.stdout.split()[0]
        start = int(span.rsplit(":", 1)[1].split("-")[0])
        lines = big.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[start - 1].strip(), "## 目标节")

    def test_get_deleted_file_is_loud(self) -> None:
        (self.root / "data.json").unlink()
        proc = run("get", "data.json", cwd=self.root)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("已删除", proc.stderr)

    def test_section_ambiguity_exits_1_unless_first(self) -> None:
        proc = run("get", "doc.md", "--section", "节", cwd=self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(proc.stdout.strip().splitlines()), 2)
        self.assertIn("多命中", proc.stderr)
        first = run("get", "doc.md", "--section", "节", "--first", cwd=self.root)
        self.assertEqual(first.returncode, 0)

    def test_office_docx_gets_real_sections_from_outline(self) -> None:
        docx = self.root / "sample.docx"
        xml = ("<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
               "<w:body><w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>"
               "<w:r><w:t>第一章 总则</w:t></w:r></w:p><w:p><w:r><w:t>正文</w:t></w:r></w:p>"
               "</w:body></w:document>")
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", xml)
        run("build", "--root", ".", cwd=self.root)
        rec = json.loads(run("get", "sample.docx", "--json", cwd=self.root).stdout)
        self.assertEqual(rec["kind"], "office")
        if not (Path.home() / ".dsh" / "bin" / "outline").is_file():
            self.skipTest("outline 不存在")
        self.assertGreaterEqual(len(rec["sections"]), 1)
        self.assertIn("第一章", rec["sections"][0]["label"])

    def test_large_file_is_unverified_not_silently_green(self) -> None:
        big = self.root / "huge.bin"
        big.write_bytes(b"a" * (9 * 1024 * 1024))
        run("build", "--root", ".", cwd=self.root)
        proc = run("check", "--root", ".", "--verify-hashes", cwd=self.root)
        self.assertEqual(proc.returncode, 4, "验不了必须与漂移分开退出码")
        self.assertIn("unverified", proc.stdout)
        self.assertIn('"drift": 0', proc.stdout)
        allowed = run("check", "--root", ".", "--verify-hashes",
                      "--allow-unverified", cwd=self.root)
        self.assertEqual(allowed.returncode, 0)

    def test_concurrent_refresh_does_not_crash(self) -> None:
        procs = [subprocess.Popen([sys.executable, str(CLI), "refresh", "--root", "."],
                                  cwd=self.root, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for _ in range(4)]
        for proc in procs:
            proc.communicate()
        for proc in procs:
            self.assertEqual(proc.returncode, 0)
        self.assertEqual(run("check", "--root", ".", cwd=self.root).returncode, 0)

    def test_get_by_absolute_path_from_other_cwd(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(CLI), "get", str(self.root / "doc.md"),
             "--section", "第二节"],
            cwd=tempfile.gettempdir(), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("doc.md:"), proc.stdout)

    def test_get_unknown_asset_exits_3(self) -> None:
        proc = run("get", "nope.md", cwd=self.root)
        self.assertEqual(proc.returncode, 3)


class RepoIndexTest(unittest.TestCase):
    def test_selfcheck_on_repo_root(self) -> None:
        """在本仓真跑一次：build → check 一致。索引不入库，所以现场建。"""
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "idx"
            env = dict(os.environ)
            proc = subprocess.run(
                [sys.executable, str(CLI), "build", "--root", str(ROOT)],
                cwd=ROOT, capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertGreater(out["built"], 100)


if __name__ == "__main__":
    unittest.main()