"""自举入口：从 ROADMAP 取下一个任务 → 在 sandbox 里让系统自己实现 → 产出 diff 交人审。

规矩（见 README「演进规矩」）：
- 系统不直接改项目目录，只在 sandbox/ 里工作
- 没有机检判据（tests/test_<slug>.py）的任务，拒绝执行——判据先于实现
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.backlog import load, next_ready

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {".git", "runs", "reports", "sandbox", "__pycache__"}

M1_SPEC = """在项目根目录新建 `xm/app.py`，实现装配层 `Org`，把已有的 ticket / bus / gates / metrics 串起来。

要求：
- `Org()` 无参构造；实例上有 `self.bus`（xm.bus.Bus）、`self.metrics`（xm.metrics.Metrics）、`self.gates`（xm.gates.GateChain）。
- `submit(goal: str) -> str`：构造一条 `kind="task"`、`sender="planner"`、`receiver="executor"` 的工单（id 自增：T1、T2…），提交到 bus 并返回 id。
- `submit_raw(payload: dict) -> str`：先 `Ticket.parse` 校验再提交；非法输入必须让 `TicketError` 原样抛出，且**不得**产生任何工单。
- `tick() -> None`：取 `executor` inbox 里最早的一条，claim 后跑 `Pipeline`（artifacts 可为空）。准出未过时单会变成 `rejected`；`Org.tick()` 必须吞掉该异常、不向外抛。
- `reports() -> list[str]`：返回所有被拒收工单的 id，按拒收顺序。
- 只用标准库，复用现有 `xm/` 模块，不要改 `xm/bus.py`、`xm/gates.py`、`xm/pipeline.py`、`xm/ticket.py`。
"""


def copy_project(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for item in ROOT.iterdir():
        if item.name in EXCLUDE:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(item, target)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="判据存在时，在 sandbox 里让系统自己实现")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    task = next_ready(load(ROOT / "docs" / "ROADMAP.md"))
    if task is None:
        print(json.dumps({"status": "idle", "message": "ROADMAP 里没有待办任务"}, ensure_ascii=False))
        return 0

    slug = task.slug
    sandbox = ROOT / "sandbox" / slug
    copy_project(sandbox)

    criteria = ROOT / "tests" / f"test_{slug}.py"
    out = ROOT / "runs" / slug
    out.mkdir(parents=True, exist_ok=True)
    package = {
        "task": task.name,
        "status": task.status,
        "evidence": task.evidence,
        "sandbox": str(sandbox.relative_to(ROOT)),
        "criteria_file": str(criteria.relative_to(ROOT)),
        "has_criteria": criteria.exists(),
        "next": ("执行 daemon" if criteria.exists() else "先写机检判据：没有判据的任务不接"),
    }
    (out / "task.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(package, ensure_ascii=False, indent=2))

    if not criteria.exists() or not args.execute:
        return 0 if criteria.exists() else 2

    # 系统在 sandbox 里自己实现；项目目录不受影响，改完由人看 diff 决定合入
    from xm.daemon import Daemon, DaemonConfig
    from xm.ledger import Ledger
    from xm.llm import complete

    cfg = DaemonConfig(
        spec=M1_SPEC, target_file="xm/app.py", tests=[f"tests.test_{slug}"],
        max_rounds=args.rounds, patience=2, in_sandbox=True,
        context_files=["xm/pipeline.py", "xm/bus.py", "xm/ticket.py", "xm/gates.py", "xm/metrics.py"],
    )
    llm = lambda messages: complete(
        messages, model=args.model, max_tokens=8000,
        extra={"thinking": {"type": "disabled"}},
    )
    summary = Daemon(Ledger(out / "bootstrap_ledger.jsonl"), llm, cfg, workspace=str(sandbox)).run()
    summary.update({"task": task.name, "model": args.model, "sandbox": str(sandbox.relative_to(ROOT))})
    (out / "bootstrap.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["green_at_round"] else 1


if __name__ == "__main__":
    raise SystemExit(main())