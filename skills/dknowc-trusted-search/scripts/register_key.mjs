#!/usr/bin/env node
// 国内 MaaS headless 注册助手（供 skillhub skill 调用；纯 node，内置 fetch，无三方依赖）。
//   node register_key.mjs [--base URL] send     --phone <p>
//   node register_key.mjs [--base URL] register --phone <p> --vcode <c> [--type 11] [--organ ..] [--name ..] [--channel ..] [--source ..] [--password ..] [--new-key] [--no-persist]
//   node register_key.mjs save-key   （MCP 取 Key 路径落盘：密钥经 stdin 或 --api-key 传入，随公文写作 3.7.7 移植）
// 无需 cookie / 加密 / 登录态。注册成功自动把 API Key 写入本机专用配置文件
// ~/.config/dknowc/api_key（XDG，600 权限；Windows %APPDATA%\dknowc\api_key），
// 并清理历史 ~/.zshrc Key 标记块；业务脚本从配置文件直读，无需重启宿主；
// persist 命令可事后手动补持久化。默认打生产，--base 可切测试环境。

import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DEFAULT_BASE = "https://platform.dknowc.cn/auth/home/userAuto";
const DEFAULT_OPEN_BASE = "https://open.dknowc.cn";
const DEFAULT_CHANNEL = "46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05";
const DEFAULT_TYPE = "11";
// 3.7.7 对齐（2026-09-29 用户决策）：source 由 "agent" 改为 skill 名，与 X-Dknowc-Attribution
// 声明的 source 字段同名同义；body 里的 channel 渠道码（UUID 埋点）保持不变，同名不同义、互不影响。
const DEFAULT_SOURCE = "dknowc-trusted-search";
const API_KEY_ENV = "DKNOWC_API_KEY";
const MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login";
const FALLBACK_REGISTER_URL = MAAS_PLATFORM_URL;
const KEY_FILE_NAME = "api_key";
// 历史 ~/.zshrc 标记块（1.3.5 迁移：写入配置文件后清理，避免污染 shell 配置）
const ZSHRC_START = "# >>> dknowc trusted search api key >>>";
const ZSHRC_END = "# <<< dknowc trusted search api key <<<";

function apiKeyFilePath() {
  const home = os.homedir();
  if (process.platform === "win32") {
    const appdata = process.env.APPDATA || home;
    return path.join(appdata, "dknowc", KEY_FILE_NAME);
  }
  const xdg = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdg, "dknowc", KEY_FILE_NAME);
}

function maskPhone(phone) {
  const p = String(phone || "");
  return p.length >= 7 ? `${p.slice(0, 3)}****${p.slice(-4)}` : p;
}

function maskKey(apiKey) {
  if (!apiKey) return null;
  if (apiKey.length <= 12) return "***";
  return `${apiKey.slice(0, 7)}...${apiKey.slice(-4)}`;
}

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith("--")) {
      const key = arg.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) {
        out[key] = true;
      } else {
        out[key] = next;
        i++;
      }
    } else {
      out._.push(arg);
    }
  }
  return out;
}

// 来源声明（X-Dknowc-Attribution，仅统计用、不参与鉴权；随公文写作 3.7.7 移植）：
// 读包根 attribution.json + SKILL.md 的 version；读取失败不加头、不阻断请求。
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

async function postJson(url, payload, headers = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: withAttribution({ "Content-Type": "application/json", ...headers }),
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch {
      return { status: false, msg: `非 JSON 响应：${text.slice(0, 200)}` };
    }
  } catch (error) {
    const msg = error && error.message ? error.message : String(error);
    return { status: false, msg: `请求异常：${msg}` };
  } finally {
    clearTimeout(timer);
  }
}

function genPassword() {
  const pools = [
    "ABCDEFGHJKLMNPQRSTUVWXYZ",
    "abcdefghijkmnpqrstuvwxyz",
    "23456789",
    "!@#$%^&*",
  ];
  const pick = (value) => value[Math.floor(Math.random() * value.length)];
  const chars = pools.map(pick);
  const all = pools.join("");
  for (let i = 0; i < 8; i++) chars.push(pick(all));
  for (let i = chars.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

async function createNewApiKey(openBase, existingApiKey, name, remark) {
  const url = `${openBase.replace(/\/$/, "")}/open-api/maas/api-key/create`;
  const result = await postJson(
    url,
    { name, remark },
    { Authorization: `Bearer ${existingApiKey}` },
  );
  const apiKey = result && result.data ? result.data.appKey : "";
  return { result, apiKey };
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function removeLegacyZshrcBlocks() {
  // 迁移：写入配置文件后从 ~/.zshrc 移除历史 Key 标记块（避免污染 shell 配置）
  const zshrcPath = path.join(os.homedir(), ".zshrc");
  try {
    let existing = fs.existsSync(zshrcPath) ? fs.readFileSync(zshrcPath, "utf8") : "";
    if (!existing) return;
    const re = new RegExp(`${escapeRegExp(ZSHRC_START)}[\\s\\S]*?${escapeRegExp(ZSHRC_END)}\\n?`, "m");
    if (re.test(existing)) {
      existing = existing.replace(re, "");
      // 保留 zshrc 原有权限，不强制改 600（2026-09-28 审查修复）
      let mode;
      try { mode = fs.statSync(zshrcPath).mode & 0o777; } catch { mode = 0o600; }
      fs.writeFileSync(zshrcPath, existing, { encoding: "utf8", mode });
    }
  } catch {
    /* 清理失败不阻断：遗留块仍由 api_key.py 的 zshrc 兜底读到 */
  }
}

function writeApiKeyToConfigFile(apiKey) {
  // 写本机专用配置文件（纯文本一行 Key，600 权限）；成功后清理历史 ~/.zshrc 块
  const filePath = apiKeyFilePath();
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
    fs.writeFileSync(filePath, `${String(apiKey).trim()}\n`, { encoding: "utf8", mode: 0o600 });
    removeLegacyZshrcBlocks();
    return { written: true, path: filePath, error: null };
  } catch (error) {
    const msg = error && error.message ? error.message : String(error);
    return { written: false, path: filePath, error: msg };
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  const base = args.base || DEFAULT_BASE;

  if (cmd === "save-key") {
    // 3.7.7 移植：MCP 取 Key 路径的落盘子命令。宿主提供 dknowc-mcp 的 create_api_key 且调用
    // 成功（返回顶层 JSON {"apiKey": "..."}）后，用本命令落盘，用户无需手机号验证码。
    // 密钥来源优先 stdin（printf '%s' "<密钥>" | node register_key.mjs save-key，避免出现在
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
    if (!apiKey.trim() && args["api-key"] && args["api-key"] !== true) apiKey = String(args["api-key"]);
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
    if (!args.phone) {
      console.error("缺少 --phone");
      process.exit(2);
    }
    // 渠道细分：sendMessage 与 register 请求体统一携带 SkillHub 渠道码。
    const result = await postJson(`${base}/sendMessage`, {
      phone: args.phone,
      type: "register",
      channel: args.channel && args.channel !== true ? args.channel : DEFAULT_CHANNEL,
    });
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥
    let userMessage;
    if (result.status) {
      userMessage = `验证码已发送到 ${maskPhone(args.phone)}，请把最新一条短信里的 6 位验证码发我。`;
    } else if (String(result.msg || "").includes("手机号")) {
      userMessage = "这个手机号格式好像不对，麻烦核对一下再发我。";
    } else {
      userMessage = `验证码发送没成功（可能是网络或短信通道问题），可以再试一次；如果连续失败，也可以用网页方式开通：${FALLBACK_REGISTER_URL}`;
    }
    console.log(JSON.stringify({ ...result, user_message: userMessage }));
    if (result.status) console.error("验证码已发送（话术见 user_message，请向用户转述后索取 6 位验证码）。");
    process.exit(result.status ? 0 : 1);
  }

  if (cmd === "register") {
    if (!args.phone || !args.vcode) {
      console.error("缺少 --phone 或 --vcode");
      process.exit(2);
    }

    const payload = {
      phone: args.phone,
      vcode: args.vcode,
      password: args.password && args.password !== true ? args.password : genPassword(),
      type: args.type && args.type !== true ? args.type : DEFAULT_TYPE,
      organ: args.organ && args.organ !== true ? args.organ : "个人",
      name: args.name && args.name !== true ? args.name : "用户",
      apiKeyName: args["apikey-name"] && args["apikey-name"] !== true ? args["apikey-name"] : "agent-key",
      channel: args.channel && args.channel !== true ? args.channel : DEFAULT_CHANNEL,
      source: args.source && args.source !== true ? args.source : DEFAULT_SOURCE,
    };

    const result = await postJson(`${base}/register`, payload);
    const data = result.data || {};
    const ok = Boolean(result.status) && Boolean(data.apiKey);
    let apiKeyToSave = ok ? data.apiKey : "";
    let newKeyCreated = false;
    let newKeyError = null;
    if (ok && args["new-key"]) {
      const keyName = args["new-key-name"] && args["new-key-name"] !== true
        ? args["new-key-name"]
        : payload.apiKeyName;
      const keyRemark = args["new-key-remark"] && args["new-key-remark"] !== true
        ? args["new-key-remark"]
        : "由 SkillHub 深知可信搜索按用户要求重新生成";
      const created = await createNewApiKey(
        args["open-base"] && args["open-base"] !== true ? args["open-base"] : DEFAULT_OPEN_BASE,
        data.apiKey,
        keyName,
        keyRemark,
      );
      if (created.apiKey) {
        apiKeyToSave = created.apiKey;
        newKeyCreated = true;
      } else {
        // 新建失败：沿用原密钥继续（不中断用户任务），newKeyCreated=false 明确区分新旧
        newKeyError = created.result.errmsg || created.result.msg || "新 API Key 创建失败";
      }
    }
    // 注册成功自动持久化到本机专用配置文件 ~/.config/dknowc/api_key（1.3.5 起，对齐公文写作
    // 3.7.5：不再写 ~/.zshrc，避免污染 shell 配置；读取顺序 env→配置文件→历史 zshrc 兜底）。
    // --no-persist 可跳过；persist 命令保留用于事后手动补持久化。
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    // 权益告知（注册赠送 10 万积分 + 实名认证再送 10 万积分）已前移到开通引导（initialize.guide_message / onboarding_scripts S1），
    // 此处只做轻确认，避免成功节点信息过重导致转述截断。
    const cfgWrite = ok && apiKeyToSave && !args["no-persist"]
      ? writeApiKeyToConfigFile(apiKeyToSave)
      : { written: false, path: apiKeyFilePath(), error: null };
    let userMessage;
    if (ok && apiKeyToSave) {
      userMessage = Boolean(data.existed)
        ? `这个手机号之前开通过，已直接找回原来的密钥和额度，不用重新注册。我马上开始检索。`
        : `开通成功，访问密钥已写入本机，注册赠送的 10 万积分已到账。我马上开始检索。`;
      if (newKeyError) {
        userMessage += ` 另外你要求的新密钥生成失败（${newKeyError}），已先沿用现有密钥继续，不影响使用；需要的话稍后再重新生成。`;
      }
    } else if (String(result.msg || "").includes("验证码")) {
      userMessage = `验证码校验没通过（可能是输入有误或已过期）。请核对 ${maskPhone(args.phone)} 最新一条短信的 6 位验证码重新发我；需要我重新发送一条，直接说一声。`;
    } else {
      userMessage = `开通服务暂时没连上（${result.msg || "网络波动"}），可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`;
    }
    console.log(JSON.stringify({
      status: ok && Boolean(apiKeyToSave),
      msg: result.msg,
      url: data.url || null,
      existed: Boolean(data.existed),
      keyCreatedByRegister: Boolean(data.keyCreated),
      newKeyRequested: Boolean(args["new-key"]),
      newKeyCreated,
      user_message: userMessage,
      envName: API_KEY_ENV,
      // 防明文泄漏（对齐公文写作 3.7.4）：注册成功且已持久化时不输出明文 apiKey，
      // 只输出掩码与写入路径——业务脚本从配置文件直读，无需明文；仅写入失败时回退明文供临时注入。
      apiKey: cfgWrite.written ? null : apiKeyToSave,
      apiKeyMasked: maskKey(apiKeyToSave),
      envWriteRequired: false,
      envWriteTarget: cfgWrite.path,
      envWriteSucceeded: Boolean(cfgWrite.written),
      envWriteError: cfgWrite.error,
      envWriteInstruction: cfgWrite.written
        ? `已写入 ${cfgWrite.path}；业务脚本直读该文件，无需重启宿主。`
        : `未能写入 ${cfgWrite.path}，可运行 persist 命令补写，或由 Agent / 平台密钥配置将返回的 apiKey 写入环境变量 ${API_KEY_ENV}。`,
      currentSessionInstruction: `已持久化时初始化会从配置文件直读 Key，无需手动注入；未持久化时用本次返回的 apiKey 临时注入环境变量 ${API_KEY_ENV}，不得向用户展示完整 Key。`,
      newKeyError,
      fallbackRegisterUrl: FALLBACK_REGISTER_URL,
    }));
    process.exit(ok && Boolean(apiKeyToSave) ? 0 : 1);
  }

  if (cmd === "persist") {
    // 手动补持久化：从当前任务临时注入的环境变量（或 --api-key）读取 Key 写入专用配置文件。
    const apiKey = (args["api-key"] && args["api-key"] !== true)
      ? args["api-key"]
      : process.env[API_KEY_ENV] || "";
    if (!apiKey) {
      console.error(`缺少 ${API_KEY_ENV} 环境变量或 --api-key`);
      process.exit(2);
    }
    const cfgWrite = writeApiKeyToConfigFile(apiKey);
    console.log(JSON.stringify({
      status: Boolean(cfgWrite.written),
      envName: API_KEY_ENV,
      envWriteTarget: cfgWrite.path,
      envWriteSucceeded: Boolean(cfgWrite.written),
      envWriteError: cfgWrite.error,
      envWriteInstruction: cfgWrite.written
        ? `已写入 ${cfgWrite.path}；脚本直读该文件，无需重启宿主。`
        : `未能写入 ${cfgWrite.path}，请由 Agent 或平台密钥配置将返回的 apiKey 写入环境变量 ${API_KEY_ENV}。`,
    }));
    process.exit(cfgWrite.written ? 0 : 1);
  }

  console.error("用法: node register_key.mjs <send|register|persist> ...");
  process.exit(2);
}

main();
