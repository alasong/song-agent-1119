#!/usr/bin/env python3
"""S1 演示：角色档案落盘 → 换实例重读 → 记战绩 → 交出接管包。

跑法：python3 scripts/demo_role_profile.py
不碰仓库数据：写临时目录，跑完删掉。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.memory.profiles import RoleProfile, RoleStore  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "roles.jsonl"
        store = RoleStore(path)

        profile = RoleProfile(id="研究员·甲", kind="researcher", duty="查文献与取数",
                              tools=("fetch:arxiv",), criteria_version="c-2026-11-20")
        profile.strengths.append("arXiv 检索")
        keep = profile.add_promise("把第三节的引用补齐", goal="AI 科研自动化路线比较")
        closed = profile.add_promise("核一遍检索式")
        store.save(profile)

        print("① 建档并落盘")
        print(f"   {path}（{path.stat().st_size} 字节）")

        reloaded = RoleStore(path).get("研究员·甲")
        print("② 换一个实例重读（等价于进程重启）")
        print(f"   id={reloaded.id}  kind={reloaded.kind}  duty={reloaded.duty}")
        print(f"   tools={list(reloaded.tools)}  status={reloaded.status}")
        print(f"   calibration={reloaded.calibration!r}（None=空壳，不是 0.0）")
        print(f"   未偿承诺：{[x['text'] for x in reloaded.pending_promises()]}")

        reloaded.bump("done")
        reloaded.resolve_promise(closed["id"])
        store.save(reloaded)
        again = RoleStore(path).get("研究员·甲")
        print("③ 记一次战绩、了结一条承诺，再重读")
        print(f"   战绩={again.record}  未偿承诺={[x['text'] for x in again.pending_promises()]}")

        print("④ 接管包（S2 的 supervisor 把它交给继任者）")
        pack = again.handover()
        print(json.dumps(pack, ensure_ascii=False, indent=2))
        assert [x["id"] for x in pack["promises"]] == [keep["id"]]

        print("⑤ 判红演练：查一个不存在的人")
        try:
            RoleStore(path).get("没有这个人")
        except KeyError as exc:
            print(f"   KeyError: {exc}（不静默返回空档案）")
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main())