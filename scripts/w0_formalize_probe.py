#!/usr/bin/env python3
"""W0 探针 v2：20+ 个真实任务，形式化 + 抗冒充对抗样本。

两档计分：
- L1 可执行：checker 跑得起来；合格件 rc=0；模型自给坏件、空文件、占位文本都 rc≠0。
- L2 抗冒充：**另一次独立调用**（看不到 checker）写一份「格式齐全但结论/关键事实错」的稿子，
  checker 必须判红。这是语义判据最便宜的机检替代；不过它仍不等同于「判对了」，
  只说明判据不是纯结构匹配。

checker 源码、对抗样本、每次 rc 全部落盘，供人工复核。
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

MODEL = "deepseek-flash"

TASKS = [
    ("A", "判断我们该不该做 agent 创业方向；如果做，选哪个方向、不选什么，给出依据与止损。"),
    ("B", "给山西刚过特控线的考生一份专业与志愿建议，要能落地。"),
    ("C", "判断要不要把 sa 重做成双环：内环确定性收敛、外环探索。"),
    ("D", "把本周做的事写成一页给领导的周报：做了什么、卡在哪、下周做什么。"),
    ("E", "判断三条 AI 科研自动化路线（自动做实验 / 自动写作与审稿 / 自动选题）哪条值得押，给依据。"),
    ("F", "给 sa 的外环实验定一条预算上限，并说明什么情况下判停。"),
    ("G", "评估把 sa2_live 切到 --pool 2 是否值得：成本与收益各是什么。"),
    ("H", "决定要不要每天自动跑一次 sa，并给出止损条件。"),
    ("I", "把一次真跑的成本写成一页账：token、失败次数、返工次数。"),
    ("J", "判断 sa 离「单 agent 死了任务仍完成」还差什么，并给一条验收命令。"),
    ("K", "判断要不要给 sa 的 checker 加一层「语义复核」：说明收益、成本与失败模式。"),
    ("L", "给一个三人小团队定一周的 OKR：目标、关键结果、验收口径都要可判定。"),
    ("M", "判断是否该把 sa 的默认模型从 deepseek-flash 换成更强的模型，给出依据与回滚条件。"),
    ("N", "写一份「上线前检查清单」：至少 5 条，每条都要能被脚本判定通过/不通过。"),
    ("O", "判断要不要给 sa 引入人工复核环节：在哪些节点、谁来做、如何止损。"),
    ("P", "评估把 sa 的日志从本地文件改成结构化 JSONL 的收益与迁移成本。"),
    ("Q", "给一次线上事故写复盘：时间线、根因、影响面、改进项与验收方式。"),
    ("R", "判断 sa 的 L2 抗冒充判据是否足够：指出至少一个它能放过、但人应判红的场景。"),
    ("S", "为一个新功能写验收标准：功能描述、输入输出、边界条件、失败处理。"),
    ("T", "判断要不要把 sa 的探针任务集从 10 条扩到 20 条以上：收益、成本、风险。"),
    ("U", "给 sa 定一条「停止扩张、先修内环」的触发条件，并说明如何机检。"),
    ("V", "评估把 sa 的报告从 JSON 改成「JSON + 一页 Markdown 摘要」的取舍。"),
    ("W", "判断 sa 的 checker 是否应该禁止联网：给出理由、例外与检测方式。"),
    ("X", "为一个内部工具写使用说明：适用场景、不适用场景、一条最小示例。"),
]

FORM_PROMPT = """你是组织里的「目标形式化」角色。把下面的模糊任务形式化成可判定的东西。

只输出 JSON（不要解释、不要代码围栏）：
{
  "predicate": "一句可判真假的命题，带参数",
  "checker": "Python 源码：argv[1] 是待判交付物路径；合格 exit 0，不合格 exit 1。只读该文件，不联网。",
  "good_sample": "必然合格的极短样例（<300 字）",
  "bad_sample": "必然不合格的极短样例（<300 字）"
}

任务：{task}
"""

ADV_PROMPT = """根据下面的任务与判据，写一份**格式齐全、要素都在、但结论或关键事实是错的**交付物。
要求：不要自我承认错误、不要标注「这是反例」，读起来像一份正常交付。
只输出正文，不超过 400 字。

任务：{task}
判据：{predicate}
"""

EMPTY = ""
PLACEHOLDER = "TODO：待补充。\n"


def pick_tasks(n: int) -> list[tuple[str, str]]:
    """返回任务清单的前 n 条；n 超过总数时返回全部。"""
    if n < 0:
        raise ValueError("n 必须 >= 0")
    return list(TASKS[:n])


def _call(prompt: str, max_tokens: int) -> tuple[str, int]:
    text, usage = llm.complete_usage(
        [{"role": "user", "content": prompt}], model=MODEL, max_tokens=max_tokens,
        extra={"thinking": {"type": "disabled"}})
    return text or "", int(usage.get("total_tokens") or 0)


def _parse(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("模型输出里没有 JSON")
    return json.loads(match.group(0))


def _run(checker: Path, target: Path, timeout: int = 20) -> int:
    proc = subprocess.run([sys.executable, str(checker), str(target)],
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode


def probe(tasks: list[tuple[str, str]] | None = None) -> dict:
    tasks = list(TASKS) if tasks is None else list(tasks)
    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for task_id, task in tasks:
            row = {"id": task_id, "task": task, "l1": False, "l2": False, "why": ""}
            try:
                text, u1 = _call(FORM_PROMPT.replace("{task}", task), 1800)
                data = _parse(text)
                predicate = str(data.get("predicate") or "")
                checker_src = str(data.get("checker") or "")
                if not predicate or not checker_src:
                    raise ValueError("缺 predicate 或 checker")
                folder = tmp / task_id
                folder.mkdir()
                checker = folder / "checker.py"
                checker.write_text(checker_src, encoding="utf-8")
                files = {"good": folder / "good.md", "bad": folder / "bad.md",
                         "empty": folder / "empty.md", "placeholder": folder / "placeholder.md"}
                files["good"].write_text(str(data.get("good_sample") or ""), encoding="utf-8")
                files["bad"].write_text(str(data.get("bad_sample") or ""), encoding="utf-8")
                files["empty"].write_text(EMPTY, encoding="utf-8")
                files["placeholder"].write_text(PLACEHOLDER, encoding="utf-8")

                adv_text, u2 = _call(ADV_PROMPT.replace("{task}", task)
                                     .replace("{predicate}", predicate), 700)
                adv = folder / "adversarial.md"
                adv.write_text(adv_text, encoding="utf-8")

                rcs = {name: _run(checker, path) for name, path in files.items()}
                rcs["adversarial"] = _run(checker, adv)
                l1 = (rcs["good"] == 0 and rcs["bad"] != 0
                      and rcs["empty"] != 0 and rcs["placeholder"] != 0)
                l2 = l1 and rcs["adversarial"] != 0
                row.update({"l1": l1, "l2": l2, "predicate": predicate,
                            "checker": checker_src, "rcs": rcs,
                            "adversarial": adv_text.strip()[:400],
                            "tokens": u1 + u2,
                            "why": "" if l2 else ("L1 未过" if not l1 else "对抗样本被放过")})
            except Exception as exc:
                row["why"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            print(f"{task_id}: L1={'过' if row['l1'] else '红'}  "
                  f"L2={'过' if row['l2'] else '红'}  "
                  f"rcs={row.get('rcs') or row['why']}")

    l1n = sum(1 for r in rows if r["l1"])
    l2n = sum(1 for r in rows if r["l2"])
    total = len(rows) or 1
    result = {
        "step": "W0-formalize-v2", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "samples": len(rows), "l1_passed": l1n, "l2_passed": l2n,
        "l1_rate": round(l1n / total, 3), "l2_rate": round(l2n / total, 3),
        "note": "L2=判据能拒掉格式齐全但结论错的稿子；仍不等于语义判对",
        "rows": rows,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / f"w0-formalize-v2-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nL1 {l1n}/{len(rows)}  L2（抗冒充）{l2n}/{len(rows)}；读数写入 {out.name}")
    return result


if __name__ == "__main__":
    probe()
    raise SystemExit(0)
