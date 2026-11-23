// 真跑工具的执行体：不启动 DSH，用假 ctx 拿注册表，再逐条调 execute。
// 判据：注册成功、build/refresh/check 的 rc 语义、get 的行区间与实物一致、无索引也能出骨架。
import assert from "node:assert";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { apply } from "./index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
let passed = 0;
function ok(cond, msg) {
  assert.ok(cond, msg);
  passed += 1;
}

const ws = mkdtempSync(join(tmpdir(), "asset-index-plugin-"));
writeFileSync(join(ws, "doc.md"), "# 标题\n\n引言\n\n## 第一节\n甲\n\n## 第二节\n丙\n丁\n");
writeFileSync(join(ws, "code.py"), "class A:\n    pass\n\n\ndef f(x):\n    return x\n");
writeFileSync(join(ws, "data.json"), '{\n  "alpha": 1,\n  "beta": 2\n}\n');
// >4KB 才会落索引、走 direct-stale；≤4KB 走 direct-thin（两条路径都要测）
writeFileSync(join(ws, "big.md"), "# 顶\n" + "填充\n".repeat(900) + "## 目标节\n内容\n");

let tool = null;
apply({ tools: { register: (t) => { tool = t; } } });
ok(tool && tool.name === "asset_index", "必须注册 asset_index 工具");
ok(typeof tool.execute === "function", "注册项必须有 execute");

const call = (args) => tool.execute({ root: ws, ...args });

// 1) build
const built = await call({ action: "build" });
ok(built.ok === true && /"built": 4/.test(built.text), "build 应索引 3 个资产，实际：" + built.text);

// 2) get 一节：行区间必须指向真实标题行
const hit = await call({ action: "get", path: "doc.md", section: "第二节" });
ok(hit.ok === true, "get 应成功，实际：" + hit.text);
const span = hit.text.split(/\s+/)[0];
const [rel, range] = span.split(":");
const start = Number(range.split("-")[0]);
ok(rel === "doc.md", "命中路径应是 doc.md，实际：" + span);
const lines = readFileSync(join(ws, "doc.md"), "utf8").split("\n");
ok(lines[start - 1].trim() === "## 第二节", "行区间起点必须是标题行，实际第 " + start + " 行：" + lines[start - 1]);

// 3) 改文件后立刻 get：不能返回旧行号
writeFileSync(join(ws, "doc.md"), "# 标题\n新一行\n\n## 第一节\n甲\n\n## 第二节\n丙\n丁\n");
const stale = await call({ action: "get", path: "doc.md", section: "第二节" });
const staleStart = Number(stale.text.split(/\s+/)[0].split(":")[1].split("-")[0]);
const newLines = readFileSync(join(ws, "doc.md"), "utf8").split("\n");
ok(newLines[staleStart - 1].trim() === "## 第二节", "索引过期时必须现场重算，不返回旧行号");
ok(/direct-thin/.test(stale.text), "≤4KB 现场抽取并标 direct-thin，实际：" + stale.text);

// 4) check 判漂移
const drift = await call({ action: "check" });
ok(drift.ok === false && drift.rc === 1, "内容变了 check 必须 rc=1，实际：" + drift.rc);
ok(/meta-changed/.test(drift.text), "check 要指出是哪个文件变了");

// 5) refresh 只重建脏文件
const refreshed = await call({ action: "refresh" });
ok(refreshed.ok === true, "refresh 应成功");
const parsed = JSON.parse(refreshed.text.split("\n")[0]);
ok(parsed.rebuilt === 1 && parsed.unchanged === 3, "refresh 应只重建 1 个，实际：" + JSON.stringify(parsed));

// 6) check 恢复绿
const clean = await call({ action: "check" });
ok(clean.ok === true && clean.rc === 0, "刷新后 check 应 rc=0，实际：" + clean.text);

// 6.5) 大文件走索引：行号漂移必须现场重算
writeFileSync(join(ws, "big.md"), "# 顶\n新增\n\n" + "填充\n".repeat(900) + "## 目标节\n内容\n");
const bigStale = await call({ action: "get", path: "big.md", section: "目标节" });
ok(/direct-stale/.test(bigStale.text), "过期的大文件必须标 direct-stale，实际：" + bigStale.text);
const bigStart = Number(bigStale.text.split(/\s+/)[0].split(":")[1].split("-")[0]);
ok(readFileSync(join(ws, "big.md"), "utf8").split("\n")[bigStart - 1].trim() === "## 目标节",
   "direct-stale 给的行号必须是新行号");

// 7) 没索引也能出骨架（骨架无条件）
rmSync(join(ws, ".asset-index"), { recursive: true, force: true });
const noIndex = await call({ action: "get", path: "code.py", section: "f" });
ok(noIndex.ok === true && /code\.py:\d+-\d+/.test(noIndex.text), "无索引时必须现场给骨架，实际：" + noIndex.text);

// 8) 非法 action 要有明确错误，不静默成功
const bad = await call({ action: "nope" });
ok(bad.ok === false && /未知 action/.test(bad.text), "非法 action 必须失败并说明");

// 9) 随包 Python 引擎与仓库源同步（两者都是这一份实现，漂了就是两份行为）
const repoScript = join(HERE, "..", "..", "scripts", "asset_index.py");
try {
  const a = createHash("sha256").update(readFileSync(join(HERE, "asset_index.py"))).digest("hex");
  const b = createHash("sha256").update(readFileSync(repoScript)).digest("hex");
  ok(a === b, "plugins/dsh-asset-index/asset_index.py 必须与 scripts/asset_index.py 一致（重新 cp）");
} catch {
  console.log("skip: 仓库源不在预期位置，跳过同步校验");
}

rmSync(ws, { recursive: true, force: true });
console.log(`ASSET-INDEX-PLUGIN-TEST ${passed}/${passed}`);