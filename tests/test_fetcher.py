"""解析器验收（不联网，用固定 Atom 片段）。"""
import unittest

from xm.fetcher import parse_atom

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Paper One
      Title</title>
    <summary>Abstract one.</summary>
    <id>http://arxiv.org/abs/1</id>
    <published>2026-01-01T00:00:00Z</published>
  </entry>
  <entry>
    <title>Paper Two</title>
    <summary>Abstract two.</summary>
    <id>http://arxiv.org/abs/2</id>
    <published>2026-02-02T00:00:00Z</published>
  </entry>
</feed>"""


class FetcherParseTest(unittest.TestCase):
    def test_parses_entries(self):
        papers = parse_atom(ATOM)
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0].title, "Paper One Title")
        self.assertEqual(papers[0].url, "http://arxiv.org/abs/1")
        self.assertEqual(papers[1].published, "2026-02-02T00:00:00Z")

    def test_skips_entries_without_url(self):
        broken = ATOM.replace("<id>http://arxiv.org/abs/1</id>", "")
        self.assertEqual(len(parse_atom(broken)), 1)


if __name__ == "__main__":
    unittest.main()