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

import re
from dataclasses import replace

from ..core.judge import Criterion, Judge

STRUCT = "必须包含："
CONTENT = "必须出现："


def propose_sections(name: str, required, dims) -> Criterion:
    items = [str(s).strip() for s in required if str(s).strip()]
    return Criterion(name=name, kind="sections", spec={"required": items},
                     dims=tuple(dims), self_tested=False)


SEPARATORS = r"[、,，;；]"


def split_items(text: str) -> list[str]:
    """「来源标注、分类标签」是两个要出现的词，不是一个长串。
    合成一个长串等于要求文档里出现这句连写，永远判红。"""
    out: list[str] = []
    for chunk in re.split(SEPARATORS, str(text or "")):
        item = chunk.strip().strip("「」“”\"'")
        if item:
            out.append(item)
    return out


def propose_content(name: str, markers, dims) -> Criterion:
    items: list[str] = []
    for marker in markers:
        items.extend(split_items(marker))
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


def split_spec(spec_text: str) -> tuple[list[str], list[str]]:
    """按标记把规格拆成「章节」与「关键词」两摞，调用方各自实例化。"""
    return _collect(spec_text)


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


# ── 让系统自己出判据（原料不再由人写）─────────────────────────────────────

SPEC_PROMPT = """你是验收设计者。请为下面这个任务写一组**可机检**的验收规格，并附一份**能通过它的最小合格样例**。

任务：{goal}
{context}
规则（违反任何一条，这组判据都会被拒）：
- 「必须包含：」后面必须是**文档里会原样出现的一行标题**，形如 `## 一、XXX`。
  不许写要求句子（例如「条目数 ≥ 40 且每条含…」这种永远不可能出现在文档里的行）。
- 「必须出现：」后面是**文档正文里会逐字出现的词**，例如「单位经济」「不选」「止损线」。
  多个词用顿号分隔；不许写「质量」「深度」「合理性」这类没人能判的词，也不许写 ≥、且 这类句子。
- 3–6 行规格，其中至少一行是「必须出现：」。
- 样例必须同时满足上面每一条（它会被拿去跑一遍判据，跑不过就整组作废）。

输出格式（两个块，不要别的解释）：
### SPEC
必须包含：## 一、XXX
必须包含：## 二、YYY
必须出现：关键词A、关键词B
### SAMPLE
## 一、XXX
一节正文，含关键词A 与关键词B。
## 二、YYY
二节正文。
"""


def _blocks(raw: str) -> tuple[str, str]:
    spec = sample = ""
    match = re.search(r"###\s*SPEC\s*\n(.*?)(?=###\s*SAMPLE|\Z)", raw or "", re.S)
    if match:
        spec = match.group(1).strip()
    match = re.search(r"###\s*SAMPLE\s*\n(.*)\Z", raw or "", re.S)
    if match:
        sample = match.group(1).strip()
    return spec, sample


def propose_spec(goal: str, llm, context: str = "") -> dict:
    """让模型把目标翻译成规格 + 一份它认为能过的最小样例。

    为什么要样例：三反例只证明「判据执行正确」，不证明「判据可满足」。
    实测里模型写出过「必须包含：素材条目总数 ≥ 40，且…」这种永远不可能出现在文档里的行，
    自测照样全绿，一跑必红。样例就是它的可满足性证明。
    """
    raw = llm([{"role": "user", "content": SPEC_PROMPT.format(
        goal=goal, context=("\n" + context.strip() + "\n") if context.strip() else "")}], 1600) or ""
    spec, sample = _blocks(raw)
    return {"raw": raw, "spec": spec or raw, "sample": sample}


def instantiate_all(spec_text: str, dims, prefix: str = "", scope: str = "delivery") -> list[Criterion]:
    """把规格拆成「章节判据 + 要素判据」，各自带名字与作用域。"""
    struct, content = split_spec(spec_text)
    out: list[Criterion] = []
    if struct:
        out.append(replace(propose_sections(f"{prefix}章节", struct, dims), scope=scope))
    if content:
        out.append(replace(propose_content(f"{prefix}要素", content, dims), scope=scope))
    return out


def _shell(specs: list[Criterion]) -> str:
    """空壳件：标题齐全，正文全是「本站略」，一个要素都没有。"""
    lines: list[str] = []
    for crit in specs:
        if crit.kind == "sections":
            lines.extend(str(h) for h in crit.spec.get("required") or [])
    return "\n".join(lines) + "\n（本节略）\n"


def test_set(specs: list[Criterion], sample: str | None = None) -> tuple[bool, list[str]]:
    """一整组判据的自测：三反例 + **空壳件必须被其中至少一条拒掉**。

    只测单条会漏掉最贵的失效形态：章节判据全过、要素判据没生效，
    于是「标题齐全的空文档」能毕业。
    """
    if not specs:
        return False, ["没有任何判据"]
    probe = _probe_judge()
    for crit in specs:
        probe.register(replace(crit, self_tested=True), proposer="probe")

    sections: list[str] = []
    patterns: list[str] = []
    for crit in specs:
        if crit.kind == "sections":
            sections.extend(str(h) for h in crit.spec.get("required") or [])
        elif crit.spec.get("literal"):
            patterns.extend(str(x) for x in crit.spec.get("patterns") or [])

    def compose(secs, pats) -> str:
        return "\n".join(list(secs) + list(pats) + ["正文略。"])

    good = compose(sections, patterns)
    if len(sections) > 1:
        missing = compose(sections[:-1], patterns)
    elif patterns:
        missing = compose(sections, patterns[:-1])
    else:
        missing = compose(sections[:-1], [])
    fake = "```\n" + "\n".join(sections + patterns) + "\n```"
    shell = _shell(specs)

    fails: list[str] = []
    if not all(probe.run(c.name, good).ok for c in specs):
        fails.append("合格件：该过的没过")
    if all(probe.run(c.name, missing).ok for c in specs):
        fails.append("缺件：少一样仍然全过")
    if all(probe.run(c.name, fake).ok for c in specs):
        fails.append("冒充件：塞进代码围栏仍然全过")
    if all(probe.run(c.name, shell).ok for c in specs):
        fails.append("空壳件：只有标题、没有要素也能过（判据没有判别力）")
    if sample and not all(probe.run(c.name, sample).ok for c in specs):
        fails.append("样例自证：判据把模型自己给的合格样例判红了（判据不可满足或样例不达标）")
    return (not fails), fails


def tested_set(specs: list[Criterion], sample: str | None = None) -> list[Criterion]:
    ok, fails = test_set(specs, sample=sample)
    if not ok:
        raise ValueError("这组判据自测未过：" + "；".join(fails))
    return [replace(c, self_tested=True) for c in specs]


def tested(crit: Criterion) -> Criterion:
    """过了自测就把标记打上；没过就抛，不许带着未验证的判据进登记。"""
    ok, fails = self_test(crit)
    if not ok:
        raise ValueError(f"判据 {crit.name!r} 自测未过：{'；'.join(fails)}")
    return replace(crit, self_tested=True)