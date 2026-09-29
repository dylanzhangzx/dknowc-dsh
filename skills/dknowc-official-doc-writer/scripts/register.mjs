#!/usr/bin/env node
// 国内 MaaS headless 注册助手（供 skillhub skill 调用；纯 node，内置 fetch，无三方依赖）。
//   node register.mjs [--base URL] send     --phone <p>
//   node register.mjs [--base URL] register --phone <p> --vcode <c> [--type 6] [--organ ..] [--name ..] [--channel ..] [--source ..] [--password ..] [--new-key]
//   node register.mjs save-key     # 3.7.7：把 MCP create_api_key 拿到的密钥落盘（stdin 优先，或 --api-key）
// 无需 cookie / 加密 / 登录态。默认打生产，--base 可切测试环境。

import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DEFAULT_BASE = "https://platform.dknowc.cn/auth/home/userAuto";
const DEFAULT_OPEN_BASE = "https://open.dknowc.cn";
const DEFAULT_CHANNEL = "46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05";
const DEFAULT_TYPE = "6";
// 2026-09-29 调整：与统一来源声明（X-Dknowc-Attribution）的 source 对齐，
// 不再用旧值 "agent"（与"来源统计最终方案 V1.0"的字段语义冲突）。
const DEFAULT_SOURCE = "dknowc-official-doc-writer";
const API_KEY_ENV = "DKNOWC_API_KEY";
const MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login";
const FALLBACK_REGISTER_URL = MAAS_PLATFORM_URL;
// Key 持久化目标：本机专用配置文件（XDG 规范路径），不再写 ~/.zshrc。
// 3.7.5 迁移：写入新文件成功后，清理 ~/.zshrc 中的历史 Key 块。
const KEY_FILE_NAME = "api_key";
const ZSHRC_START = "# >>> dknowc official doc writer api key >>>";
const ZSHRC_END = "# <<< dknowc official doc writer api key <<<";
// 历史 ~/.zshrc 标记块（含旧名），迁移期统一清理
const LEGACY_BLOCKS = [
  [ZSHRC_START, ZSHRC_END],
  ["# >>> dknowc api key >>>", "# <<< dknowc api key <<<"],
];

function apiKeyFilePath() {
  const home = os.homedir();
  if (process.platform === "win32") {
    const appdata = process.env.APPDATA || home;
    return path.join(appdata, "dknowc", KEY_FILE_NAME);
  }
  const xdg = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdg, "dknowc", KEY_FILE_NAME);
}

function removeLegacyZshrcBlocks() {
  // 迁移：从 ~/.zshrc 移除历史 Key 标记块（避免污染 shell 配置）
  const zshrcPath = path.join(os.homedir(), ".zshrc");
  try {
    let existing = fs.existsSync(zshrcPath) ? fs.readFileSync(zshrcPath, "utf8") : "";
    if (!existing) return;
    let changed = false;
    for (const [start, end] of LEGACY_BLOCKS) {
      const re = new RegExp(`${escapeRegExp(start)}[\\s\\S]*?${escapeRegExp(end)}\\n?`, "m");
      if (re.test(existing)) { existing = existing.replace(re, ""); changed = true; }
    }
    if (changed) fs.writeFileSync(zshrcPath, existing, { encoding: "utf8", mode: 0o600 });
  } catch (e) { /* 清理失败不阻断写入流程 */ }
}

function maskPhone(phone) {
  const p = String(phone || "");
  return p.length >= 7 ? `${p.slice(0, 3)}****${p.slice(-4)}` : p;
}

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) { out[key] = true; }
      else { out[key] = next; i++; }
    } else { out._.push(a); }
  }
  return out;
}

// —— 统一来源声明（X-Dknowc-Attribution，2026-09-29 与开发定稿《来源统计最终方案 V1.0》）——
// 读包根 attribution.json（kind/source/channel）+ SKILL.md 的 version；仅统计用、
// 不参与鉴权；读取失败返回 null（不加头、不阻断请求）。
function buildAttributionHeader() {
  try {
    const root = path.resolve(__dirname, "..");
    const meta = JSON.parse(fs.readFileSync(path.join(root, "attribution.json"), "utf-8"));
    if (!meta.source) return null;
    const parts = [`kind=${meta.kind || "skill"}`, `source=${meta.source}`];
    try {
      const m = fs.readFileSync(path.join(root, "SKILL.md"), "utf-8").match(/^version:\s*"?([^"\n]+)"?/m);
      if (m) parts.push(`version=${m[1].trim()}`);
    } catch {}
    if (meta.channel) parts.push(`channel=${meta.channel}`);
    return parts.join(";");
  } catch { return null; }
}
function withAttribution(headers) {
  const attr = buildAttributionHeader();
  return attr ? { ...headers, "X-Dknowc-Attribution": attr } : headers;
}

async function post(url, payload) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 30000);
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: withAttribution({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
      signal: ctl.signal,
    });
    const text = await r.text();
    try { return JSON.parse(text); }
    catch { return { status: false, msg: "非JSON响应(前200字符): " + text.slice(0, 200) }; }
  } catch (e) {
    return { status: false, msg: "请求异常: " + (e && e.message ? e.message : String(e)) };
  } finally { clearTimeout(timer); }
}

async function postWithBearer(url, apiKey, payload) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 30000);
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: withAttribution({
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      }),
      body: JSON.stringify(payload),
      signal: ctl.signal,
    });
    const text = await r.text();
    try { return JSON.parse(text); }
    catch { return { code: r.status, errmsg: "非JSON响应(前200字符): " + text.slice(0, 200) }; }
  } catch (e) {
    return { code: 0, errmsg: "请求异常: " + (e && e.message ? e.message : String(e)) };
  } finally { clearTimeout(timer); }
}

function genPassword() {
  // 8-32 位，含大写/小写/数字/特殊至少 3 类
  const pools = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789", "!@#$%^&*"];
  const pick = (s) => s[Math.floor(Math.random() * s.length)];
  let chars = pools.map(pick);                       // 每类至少一个
  const all = pools.join("");
  for (let i = 0; i < 8; i++) chars.push(pick(all)); // 补到 12 位
  for (let i = chars.length - 1; i > 0; i--) {       // 洗牌
    const j = Math.floor(Math.random() * (i + 1));
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

async function createNewApiKey(openBase, existingApiKey, name, remark) {
  const result = await postWithBearer(
    openBase.replace(/\/$/, "") + "/open-api/maas/api-key/create",
    existingApiKey,
    { name, remark },
  );
  const apiKey = result && result.data ? result.data.appKey : "";
  return { result, apiKey };
}

function writeApiKeyToConfigFile(apiKey) {
  // 写本机专用配置文件（纯文本一行 Key，600 权限）；成功后清理历史 ~/.zshrc 块
  const filePath = apiKeyFilePath();
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
    fs.writeFileSync(filePath, `${String(apiKey).trim()}\n`, { encoding: "utf8", mode: 0o600 });
    removeLegacyZshrcBlocks();
    return { written: true, path: filePath, error: null };
  } catch (e) {
    return { written: false, path: filePath, error: e && e.message ? e.message : String(e) };
  }
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const base = a.base || DEFAULT_BASE;
  const cmd = a._[0];

  if (cmd === "save-key") {
    // 3.7.7：MCP 取 Key 路径的落盘子命令。宿主提供 dknowc-mcp 的 create_api_key 且调用
    // 成功（返回顶层 JSON {"apiKey": "..."}）后，用本命令落盘，用户无需手机号验证码。
    // 密钥来源优先 stdin（printf '%s' "<密钥>" | node register.mjs save-key，避免出现在
    // 命令行参数里），其次 --api-key；仅接受 sk- 开头。落盘复用 writeApiKeyToConfigFile
    // （600 权限 + 清理历史 ~/.zshrc 块），与手机号注册路径同一份持久化逻辑。
    let apiKey = "";
    try {
      if (!process.stdin.isTTY) {
        const chunks = [];
        for await (const c of process.stdin) chunks.push(c);
        apiKey = Buffer.concat(chunks).toString("utf-8");
      }
    } catch { /* stdin 读取失败时回退 --api-key */ }
    if (!apiKey.trim() && a["api-key"] && a["api-key"] !== true) apiKey = String(a["api-key"]);
    apiKey = apiKey.trim();
    if (!apiKey.startsWith("sk-") || apiKey.length < 20) {
      console.log(JSON.stringify({
        status: false,
        msg: "密钥格式不符（应为 sk- 开头的 MaaS API Key），请确认调用的是 create_api_key 的返回值",
      }));
      process.exit(1);
    }
    const w = writeApiKeyToConfigFile(apiKey);
    console.log(JSON.stringify({
      status: w.written,
      envWriteSucceeded: w.written,
      envWriteTarget: w.path,
      error: w.error || null,
      // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥
      user_message: w.written
        ? "已通过你的深知可信工作台授权直接开通搜索功能，无需手机号验证，马上开始检索。"
        : "密钥保存到本机时出现问题，需要改用手机号验证码方式开通。",
    }));
    process.exit(w.written ? 0 : 1);
  }

  if (cmd === "send") {
    if (!a.phone) { console.error("缺少 --phone"); process.exit(2); }
    // 渠道细分：sendMessage 与 register 请求体统一携带 SkillHub 渠道码。
    const channel = a.channel && a.channel !== true ? a.channel : DEFAULT_CHANNEL;
    const r = await post(base + "/sendMessage", { phone: a.phone, type: "register", channel });
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥
    let userMessage;
    if (r.status) {
      userMessage = `验证码已发送到 ${maskPhone(a.phone)}，请把最新一条短信里的 6 位验证码发我。`;
    } else if (String(r.msg || "").includes("手机号")) {
      userMessage = "这个手机号格式好像不对，麻烦核对一下再发我。";
    } else {
      userMessage = `验证码发送没成功（可能是网络或短信通道问题），可以再试一次；如果连续失败，也可以用网页方式开通：${FALLBACK_REGISTER_URL}`;
    }
    console.log(JSON.stringify({ ...r, user_message: userMessage }));
    if (r.status) console.error("验证码已发送（话术见 user_message，请向用户转述后索取 6 位验证码）。");
    process.exit(r.status ? 0 : 1);
  }

  if (cmd === "register") {
    if (!a.phone || !a.vcode) { console.error("缺少 --phone 或 --vcode"); process.exit(2); }
    const payload = {
      phone: a.phone,
      vcode: a.vcode,
      password: a.password && a.password !== true ? a.password : genPassword(),
      type: a.type && a.type !== true ? a.type : DEFAULT_TYPE,
      organ: a.organ && a.organ !== true ? a.organ : "个人",
      name: a.name && a.name !== true ? a.name : "用户",
      apiKeyName: a["apikey-name"] && a["apikey-name"] !== true ? a["apikey-name"] : "agent-key",
    };
    payload.channel = a.channel && a.channel !== true ? a.channel : DEFAULT_CHANNEL;
    payload.source = a.source && a.source !== true ? a.source : DEFAULT_SOURCE;
    const r = await post(base + "/register", payload);
    const data = r.data || {};
    const ok = Boolean(r.status) && Boolean(data.apiKey);
    let apiKeyToSave = ok ? data.apiKey : "";
    let newKeyCreated = false;
    let newKeyError = null;
    if (ok && a["new-key"]) {
      const keyName = a["new-key-name"] && a["new-key-name"] !== true ? a["new-key-name"] : payload.apiKeyName;
      const keyRemark = a["new-key-remark"] && a["new-key-remark"] !== true
        ? a["new-key-remark"]
        : "由 SkillHub 深知公文写作按用户要求重新生成";
      const { result, apiKey } = await createNewApiKey(
        a["open-base"] && a["open-base"] !== true ? a["open-base"] : DEFAULT_OPEN_BASE,
        data.apiKey,
        keyName,
        keyRemark,
      );
      if (apiKey) {
        apiKeyToSave = apiKey;
        newKeyCreated = true;
      } else {
        // 新建失败：沿用原密钥继续（不中断用户任务），newKeyCreated=false 明确区分新旧
        newKeyError = result.errmsg || result.msg || "新 API Key 创建失败";
      }
    }
    const zshrcWrite = ok && apiKeyToSave && !a["no-zshrc"]
      ? writeApiKeyToConfigFile(apiKeyToSave)
      : { written: false, path: apiKeyFilePath(), error: null };
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    // 权益告知（注册赠送 10 万积分 + 实名认证再送 10 万积分）已前移到开通引导
    // （initialize.guide_message / onboarding_scripts S1），此处只做轻确认，避免成功节点信息过重导致转述截断。
    let userMessage;
    if (ok && apiKeyToSave) {
      userMessage = Boolean(data.existed)
        ? `这个手机号之前开通过，已直接找回原来的密钥和积分，不用重新注册。我马上开始检索。`
        : `开通成功，访问密钥已写入本机，注册赠送的 10 万积分已到账。我马上开始检索。`;
      if (newKeyError) {
        userMessage += ` 另外你要求的新密钥生成失败（${newKeyError}），已先沿用现有密钥继续，不影响使用；需要的话稍后再重新生成。`;
      }
    } else if (String(r.msg || "").includes("验证码")) {
      userMessage = `验证码校验没通过（可能是输入有误或已过期）。请核对 ${maskPhone(a.phone)} 最新一条短信的 6 位验证码重新发我；需要我重新发送一条，直接说一声。`;
    } else {
      userMessage = `开通服务暂时没连上（${r.msg || "网络波动"}），可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`;
    }
    console.log(JSON.stringify({
      status: ok && Boolean(apiKeyToSave),
      msg: r.msg,
      url: data.url || null,
      existed: Boolean(data.existed),
      keyCreatedByRegister: Boolean(data.keyCreated),
      newKeyRequested: Boolean(a["new-key"]),
      newKeyCreated,
      user_message: userMessage,
      envName: API_KEY_ENV,
      // 明文 Key 只在"未写入本机配置文件、必须靠它临时注入环境变量"时才输出，其余情况
      // 只给掩码——脚本输出可能被宿主 UI 回显或模型贴进对话（2026-09-21 修复）
      apiKey: (apiKeyToSave && !zshrcWrite.written && !a["no-zshrc"]) ? apiKeyToSave : null,
      apiKeyMasked: apiKeyToSave ? `${apiKeyToSave.slice(0, 7)}...${apiKeyToSave.slice(-4)}` : null,
      envWriteRequired: Boolean(apiKeyToSave) && !zshrcWrite.written,
      envWriteTarget: zshrcWrite.path,
      envWriteSucceeded: Boolean(zshrcWrite.written),
      envWriteError: zshrcWrite.error,
      envWriteInstruction: zshrcWrite.written
        ? `已写入 ${zshrcWrite.path}；脚本直读该文件，无需重启宿主，本次不再返回明文密钥。`
        : `未能写入 ${zshrcWrite.path}，本次已在 apiKey 字段返回明文，请由 Agent 临时注入环境变量 ${API_KEY_ENV}（不得展示给用户、不得写入公开文件）。`,
      currentSessionInstruction: `当前任务继续执行初始化时，请用本次返回的 apiKey 临时注入环境变量 ${API_KEY_ENV}，不得向用户展示完整 Key。`,
      newKeyError,
      fallbackRegisterUrl: FALLBACK_REGISTER_URL,
    }));
    process.exit(ok && Boolean(apiKeyToSave) ? 0 : 1);
  }

  console.error("用法: node register.mjs <send|register> ...");
  process.exit(2);
}

main();
