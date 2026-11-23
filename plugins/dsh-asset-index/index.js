// DSH 工具插件：asset_index —— 把「先骨架 → 增量刷新 → 细节」交给模型直接调用。
// 零依赖：只 import node 内置模块；Python 引擎随包自带（asset_index.py），不依赖任何仓库。
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

export const name = "asset-index";
export const inject = ["tools"];

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(HERE, "asset_index.py");
const PYTHON_CANDIDATES = ["python3", "/opt/homebrew/bin/python3", "/usr/bin/python3"];
const TIMEOUT_MS = 180000;

function pickPython() {
  for (const p of PYTHON_CANDIDATES) {
    if (!p.includes("/")) return p;          // PATH 上的 python3
    if (existsSync(p)) return p;
  }
  return "python3";
}

function runPython(args) {
  return new Promise((resolve) => {
    if (!existsSync(SCRIPT)) {
      resolve({ rc: 127, out: "", err: `引擎不存在：${SCRIPT}` });
      return;
    }
    let child;
    try {
      child = spawn(pickPython(), [SCRIPT, ...args], { env: process.env });
    } catch (e) {
      resolve({ rc: 127, out: "", err: String(e && e.message) });
      return;
    }
    let out = "";
    let err = "";
    const timer = setTimeout(() => child.kill("SIGKILL"), TIMEOUT_MS);
    child.stdout.on("data", (c) => { out += String(c); });
    child.stderr.on("data", (c) => { err += String(c); });
    child.on("error", (e) => {
      clearTimeout(timer);
      resolve({ rc: 127, out, err: `无法启动 python3：${String(e && e.message)}` });
    });
    child.on("close", (code, signal) => {
      clearTimeout(timer);
      resolve({ rc: typeof code === "number" ? code : 1, out, err, signal });
    });
  });
}

function textOf(stdout, stderr) {
  const out = String(stdout || "").trim();
  const err = String(stderr || "").trim();
  return [out, err ? `stderr: ${err}` : ""].filter(Boolean).join("\n");
}

export function apply(ctx) {
  ctx.tools.register({
    name: "asset_index",
    description:
      "项目资产读取的骨架索引：build 全量、refresh 增量（只重算改过的文件）、get 出章节/符号/键的行区间、check 判索引是否漂移。" +
      "任何项目、任何资产同一套协议（代码/文档/JSON/CSV/文本/office）。先 get 拿骨架，再按返回的 path:start-end 读细节，别整读。",
    parameters: {
      type: "object",
      additionalProperties: false,
      required: ["action", "root"],
      properties: {
        action: {
          type: "string",
          enum: ["build", "refresh", "check", "get", "stats"],
          description: "build 全量重建 / refresh 增量刷新 / check 校验漂移 / get 出骨架 / stats 规模读数",
        },
        root: {
          type: "string",
          description: "项目根目录的绝对路径（索引写到 <root>/.asset-index/）",
        },
        path: {
          type: "string",
          description: "get 时必填：相对 root 的文件路径",
        },
        section: {
          type: "string",
          description: "get 时可选：按 label 子串定位一节，返回 path:start-end 直接喂 read",
        },
        first: {
          type: "boolean",
          description: "section 多命中时取第一个；默认报歧义并失败",
        },
        verify_hashes: {
          type: "boolean",
          description: "refresh/check 深检：连 size+mtime 未变的文件也重算 sha（慢，查被保留 mtime 的改动）",
        },
        allow_unverified: {
          type: "boolean",
          description: "check 在只有「验不了」（如 >8MB 无 sha）时也返回成功",
        },
      },
    },
    output: {
      schema: {
        type: "object",
        additionalProperties: false,
        required: ["ok", "action", "rc", "text"],
        properties: {
          ok: { type: "boolean" },
          action: { type: "string" },
          rc: { type: "integer" },
          text: { type: "string" },
        },
      },
      render(_args, value) {
        return [{ type: "text", text: String((value && value.text) || "") }];
      },
    },
    execute: async ({ action, root, path, section, first, verify_hashes, allow_unverified }) => {
      const r = String(root || "").trim();
      if (!r) {
        return { ok: false, action: String(action || ""), rc: 2, text: "root 必填：项目根目录绝对路径" };
      }
      let argv;
      if (action === "get") {
        if (!path) {
          return { ok: false, action, rc: 2, text: "get 需要 path（相对 root 的文件路径）" };
        }
        argv = ["get", String(path), "--root", r];
        if (section) argv.push("--section", String(section));
        if (first) argv.push("--first");
      } else if (action === "build" || action === "stats") {
        argv = [action, "--root", r];
      } else if (action === "refresh") {
        argv = ["refresh", "--root", r];
        if (verify_hashes) argv.push("--verify-hashes");
      } else if (action === "check") {
        argv = ["check", "--root", r];
        if (verify_hashes) argv.push("--verify-hashes");
        if (allow_unverified) argv.push("--allow-unverified");
      } else {
        return {
          ok: false,
          action: String(action || ""),
          rc: 2,
          text: `未知 action：${action}（可选 build/refresh/check/get/stats）`,
        };
      }
      const { rc, out, err } = await runPython(argv);
      let text = textOf(out, err);
      if (action === "check" && rc === 4) {
        text += "\n（exit 4 = 有文件验不了，不是漂移；漂移才是 exit 1）";
      }
      return { ok: rc === 0, action, rc, text: text || "(无输出)" };
    },
  });
}