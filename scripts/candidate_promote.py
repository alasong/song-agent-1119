"""把一个「机制候选」提升成已登记的东西——这一步只能由人或受权方做。

候选由 `evolution.candidates()` 产出（`~/xm-runs/sa2/registry/candidates.jsonl`），
现在有两种形态，走两条路：

- `prompt_note`：并进知识面的人读种子（`sa2/knowledge/seed/lessons.jsonl`），
  只是给人 review 的文本，**不生效**；
- `criterion`：按候选里的 `spec` 造一个 Criterion，走 `judge.register(proposer=…)`。
  proposer 必须在判定权名单里——judge 自己会拒，这条命令不可能给自己发毕业证。

用法：
    python3 scripts/candidate_promote.py --list
    python3 scripts/candidate_promote.py --id 3 --apply --proposer leader
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.judge import Criterion, Judge            # noqa: E402
from sa2.memory import registry                       # noqa: E402

AUTHORITY = ("leader", "verifier")
SEED_DEFAULT = Path(__file__).resolve().parents[1] / "sa2" / "knowledge" / "seed" / "lessons.jsonl"


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def promote(candidate: dict, proposer: str, judge: Judge | None = None,
            seed: Path = SEED_DEFAULT) -> dict:
    """按候选形态提升。返回 {'kind': …, 'target': …}；不合格就抛。"""
    proposal = candidate.get("proposal") or {}
    kind = str(proposal.get("kind") or "")
    if kind == "prompt_note":
        text = str(proposal.get("text") or "").strip()
        if not text:
            raise ValueError("候选没有可导出的正文")
        seed.parent.mkdir(parents=True, exist_ok=True)
        existing = {row.get("id") for row in load(seed)}
        cid = str(candidate.get("when")) + "|" + text
        if cid in existing:
            return {"kind": kind, "target": str(seed), "written": False}
        with seed.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": cid, "when": candidate.get("when"),
                                 "text": text, "origin": "candidate_promote"},
                                ensure_ascii=False) + "\n")
        return {"kind": kind, "target": str(seed), "written": True}

    if kind == "criterion":
        spec = proposal.get("spec")
        if not isinstance(spec, dict) or not spec.get("name") or not spec.get("kind"):
            raise ValueError("criterion 候选缺 spec.name / spec.kind")
        if judge is None:
            raise ValueError("提升成判据需要已登记的判据库（judge）")
        crit = Criterion(name=str(spec["name"]), kind=str(spec["kind"]),
                         spec=dict(spec.get("spec") or {}),
                         dims=tuple(spec.get("dims") or ()),
                         self_tested=bool(spec.get("self_tested")),
                         scope=str(spec.get("scope") or "delivery"))
        judge.register(crit, proposer=proposer)     # 名单外的 proposer 在这里被拒
        return {"kind": kind, "target": crit.name, "written": True}

    raise ValueError(f"不认识的候选形态：{kind!r}（只有 prompt_note / criterion 可提升）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--id", type=int, default=None, help="候选在文件里的行号（从 0 起）")
    ap.add_argument("--apply", action="store_true", help="不加就是 dry-run，只打印将做什么")
    ap.add_argument("--proposer", default="leader", choices=AUTHORITY)
    ap.add_argument("--seed", default=str(SEED_DEFAULT))
    ap.add_argument("--registry", default=None, help="默认用 XM_SA2_REGISTRY 或 ~/xm-runs")
    args = ap.parse_args()

    root = Path(args.registry).expanduser() if args.registry else registry.root()
    path = root / "candidates.jsonl"
    rows = load(path)

    if args.list or args.id is None:
        if not rows:
            print(f"没有候选：{path} 不存在或为空")
            return 0
        for i, row in enumerate(rows):
            prop = row.get("proposal") or {}
            print(f"[{i}] when={row.get('when')} support={row.get('support')} "
                  f"rate={row.get('rate')} kind={prop.get('kind')} status={row.get('status')}")
            print(f"    {str(prop.get('text') or prop.get('spec'))[:120]}")
        return 0

    if not 0 <= args.id < len(rows):
        print(f"候选行号 {args.id} 越界（共 {len(rows)} 条）", file=sys.stderr)
        return 1
    candidate = rows[args.id]

    if not args.apply:
        print(f"dry-run：会把候选 [{args.id}] 提升为 "
              f"{(candidate.get('proposal') or {}).get('kind')}；加 --apply 才写。")
        return 0

    judge = None
    if (candidate.get("proposal") or {}).get("kind") == "criterion":
        judge = Judge(authority=AUTHORITY, path=root / "criteria.json",
                      history=root / "criteria-history.jsonl")
    try:
        done = promote(candidate, args.proposer, judge=judge, seed=Path(args.seed))
    except Exception as exc:                      # 提升失败要大声
        print(f"提升失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"已提升：{done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
