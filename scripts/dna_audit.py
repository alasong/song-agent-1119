"""DNA 落地审计：逐条核对设计文档 §二 的 DNA 是否真有承载体。

为什么要有它：DNA 是硬编码的最高原则，但「文档说了」和「代码里有」是两件事。
上一版的差距清单是读代码写出来的散文，读完就散、下次还得重读一遍。
本脚本把每条 DNA 拆成若干分支，每个分支给一个机检谓词——
不成立的那一格就是差距，且差距从此可复跑。

用法：
  python3 scripts/dna_audit.py           # 人读表
  python3 scripts/dna_audit.py --json    # 机器读

退出码：
  0 = 审计跑完。差距是事实，不是错误——红着退出会把「缺口」和「脚本坏了」混为一谈。
  1 = 文档里有一条 DNA 没登记判据。以后想加 DNA，必须同时登记它的承载体判据；
      加不进来，就说明它还只是一句话。

判据只看**代码 token**：注释与字符串字面量在匹配前被剥掉。
这是本脚本第一条教训——按词面 grep 会把注释、文档串、以及审计脚本自己的正则
字面量当成实现（首版实测 #3/#5/#7 三处假绿、#1/#8 两处把标签当实现）。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "AI自治科研组织_准超级智能系统_完整设计文档.md"
PROD_DIRS = ("xm", "scripts")
SELF = "scripts/dna_audit.py"  # 审计脚本自己的正则字面量不许参与判定

STATUS_LABEL = {"landed": "落地", "partial": "半", "absent": "零", "unprobed": "无判据"}


# ── 源码探测（只读，不改任何东西）───────────────────────────────────────────

def _py_files(dirs=PROD_DIRS):
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            if p.relative_to(ROOT).as_posix() == SELF:
                continue
            yield p


_BLANKED = tuple(t for t in (tokenize.COMMENT, tokenize.STRING,
                             getattr(tokenize, "FSTRING_MIDDLE", None)) if t)


def code_lines(path: Path) -> list[tuple[int, str]]:
    """把注释与字符串字面量**按原位置**替换成空格，保留原始排版与行号。

    不重排 token：首版用「拼接 token」的办法，结果 `delivery . check` 把点号拆开，
    `def check(` 也匹配不上——假绿换成假红同样是错读数。
    """
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    out = list(lines)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [(i, line) for i, line in enumerate(lines, 1)]
    for tok in toks:
        if tok.type not in _BLANKED:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        for r in range(srow, min(erow, len(out)) + 1):
            line = out[r - 1]
            a = scol if r == srow else 0
            b = ecol if r == erow else len(line)
            out[r - 1] = line[:a] + " " * (b - a) + line[b:]
    return [(i, text) for i, text in enumerate(out, 1)]


def _scan(pattern: str, dirs=PROD_DIRS):
    rx = re.compile(pattern)
    for p in _py_files(dirs):
        for lineno, text in code_lines(p):
            if rx.search(text):
                yield f"{p.relative_to(ROOT)}:{lineno}", text.strip()


def find(pattern: str, dirs=PROD_DIRS) -> tuple[bool, str]:
    """在 xm/ 与 scripts/ 的代码里找一行匹配。返回 (是否命中, 首个命中位置)。"""
    for where, _text in _scan(pattern, dirs):
        return True, where
    return False, f"未命中 /{pattern}/"


def in_file(rel: str, pattern: str) -> tuple[bool, str]:
    p = ROOT / rel
    if not p.exists():
        return False, f"{rel} 不存在"
    rx = re.compile(pattern)
    for lineno, text in code_lines(p):
        if rx.search(text):
            return True, f"{rel}:{lineno}"
    return False, f"{rel} 未命中 /{pattern}/"


def used(module: str) -> tuple[bool, str]:
    """某个 xm 模块是否被生产代码 import —— 只看被引用，不看它自己写了什么。"""
    rx = re.compile(rf"^\s*(from xm\.{module}\b|import xm\.{module}\b)", re.M)
    for p in _py_files():
        if p.name == f"{module}.py":
            continue
        for lineno, text in code_lines(p):
            if rx.search(text):
                return True, f"{p.relative_to(ROOT)}:{lineno}"
    return False, f"xm/{module} 在 xm/ 与 scripts/ 无 import 方（只在 tests/ 出现）"


def backlog_section() -> tuple[bool, str]:
    """直接读模块常量，而不是匹配源码里那个被引号包着的值。"""
    sys.path.insert(0, str(ROOT))
    from xm import backlog
    return ("## 7" in backlog.SECTION), f"xm/backlog.py SECTION={backlog.SECTION!r}"


# ── 每条 DNA 的分支谓词 ────────────────────────────────────────────────────
# 一个分支 = 一句能判真假的断言。全真=落地，全假=零，其余=半。

SPEC: dict[int, list[tuple[str, object]]] = {
    1: [
        ("任务来源可从进度表读出", backlog_section),
        ("目标树自动生成/拆解", lambda: find(r"def (decompose|goal_tree|split_goal)")),
        ("目标偏离度计算", lambda: find(r"def (\w*deviation\w*|偏离)")),
    ],
    2: [
        ("健康指标被生产路径采集", lambda: used("metrics")),
    ],
    3: [
        ("动态创建角色", lambda: in_file("xm/hiring.py", r"def plan_org")),
        ("动态销毁/替换角色", lambda: find(r"def (\w*(retire|destroy|replace_role)\w*)")),
        ("编制可复用（不每次重建）", lambda: find(r"def (\w*reuse\w*|previous_plan|last_plan)")),
    ],
    4: [
        ("账本写入入口", lambda: in_file("xm/ledger.py", r"def append\(")),
        ("账本被生产路径使用", lambda: used("ledger")),
    ],
    5: [
        ("版本化/灰度/回滚机制", lambda: find(r"def (\w*(rollback|canary|gray)\w*)")),
    ],
    6: [
        ("存在编制自我调整入口", lambda: find(r"(org_adjustment|max_roles)")),
        ("调整由健康指标驱动（非人工参数）",
         lambda: (used("metrics")[0] and not find(r"max_roles", ("xm",))[0],
                  "metrics 无生产消费者" if not used("metrics")[0]
                  else "调整条件仍读人工传入的 max_roles")),
    ],
    7: [
        ("健康指标阈值判断", lambda: used("metrics")),
        ("推倒重构决策入口", lambda: find(r"def (\w*(refactor_decision|rebuild)\w*)")),
    ],
    8: [
        ("角色持有预算并做上限校验", lambda: find(r"budget_cap")),
        ("组织路径运行期预算闸", lambda: in_file("xm/sa_task.py", r"if .*budget.*[><]")),
        ("收益账本（验证方收益=抓到的真错）", lambda: find(r"def (\w*(reward|收益)\w*)")),
    ],
    9: [
        ("五条机检在 delivery.check", lambda: in_file("xm/delivery.py", r"def check\(")),
        ("交付路径实际调用", lambda: in_file("xm/deliver.py", r"delivery\.check")),
        ("仓库文本用同一判据", lambda: in_file("scripts/claim_check.py", r"bare_optimal_lines")),
    ],
}


# ── 解析与判定 ──────────────────────────────────────────────────────────────

def parse_dna(doc: Path | None = None) -> list[dict]:
    """从设计文档 §二 的表格里读出 DNA 条目。文档是标尺，不是脚本的私货。"""
    text = (doc or DOC).read_text(encoding="utf-8")
    start = text.index("## 二、核心DNA")
    end = text.index("\n## ", start + 5)
    rows = []
    for line in text[start:end].splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$", line)
        if m:
            rows.append({"num": int(m.group(1)), "name": m.group(2).strip(),
                         "meaning": m.group(3).strip(), "form": m.group(4).strip()})
    return rows


def status_of(claims: list[dict]) -> str:
    ok = sum(1 for c in claims if c["ok"])
    if not claims:
        return "unprobed"
    if ok == len(claims):
        return "landed"
    if ok == 0:
        return "absent"
    return "partial"


def audit(doc: Path | None = None) -> dict:
    rows = []
    for item in parse_dna(doc):
        spec = SPEC.get(item["num"])
        if spec is None:
            rows.append({**item, "status": "unprobed", "claims": []})
            continue
        claims = []
        for text, pred in spec:
            try:
                ok, evidence = pred()
            except Exception as exc:  # 谓词自己坏了也要看得见，不能悄悄算成「零」
                ok, evidence = False, f"{type(exc).__name__}: {exc}"
            claims.append({"claim": text, "ok": bool(ok), "evidence": evidence})
        rows.append({**item, "status": status_of(claims), "claims": claims})
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUS_LABEL}
    return {"doc": str((doc or DOC).relative_to(ROOT)) if (doc or DOC).is_relative_to(ROOT)
            else str(doc or DOC),
            "rows": rows, "counts": counts,
            "unprobed": [r["num"] for r in rows if r["status"] == "unprobed"]}


def render(result: dict) -> str:
    c = result["counts"]
    out = [f"DNA 落地审计（标尺：{result['doc']} §二）",
           f"落地 {c['landed']} · 半 {c['partial']} · 零 {c['absent']} · 无判据 {c['unprobed']}",
           ""]
    for row in result["rows"]:
        out.append(f"[{STATUS_LABEL[row['status']]}] #{row['num']} {row['name']}")
        if row["status"] == "unprobed":
            out.append("    未登记判据 —— 新增 DNA 必须同时登记承载体判据")
            continue
        for cl in row["claims"]:
            mark = "OK  " if cl["ok"] else "MISS"
            out.append(f"    {mark} {cl['claim']} → {cl['evidence']}")
    out.append("")
    out.append("差距清单的可复跑口径就是这条命令：python3 scripts/dna_audit.py")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="机器读")
    ap.add_argument("--doc", default=None, help="换一份设计文档（默认 docs/ 里那份）")
    args = ap.parse_args()

    doc = Path(args.doc) if args.doc else None
    result = audit(doc)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 1 if result["unprobed"] else 0


if __name__ == "__main__":
    sys.exit(main())