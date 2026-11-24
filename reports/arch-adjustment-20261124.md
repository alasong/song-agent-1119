# sa2 架构调整方案（2026-11-24）

> 状态：**提案，未执行**。依据 2026-11-23 的机检读数（`python3 scripts/dna_audit.py`、AST 导入图、412 条测试）。
> 为什么落在 `reports/` 而不是 `docs/`：README:19-24 规定 `docs/`、`sa2/`、`tests/`、`scripts/` 只能人审后改，
> 系统不得写入。本文件是待审的提案与证据，不是已生效的决定。

---

## 0. 目标对齐：架构调整只服务四件事

项目目标分三层（`README.md:3-13`、`docs/AI自治科研组织_准超级智能系统_完整设计文档.md:11`、
`docs/ASI-全形态蓝图.md:9`）：终极是**能自生长的活性组织**，形态是**科研军团**，
当前只落 **sa2 = 薄判定层 + 三圈可生成载体**。

`docs/ASI-全形态蓝图.md:59-64` 把目标形态压成四件骨架，缺一件形态就塌。
所以架构调整的判据不是"更整洁"，而是下面两条同时成立：

1. 让 **M-A** 的判红读数（抓错率 16.7% → ≥60%，盲测不降）**可复跑**；
2. 不破 **"生成方永不对判据拥有判定权"**（`docs/SA2.md:8`）。

任何不在下面四件骨架或这两条判据里的改动，一律算审美，不进本方案。

### 0.1 四件骨架 × sa2 现状

| 骨架 | 蓝图要求 | sa2 读数 | 判定 |
|---|---|---|---|
| 判定锚在外部 | 裁定落在系统改不动的地方 | `core/judge.py:11-12` 支持 `exec`/`callable`（可挂编译器、测试）；但默认交付判据是 sections/regex，锚在文本里 | 部分满足 |
| 判据冻结 | 立项即冻结，要改 = 新建节点 | `core/harness.py:77-90` 对 `task_type` 拒改；但 `Judge.register` 同名判据只升版本、不拒改（`core/judge.py:110-113`） | 部分满足 |
| 账本唯一真源 | 状态只能从 append-only 事件重放 | resume 依赖 `state.json`（`loop/pdca.py:132`、`:287`），里面存 `text`/`partial`，账本里没有对应事件 | 不满足 |
| 数据三分 | train/dev/test 互斥，挖反例只碰 dev | 0 处 train/dev/holdout；`loop/blind.py` 是评委盲评，不是数据隔离 | 不满足 |

### 0.2 工程缺口（不成骨架，但挡路）

| 缺口 | 读数 | 挡什么 |
|---|---|---|
| 没有稳定 bench 入口 | 16.7% 出自一次性探针 `reports/w0-formalize-v2-20261120-200022.json`（24 samples / l2_passed=4），且该文件未入库（`git status` 显示 `??`） | M-A 读数不可复跑 |
| 生成侧能自建判官 | `forge/criteria.py:86-93` 构造 `Judge(authority=("probe",))` 并 register | 红线只在运行期拦 |
| 回滚为零 | `dna_audit` #5 判"零"；`grep rollback sa2` 只命中一句注释 | DNA #5、设计文档 §八-7 |
| PDCA 是 443 行 19 方法的 god class | `loop/pdca.py:28-443` 混编排/提示词/写盘/反馈/报告 | 改环风险，挡迭代 |
| 零接口契约 | `grep Protocol\|ABC` = 0；`PDCA.produce` 用字符串注解 `"callable"` | M-B 换域要改调用点 |
| 失败可见有一处漏 | `memory/registry.py:66-73` 把坏掉的 goals.json 吞成空索引 | 失败不静默 |
| 文档漂移 | `docs/SA2.md:21,32,100` 写 890 行（实际 5265）；`:83` 引用不存在的 `bench.py`；`:108` 把已完成的断点重入标"未开始" | 判断依据失真 |

---

## 阶段 0：先把读数立起来（不改判定层）

### 0.1 bench 成为入口

**改什么**

- 新增 `scripts/sa2_bench.py`：从 `scripts/w0_formalize_probe.py` 收编 24 条任务与对抗样本生成逻辑，
  参数 `--split dev|test --min-l2 0.60 --json`，输出 `{samples, l1_rate, l2_rate, tokens}`，
  `l2_rate < min_l2` 时退出 1。`--dry-run` 用固定假模型，只验结构不联网。
- 把基线报告 `reports/w0-formalize-v2-20261120-200022.json` 入库（当前是未跟踪文件）。
- 文档纠偏（**需人审**）：`docs/SA2.md:21,32,100` 行数改为实测 5265（core 1178 / forge 1017 / loop 1385 / memory 714 / autonomy 211 / knowledge 201 / 根 559）；`:83` 删掉 `bench.py` 的六门残留；`:108` 改为"已完成"并指向三条测试。

**验收：**

```
python3 scripts/sa2_bench.py --dry-run --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'l2_rate' in d"
git ls-files reports/w0-formalize-v2-20261120-200022.json        # 非空
grep -c "890 行" docs/SA2.md                                     # 0
grep -c "bench.py 的 6 条" docs/SA2.md                            # 0
```

**为什么最前**：M-A 的 16.7% 目前只活在一个未跟踪的一次性报告里；不复跑，后面所有架构判断都是自证。

**判停**：两次真跑 `l2_rate` 差 > 10 个百分点，先查对抗件与判据的稳定性，不加新机制。

---

## 阶段 1：账本唯一真源（把 state.json 降级成缓存）

### 1.1 resume 从事件重建

**改什么**

- `loop/pdca.py` 的 `stage_ok`/`dispatch`/`reject` 事件补足重放所需：阶段产出写 artifact 目录并记 `path + sha256`，角色级 partial 同理。
- 新增 `PDCA.rebuild_state(ledger)`：从事件重建 `stage_index/text/ran/spent`；resume 先重建，再拿 `state.json` 做加速与校验，不一致以账本为准。
- `state.json` 保留，但删除它必须不改变行为。

**验收：**

```
python3 -m unittest tests.test_ledger_replay -q     # 新测试：跑一遍→删 state.json→resume，派活数与产物与不删时一致
```

**为什么在拆分之前**：阶段 5 要动 PDCA 的事件写入；先把"事件够不够重放"钉死，拆分才敢动。

**判停**：删除 state.json 后 resume 多派一次活或产物 hash 不一致 → 回滚，不把"近似"当重放。

---

## 阶段 2：判定权结构隔离

### 2.1 forge 拿不到 Judge

**改什么**

- 抽 `sa2/core/checks.py`：把 `judge.py` 的 `_unfenced/_run_sections/_run_regex/_run_callable/_run_exec` 改成模块级纯函数 `run(kind, spec, text) -> list[str]`；`Judge` 改为委托调用。
- `forge/criteria.py` 删掉 `_probe_judge`，三反例自测直接调 `checks.run`；`forge` 不再 import `Judge`。

**验收：**

```
grep -rn "import.*\bJudge\b\|Judge(" sa2/forge      # 无输出
python3 -m unittest tests.test_authority_seal -q   # 断言 sa2.forge.criteria 模块里没有 Judge
python3 -m unittest tests.test_sa2_forge -q        # 三反例原样全绿
```

**为什么现在做**：这条是项目定义本身，且**不改行为**——自测结果必须与改前逐条一致，所以风险低、收益最高。

**判停**：合格件/缺件/冒充件任一结果变化 → 回滚该阶段，不改判据迁就实现。

---

## 阶段 3：判据冻结、回滚与灰度

### 3.1 能退回上一版

**改什么**

- `core/judge.py` 新增 `rollback(name, version)`：从 `history.jsonl` 回放指定版本并记账本。
- `Criterion` 加 `active: bool = True`；`gate.check_criteria` 与交付门只认 active，阶段门可认 inactive（灰度先行）。
- 注意机检口径：`scripts/dna_audit.py` 的 #5 用正则 `def (\w*(rollback|canary|gray)\w*)` 判落地，
  所以函数名必须叫 `rollback`（或同步改审计判据，需人审），否则实现做了、门还是判零。

**验收：**

```
grep -n "def rollback" sa2/core/judge.py                                    # 命中
python3 -m unittest tests.test_rollback -q                                  # 登记 v2 → rollback 到 v1 → 交付门按 v1 判红
python3 scripts/dna_audit.py | grep "#5 可回滚"                              # 不再是 [零]
```

**为什么在三分之前**：没有回滚，阶段 5 的数据隔离改判据时不敢动；判据版本与历史已具备，成本低。

**判停**：回放后判据与账本记录的版本不一致 → 停，先修 history 与账本的一致性。

---

## 阶段 4：数据三分（让「盲测不降」可信）

### 4.1 dev 与 test 互斥

**改什么**

- 24 条任务拆成 `dev`（可看、可挖反例）与 `test`（盲、只用于否决），清单进 `sa2/knowledge/data/` 或 bench 自带；
  `scripts/sa2_bench.py` 加 `--split dev|test`，两个集合断言无交集。
- M-A 的"盲测不降"只读 test 集；dev 集涨而 test 不涨即判过拟合（蓝图 §5 第 4 条）。

**验收：**

```
python3 -m unittest tests.test_split -q     # dev ∩ test = ∅，且各自样本数 >= 8
python3 scripts/sa2_bench.py --split test --dry-run --json   # 只含 test 样本
```

**为什么放在这里**：它是 M-A 结论可信的前提，但依赖 bench 入口（阶段 0）与回滚（阶段 3）先就位。

**判停**：test 集 < 8 条 → 读数不下结论，只报"样本不足"。

---

## 阶段 5：拆 PDCA（最后，因为最贵）

### 5.1 把 I/O 与提示词搬出去

**改什么**

- 抽 `sa2/loop/artifacts.py`：`_write_partial/_write_artifact/_report` 的落盘与报告；
- 抽 `sa2/forge/prompts.py`：`_context/_with_material/_requirements/_feedback` 的提示词拼装；
- `PDCA` 只留编排：声明→前置门→逐阶段→交付门→证据门。

**验收：**

```
test "$(wc -l < sa2/loop/pdca.py)" -le 250
python3 -m unittest tests.test_sa2_loop tests.test_sa2_liveness -q
```

**为什么最后**：这是唯一"能跑就先不动"的模块，拆错的代价最高；前五个阶段的读数会告诉你它是否真的挡路。

**判停**：行数达标但 loop 测试出现 flaky → 回滚，形态优先于行数。

---

## 6. 不做清单（有依据，不是懒）

| 不做 | 依据 |
|---|---|
| 阶段内并行边界 | `docs/SA2.md:110` 明写"不应先做"，会重演 1.0 的 38 次调用 |
| 跨域 M-B | 先有 M-A 的 test 读数，否则"换验证器"无判据可依 |
| 千级 agent 编制 | 蓝图 §11：10³–10⁴ 并发未实测 |
| 重写 `core/` | 红线附近，收益/风险比最差；四件骨架里 core 只占两件 |

---

## 7. 一页总表

| 阶段 | 主改动 | 判红命令 | 现在预期 |
|---|---|---|---|
| 0 | bench 入口 + 基线入库 + 文档纠偏 | `scripts/sa2_bench.py --min-l2 0.6` | 退出 1（当前 0.167） |
| 1 | resume 从事件重建 | `tests.test_ledger_replay` | 红（无重建入口） |
| 2 | forge 不持有 Judge | `grep Judge sa2/forge` | 红（`criteria.py:88`） |
| 3 | rollback + 灰度 | `dna_audit` #5 | 红（零） |
| 4 | dev/test 互斥 | `tests.test_split` | 红（无三分） |
| 5 | 拆 PDCA | `wc -l pdca.py <= 250` | 红（443） |

顺序理由一句话：**读数不可复跑时，一切架构判断都是自证**；所以先立 bench，再修崩溃地基（账本），
然后封红线（不改行为），再用回滚与三分把 M-A 的结论钉住，最后才动最贵的拆分。

---

## 8. 人审与边界

- 本方案不改任何代码；`docs/`、`sa2/`、`tests/`、`scripts/` 的每一处改动都需人审后执行。
- 每个阶段的验收命令都要先在当前树上跑到红，再改，再跑到绿——红不出来的阶段，说明判据写错了。
- 本轮未验证：各阶段改动能否真落地、bench 的真实抓错率、跨域 M-B。
