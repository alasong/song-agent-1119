"""交付标准的机检：让「只说够好不讲最优就算没交付」这条规则第一次能判红。

只做两条，能说清才能被执行：

1. **裸称「最优」且没有读数**：正文里出现未加引号的「最优」，同一行必须带一个真实读数
   （`1 次`、`32 次`、`6/15`、`9 处` 这种「数字 + 单位」）。只写「候选集内最优」「依据很充分」
   不算——那正是套路的形状：借论证的词汇，不给可核对的数。引号里、代码块里讨论这个词不算声称。
   理由：`docs/OPTIMALITY.md` 已判定「最优」不可证，正文还裸着用，就是把修辞当结论。
2. **自说自话**：`reports/bench-*.json` 里的 `verdict` 必须与 `passed/total` 相符。
   一份报告说自己「够了」但只过了 5/6，判红——自己给自己发奖状正是这条规则要防的。

扫不到的：对话里的交付。那是人看的，机器管不了，脚本不假装能管。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.delivery import bare_optimal_lines  # 与交付检查共用一套规则，避免两处各写一份

CERTAIN = ("已经完全验证", "已证明最优", "保证最优", "绝对正确")
# 交付里不许留「下一步 / 待办」节：该做的当场做，做不到的写「未验证」并给不可得理由。
# 判据照搬 ~/.dsh/notes/work-loop.md（那边是 grep，这里是同一口径）。
OPEN_TAIL = re.compile(r"^#{1,4}\s*(下一步|待办)\s*$")


def _strip_quotes(line: str) -> str:
    return QUOTED.sub("", line)


def scan_text(path: Path) -> list[dict]:
    """返回违规行：裸称「最优」却没有读数，或写了机器判不了的断言。"""
    text = path.read_text(encoding="utf-8")
    problems: list[dict] = [
        {"file": str(path), "line": lineno, "kind": "bare-optimal",
         "text": line[:120],
         "why": "称「最优」却没有读数（数字+单位）——只给词不给数，就是凑"}
        for lineno, line in bare_optimal_lines(text)
    ]
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if OPEN_TAIL.match(line.strip()):
            problems.append({"file": str(path), "line": lineno, "kind": "open-tail",
                             "text": line.strip()[:120],
                             "why": "交付里留了「下一步/待办」节——该做的当场做，做不到的写「未验证」并给不可得理由"})
        if re.match(r"^\s*```", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        bare = re.sub(r"「[^」]*」|“[^”]*”|\"[^\"]*\"|`[^`]*`", "", line)
        for word in CERTAIN:
            if word in bare:
                problems.append({"file": str(path), "line": lineno, "kind": "certainty",
                                 "text": line.strip()[:120],
                                 "why": f"断言「{word}」——机器判不了的结论不许这么写"})
    return problems


def scan_bench_reports(reports: Path) -> list[dict]:
    """报告自己说的判定，必须与自己的读数一致。"""
    problems: list[dict] = []
    for path in sorted(reports.rglob("bench-*.json")):   # 递归：归档的报告也要查，避免归档成盲区
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append({"file": str(path), "line": 0, "kind": "broken-report",
                             "text": "", "why": f"报告本身坏了：{exc}"})
            continue
        passed, total = data.get("passed"), data.get("total")
        expect = "够了" if passed == total else "不够"
        if data.get("verdict") != expect:
            problems.append({"file": str(path), "line": 0, "kind": "verdict-mismatch",
                             "text": f"{data.get('verdict')}",
                             "why": f"读数 {passed}/{total} 应为「{expect}」，报告却写「{data.get('verdict')}」"})
    return problems


def doc_targets(root: Path) -> list[Path]:
    targets = [root / "AGENTS.md", root / "README.md"]
    targets += sorted((root / "docs").glob("*.md"))
    return [p for p in targets if p.exists()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    problems = []
    for path in doc_targets(root):
        problems += scan_text(path)
    problems += scan_bench_reports(root / "reports")

    if args.json:
        print(json.dumps({"problems": problems, "count": len(problems)}, ensure_ascii=False, indent=2))
    else:
        for p in problems:
            where = f"{p['file']}:{p['line']}" if p["line"] else p["file"]
            print(f"[FAIL] {where}  {p['why']}")
            if p["text"]:
                print(f"       > {p['text']}")
        print(f"\n{len(problems)} 处需要改" if problems else "0 处：没有裸称最优，报告判定与读数一致")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())