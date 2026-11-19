"""判据实例化：把「文字判据」变成可执行判据，**但要先过三反例自测**。

自测的三件东西是这套设计里最值钱的几行：
    合格件  —— 该过的必须过（否则判据太严，好活被判死）
    缺件    —— 少一样必须拒（否则判据太松）
    冒充件  —— 把章节名/关键词塞进代码围栏，仍必须拒（否则判据能被格式骗过）

第三件是实测教训：sa 1.0 的 `scripts/dna_audit.py` 首版按词面 grep，被自己的正则字面量
和注释骗出 5 处误判。判据自己会造假的时候，只有反例能抓。

两种可生成的形态（都只看代码围栏之外的内容）：
    sections  「必须包含：## 一、x」→ 章节行必须原样出现
    regex     「必须出现：机制：」  → 关键词必须出现（字面匹配，不当正则用）

范围说明（写在代码里而不是藏起来）：这里生成的是**结构类与关键词类**判据。
观点类判据（写得好不好）不在这里生成——它需要人定标准，生成方造它等于自评。
"""
from __future__ import annotations

from dataclasses import replace

from ..core.judge import Criterion, Judge

STRUCT = "必须包含："
CONTENT = "必须出现："


def propose_sections(name: str, required, dims) -> Criterion:
    items = [str(s).strip() for s in required if str(s).strip()]
    return Criterion(name=name, kind="sections", spec={"required": items},
                     dims=tuple(dims), self_tested=False)


def propose_content(name: str, markers, dims) -> Criterion:
    items = [str(s).strip() for s in markers if str(s).strip()]
    return Criterion(name=name, kind="regex", spec={"patterns": items, "literal": True},
                     dims=tuple(dims), self_tested=False)


def _collect(spec_text: str) -> tuple[list[str], list[str]]:
    struct: list[str] = []
    content: list[str] = []
    for line in (spec_text or "").splitlines():
        stripped = line.strip()
        for marker, bucket in ((STRUCT, struct), (CONTENT, content)):
            if stripped.startswith(marker):
                bucket.append(stripped[len(marker):].strip())
                break
    return struct, content


def instantiate(spec_text: str, name: str, dims) -> Criterion:
    """从规格文本里取出必答项。混用两种标记就抛，不猜你想要哪种。"""
    struct, content = _collect(spec_text)
    if struct and content:
        raise ValueError(f"规格里同时有「{STRUCT}」与「{CONTENT}」：请分开实例化成两条判据")
    if struct:
        return propose_sections(name, struct, dims)
    if content:
        return propose_content(name, content, dims)
    raise ValueError(f"规格里没有 {STRUCT} 或 {CONTENT} 行，无法实例化判据")


def _probe_judge() -> Judge:
    # 自测用的独立判定实例：不污染主 Judge，也不需要它承认自测结果
    return Judge(authority=("probe",), require_self_tested=False)


def _run_cases(crit: Criterion, required: list[str]) -> tuple[bool, list[str]]:
    probe = _probe_judge()
    probe.register(replace(crit, self_tested=True), proposer="probe")
    good = "\n".join(required)
    missing = "\n".join(required[:-1])               # 少最后一条
    fake = "```\n" + "\n".join(required) + "\n```"   # 全塞进代码围栏
    cases = [("合格件", good, True), ("缺件", missing, False), ("冒充件", fake, False)]
    fails: list[str] = []
    for label, text, expect_ok in cases:
        verdict = probe.run(crit.name, text)
        if verdict.ok != expect_ok:
            got = "过" if verdict.ok else "拒"
            want = "过" if expect_ok else "拒"
            fails.append(f"{label}：期望{want}，实际{got}")
    return (not fails), fails


def self_test(crit: Criterion) -> tuple[bool, list[str]]:
    """跑三反例。返回 (是否全过, 失败明细)。"""
    if crit.kind == "sections":
        required = [str(s) for s in (crit.spec.get("required") or [])]
    elif crit.kind == "regex" and crit.spec.get("literal"):
        required = [str(s) for s in (crit.spec.get("patterns") or [])]
    else:
        return False, [f"自测暂不支持 {crit.kind} 形态（只支持 sections 与字面 regex）"]
    if not required:
        return False, ["判据没有任何必答项，无法自测"]
    return _run_cases(crit, required)


def tested(crit: Criterion) -> Criterion:
    """过了自测就把标记打上；没过就抛，不许带着未验证的判据进登记。"""
    ok, fails = self_test(crit)
    if not ok:
        raise ValueError(f"判据 {crit.name!r} 自测未过：{'；'.join(fails)}")
    return replace(crit, self_tested=True)