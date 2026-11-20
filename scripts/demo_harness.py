#!/usr/bin/env python3
"""M5 演示：一台 WorkItem 状态机，两种活挂上来。

跑法：python3 scripts/demo_harness.py

看四件事：
- 文档活和代码活走同一张边表，加一种活只是 register 一个类型；
- 处理器声称「过了」不管用，状态只按产物 + 注册时的校验命令走；
- 进程没了，新进程从账本重放到断点，已走过的边不重跑；
- 判据登记后不许悄悄换。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core.harness import ARTIFACT, Harness, HarnessRefused  # noqa: E402

DOC_VERIFY = ("python3 -c \"import pathlib,sys;"
              "t=pathlib.Path('out/down.md').read_text();"
              "sys.exit(0 if '结论' in t else 1)\"")
CODE_VERIFY = "python3 -c \"import sys; sys.exit(0)\""


def walk(h: Harness, item: str, label: str) -> None:
    for to in ("routed", "running"):
        h.advance(item, to)
    print(f"   {label}: {h.state(item)}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        h = Harness(root)
        (root / "out").mkdir()
        (root / "out/down.md").write_text("结论：这套状态机能管住流程。\n", encoding="utf-8")

        print("① 注册两种活（判据是命令，不是形容词）")
        h.register("document", verify_cmd=DOC_VERIFY)
        h.register("code", verify_cmd=CODE_VERIFY)
        print(f"   类型={sorted(h.routes)}")

        print("② 文档活走同一张边表，交产物后停在 checked（还没判）")
        doc = h.declare(task_type="document", criteria=["有结论"])
        walk(h, doc, "到 running")
        h.advance(doc, "checked", artifacts={ARTIFACT: "out/down.md"})
        print(f"   document: {h.state(doc)}")

        print("③ 代码活不写新壳，只注册类型")
        code = h.declare(task_type="code", criteria=["测试绿"])
        walk(h, code, "到 running")
        (root / "out/fix.py").write_text("ok\n", encoding="utf-8")
        h.advance(code, "checked", artifacts={ARTIFACT: "out/fix.py"})
        h.advance(code, "done")
        print(f"   code: {h.state(code)}")

        print("④ 假处理器：声称 passed、不交产物 → 拒绝，状态不动")
        h.register("liar", handler=lambda item, to: {"passed": True}, verify_cmd=None)
        cheat = h.declare(task_type="liar", criteria=["有结论"])
        walk(h, cheat, "到 running")
        try:
            h.advance(cheat, "checked")
        except HarnessRefused as exc:
            print(f"   拒绝：{exc}")
        print(f"   liar: {h.state(cheat)}（声称留痕，状态没动）")

        print("⑤ 进程没了：新进程从账本重放，从断点续，边不重跑")
        del h
        again = Harness(root)
        print(f"   重放后 document={again.state(doc)} code={again.state(code)}")
        try:
            again.advance(doc, "checked")
        except HarnessRefused as exc:
            print(f"   重走旧边被拒：{exc}")
        again.advance(doc, "done")
        print(f"   续到：document={again.state(doc)}")
        alone = len([e for e in again.history(doc) if e["kind"] == "advance"])
        print(f"   document 走过的边={alone} 条，无重复")

        print("⑥ 判据不许悄悄换")
        try:
            again.register("document", verify_cmd="true")
        except HarnessRefused as exc:
            print(f"   拒绝：{exc}")

        ok = (again.state(doc) == "done" and again.state(code) == "done"
              and again.state(cheat) == "running")
        print(f"\n结论：{'过' if ok else '红'}——三种活一台状态机，判定权不在生成方")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())