#!/usr/bin/env python3
"""W0 冒烟：把 3 个真实任务形式化成「谓词 + 可执行判据」，量覆盖率。

两档计分，别混：
- L1 可执行：checker 跑得起来；合格件 rc=0；模型自给的坏件 rc≠0；系统再补两个坏件
  （空文件、占位文本）也 rc≠0。四条全过才算 L1。
- L2 语义：checker 判的是「命题真假」还是「结构要素」——机器判不了，本脚本不测，
  由人读 checker 源码。**不把 L1 当 W0 通过。**

跑法：python3 scripts/w0_formalize_probe.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2 import llm  # noqa: E402

# A/B 来自仓库里两个真实一次性任务（tasks/*.spec.md 的诉求形态）；C 是本次会话里的真实问题。
TASKS = [
    ("A", "判断我们该不该做 agent 创业方向；如果做，选哪个方向、不选什么，给出依据与止损。"),
    ("B", "给山西刚过特控线的考生一份专业与志愿建议，要能落地。"),
    ("C", "判断要不要把 sa 重做成双环：内环确定性收敛、外环探索。"),
]

PROMPT = """你是组织里的「目标形式化」角色。把下面这个模糊任务形式化成可判定的东西。

要求输出 JSON（不要解释、不要代码围栏）：
{
  "predicate": "一句可判真假的命题，带参数",
  "checker": "一段 Python 代码源码：argv[1] 是待判交付物的文件路径；合格 exit 0，不合格 exit 1。只查文件内容，不联网、不读别的文件。",
  "good_sample": "一份必然合格的极短样例（<300 字）",
  "bad_sample": "一份必然不合格的极短样例（<300 字）"
}

任务：{task}
"""

EMPTY = ""
PLACEHOLDER = "TODO：待补充。\n"


def _parse(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("模型输出里没有 JSON")
    return json.loads(match.group(0))


def _run(checker: Path, target: Path, timeout: int = 20) -> int:
    proc = subprocess.run([sys.executable, str(checker), str(target)],
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode


def probe() -> dict:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for task_id, task in TASKS:
            prompt = PROMPT.replace("{task}", task)
            text, usage = llm.complete_usage(
                [{"role": "user", "content": prompt}],
                model="deepseek-flash", max_tokens=1800,
                extra={"thinking": {"type": "disabled"}})
            row = {"id": task_id, "tokens": usage.get("total_tokens"),
                   "ok": False, "why": ""}
            try:
                data = _parse(text)
                predicate = str(data.get("predicate") or "")
                checker_src = str(data.get("checker") or "")
                if not predicate or not checker_src:
                    raise ValueError("缺 predicate 或 checker")
                folder = tmp / task_id
                folder.mkdir()
                checker = folder / "checker.py"
                checker.write_text(checker_src, encoding="utf-8")
                paths = {"good": folder / "good.md", "bad": folder / "bad.md",
                         "empty": folder / "empty.md", "placeholder": folder / "placeholder.md"}
                paths["good"].write_text(str(data.get("good_sample") or ""), encoding="utf-8")
                paths["bad"].write_text(str(data.get("bad_sample") or ""), encoding="utf-8")
                paths["empty"].write_text(EMPTY, encoding="utf-8")
                paths["placeholder"].write_text(PLACEHOLDER, encoding="utf-8")
                rcs = {name: _run(checker, path) for name, path in paths.items()}
                ok = (rcs["good"] == 0 and rcs["bad"] != 0
                      and rcs["empty"] != 0 and rcs["placeholder"] != 0)
                row.update({"ok": ok, "predicate": predicate, "rcs": rcs,
                            "checker_chars": len(checker_src), "why": "" if ok else "四件未全过"})
            except Exception as exc:
                row["why"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            print(f"{task_id}: L1={'过' if row['ok'] else '红'}  "
                  f"tokens={row['tokens']}  {row.get('rcs') or row['why']}")

    passed = sum(1 for r in rows if r["ok"])
    result = {"step": "W0-formalize-smoke", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "samples": len(rows), "l1_passed": passed,
              "l1_coverage": round(passed / len(rows), 3),
              "l2_semantic": "未测量（需人读 checker）", "rows": rows}
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / f"w0-formalize-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nL1 覆盖率 {passed}/{len(rows)}；L2 语义未测量；读数写入 {out.name}")
    return result


if __name__ == "__main__":
    result = probe()
    raise SystemExit(0 if result["l1_passed"] == result["samples"] else 0)