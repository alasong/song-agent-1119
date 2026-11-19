# reports/ —— 证据目录

规则只有一条：**只增不改**。这里的文件是「当时读数是多少」的唯一凭据，不许覆盖、不许改内容。

## 顶层放什么

| 前缀 | 谁写 | 是什么 |
|---|---|---|
| `bench-*.json` | `scripts/bench.py` | 六条能力判据的一次完整读数 |
| `scheduler-*.json` | `scripts/dispatch_org.py` | 一次派活：角色数、阶段数、交接、验拒、返工 |
| `deliver-*.json` | `scripts/deliver.py` | 一次交付决策：单 agent 还是组队、为什么 |
| `ab-*.json` / `ab-quality-*.json` | `scripts/ab_test.py` | 同任务 A/B 对照；带 `quality` 的是盲评分 |
| `deliverable-stability-*.json` | `scripts/stability_deliverable.py` | 同任务三次交付的重合率与章节骨架 |
| `kb-fetch-*.json` / `rag-*.json` | `scripts/kb_fetch_demo.py` / `rag_demo.py` | 知识取用与可溯源 |
| `usage-*.json` | `xm/daemon.py` | 真实 token 用量与预算止损 |
| `m0*.json` | 早期里程碑 | M0a/M0b 阶段读数 |

## 顶层 vs archive/

**顶层只留「文档点名引用的」和「每类最新的那一份」**，其余进 `archive/`。
这样做的原因不是好看：`scripts/bench.py` 等按 `reports/*.json` 取「最新一份」，
每次中间尝试都堆在顶层会让「最新」变得没有意义。

归档不等于删除——`archive/` 里的文件仍被 `scripts/claim_check.py` 递归检查
（裸称最优、报告判定与读数不符照样判红）。

## 现在的归档内容

`archive/` 里是过程性读数：反复跑出来的 bench、早期 scheduler 派活、换代前的稳定性报告。
结论只由顶层那份最新读数代表；归档文件仍参与 `claim_check.py` 的检查。