#!/usr/bin/env node
// 国内 MaaS 注册助手（供 skill 调用；纯 node，内置 fetch，无三方依赖）。
//   node register_key.mjs [--guide URL] challenge --phone <p> [--channel <c>]
//   可选 --clean-zshrc：显式清理 ~/.zshrc 中的历史 Key 标记块（默认不修改该文件）
//     读官方 Agent 注册指引 → 申请一道文字题 → 本机保存会话与题目；退出 0 返回题目，
//     退出 2 表示平台要求人工图片验证（返回 verificationUrl），退出 1 为失败。
//   node register_key.mjs answer --phone <p> --answer <非负整数>
//     提交答案；答对即申请发码。退出 0=已发短信；3=答错换题（JSON 带新 question，需再答）；
//     2=转人工接手；4=发送结果未确认（不重发）；1=失败。
//   node register_key.mjs register --phone <p> --vcode <c> [--type 6] [--organ ..] [--name ..] [--channel ..] [--source ..] [--password ..] [--new-key]
//     可能返回 pending:true（账号已创建、密钥资源准备中）——非错误，稍后同参数重试一次。
//   node register_key.mjs save-key     # 把 MCP create_api_key 拿到的密钥落盘（stdin 优先，或 --api-key）
// 说明：文字题由调用方（Agent）直接计算，本脚本只负责会话、题目状态与提交，不求解。
// 2026-10-29 注册链路改造：平台新增 Agent 注册文字题（先解题再发码，图片验证只作为人工兜底）。
// 旧 /sendMessage 发码入口对 Agent 一律要求图片验证，已由 challenge + answer 取代。
// 2026-10-09 改造仍保留于 register 一步：X-MaaS 客户端观测请求头、错误码族映射、验证链接安全校验。

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
// body 的 source 是注册 API 的合同标记：服务端按 source="agent" 放行"老用户直接返 Key"
// 路径（生产环境可能出现：source=dknowc-ppt-assistant 时返回"用户已存在！"错误，
// source=agent 时正常返回 Key）。它与 X-Dknowc-Attribution 统计声明里的 skill 标识是两个
// 字段：统计声明头的键名为 agentSource（2026-10-09 平台方确认改名，避免与 body 的
// source 混淆），值仍读 attribution.json 的 dknowc-ppt-assistant，不受本值影响。
const DEFAULT_SOURCE = "agent";
// 2026-10-09 注册链路改造：MaaS 客户端观测请求头（X-MaaS-*）用本 Skill 真实包名，不冒充
// 其他客户端；Client-Version 运行时读包根 SKILL.md；Instance-Id 由服务端响应头签发后落盘
// 回传，不自行生成（user-auth maas-1.1.6 契约）。
const MAAS_CLIENT_NAME = "dknowc-ppt-assistant";
const INSTANCE_FILE_NAME = "maas_client_instance";
const API_KEY_ENV = "DKNOWC_API_KEY";
const MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login";
const FALLBACK_REGISTER_URL = MAAS_PLATFORM_URL;
// 2026-10-29 Agent 注册：官方机器可读指引与注册页。指引里 challenge/submit 是相对地址，
// 必须相对「指引的最终响应 URL」解析，保留认证代理前缀（不得相对 SPA 的 #/agent-register 解析）。
const DEFAULT_GUIDE = "https://platform.dknowc.cn/maas/identity-center/maas/login/open-api/maas/identity/v1/agent-registration-guide";

// 端点域名白名单：注册/发码/指引三类地址默认只允许官方域名且必须 HTTPS，
// 防止 --base / --guide / --open-base 把手机号或密钥发往任意主机。
// 本地测试（mock 服务）可用 DKNOWC_ALLOW_ANY_ENDPOINT=1 显式放开。
const ALLOWED_ENDPOINT_HOSTS = new Set(["platform.dknowc.cn", "open.dknowc.cn"]);
function assertEndpointAllowed(rawUrl, flagName) {
  const raw = String(rawUrl || "");
  if (process.env.DKNOWC_ALLOW_ANY_ENDPOINT === "1") return raw;
  let u;
  const fail = (reason) => {
    emit(errorPayload(
      "ENDPOINT_REJECTED",
      null,
      `${flagName} ${reason}。仅允许 HTTPS 的 platform.dknowc.cn / open.dknowc.cn；如确需自定义端点，请设置 DKNOWC_ALLOW_ANY_ENDPOINT=1。`,
    ), 1);
  };
  try { u = new URL(raw); } catch { fail(`不是合法 URL（${raw}）`); }
  if (u.protocol !== "https:" || !ALLOWED_ENDPOINT_HOSTS.has(u.hostname)) {
    fail(`指向非官方主机（${u.protocol}//${u.hostname}）`);
  }
  return raw;
}
// 挑战状态（Cookie / token / attempt / 题目）落盘，供 challenge 与 answer 两次调用之间传递。
// attempt 必须始终使用服务端返回值，刷新题目不增加机会，故本机只做保存、不改写。
const CHALLENGE_STATE_FILE = "maas_agent_challenge.json";
// Key 持久化目标：本机专用配置文件（XDG 规范路径），不再写 ~/.zshrc。
// 3.7.5 迁移：写入新文件成功后，清理 ~/.zshrc 中的历史 Key 块。
const KEY_FILE_NAME = "api_key";
const ZSHRC_START = "# >>> dknowc ppt assistant api key >>>";
const ZSHRC_END = "# <<< dknowc ppt assistant api key <<<";
// 历史 ~/.zshrc 标记块（历史版本与历史产品名）。注意：脚本默认**不修改** ~/.zshrc；
// 仅当用户显式传 --clean-zshrc 时才清理这些块（历史块只作读取兜底，见 api_key.py）。
const LEGACY_BLOCKS = [
  [ZSHRC_START, ZSHRC_END],
  ["# >>> dknowc official doc writer api key >>>", "# <<< dknowc official doc writer api key <<<"],
  ["# >>> dknowc api key >>>", "# <<< dknowc api key <<<"],
];

// 配置目录：默认 ~/.config/dknowc（Windows 为 %APPDATA%\dknowc），可用 DKNOWC_CONFIG_DIR 覆盖。
function configDir() {
  const override = process.env.DKNOWC_CONFIG_DIR;
  if (override && override.trim()) return override.trim();
  const home = os.homedir();
  if (process.platform === "win32") {
    return path.join(process.env.APPDATA || home, "dknowc");
  }
  const xdg = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdg, "dknowc");
}

function apiKeyFilePath() {
  return path.join(configDir(), KEY_FILE_NAME);
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

// —— 2026-10-09 注册链路改造新增（user-auth maas-1.1.6 契约）——

// Client-Instance-Id 持久化：与 api_key 同目录（~/.config/dknowc/maas_client_instance）。
// 值来自服务端响应头签发，仅做回传；读不到/落盘失败都不阻断请求。
function instanceIdFilePath() {
  return path.join(configDir(), INSTANCE_FILE_NAME);
}
function readInstanceId() {
  try { return fs.readFileSync(instanceIdFilePath(), "utf-8").trim() || null; } catch { return null; }
}
function writeInstanceId(id) {
  try {
    fs.mkdirSync(path.dirname(instanceIdFilePath()), { recursive: true, mode: 0o700 });
    fs.writeFileSync(instanceIdFilePath(), `${String(id).trim()}\n`, { encoding: "utf-8", mode: 0o600 });
  } catch { /* 落盘失败不阻断请求 */ }
}

// —— 2026-10-29 Agent 注册链路：文字题 + 人工兜底 ——

// 验证页链接安全校验：必须与指引同源（生产 https://platform.dknowc.cn；测试环境随 --guide），
// 路径以 sms-verification-page 结尾（兼容认证代理前缀），无用户名/密码/query，fragment 仅为
// #token= 后跟 43 位 Base64URL 字符；拒绝编码/路径遍历/其他版本与非规范 URL。
function originOf(url) {
  try { return new URL(String(url)).origin; } catch { return null; }
}
function validateVerificationUrl(rawUrl, guideUrl) {
  const origin = originOf(guideUrl);
  if (!origin) return null;
  try {
    const u = new URL(String(rawUrl || ""));
    if (u.username || u.password || u.search) return null;
    if (u.origin !== origin) return null;
    if (!u.pathname.endsWith("/sms-verification-page")) return null;
    if (!/^#token=[A-Za-z0-9_-]{43}$/.test(u.hash)) return null;
    if (String(rawUrl) !== u.toString()) return null; // 拒绝编码/非规范写法
    return u.toString();
  } catch { return null; }
}

function stateFilePath() {
  return path.join(configDir(), CHALLENGE_STATE_FILE);
}
function readChallengeState() {
  try {
    const raw = fs.readFileSync(stateFilePath(), "utf-8");
    const st = JSON.parse(raw);
    return st && typeof st === "object" ? st : null;
  } catch { return null; }
}
function writeChallengeState(st) {
  try {
    fs.mkdirSync(configDir(), { recursive: true, mode: 0o700 });
    fs.writeFileSync(stateFilePath(), JSON.stringify(st, null, 2) + "\n", { encoding: "utf-8", mode: 0o600 });
    return true;
  } catch { return false; }
}
function clearChallengeState() {
  try { fs.unlinkSync(stateFilePath()); } catch { /* 不存在时忽略 */ }
}
function challengeExpired(st) {
  const exp = Number(st && st.expiresAt);
  if (!Number.isFinite(exp) || exp <= 0) return false;
  return Date.now() >= exp - 5000; // 预留 5 秒余量，避免临界提交
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

// —— 统一来源声明（X-Dknowc-Attribution，按 MaaS 平台方约定的调用来源统计方案）——
// 读包根 attribution.json（kind/source/channel）+ SKILL.md 的 version；仅统计用、
// 不参与鉴权；读取失败返回 null（不加头、不阻断请求）。
// 头内键名用 agentSource（2026-10-09 平台方改名，区别于注册 body 的 source 合同标记）。
function readSkillVersion() {
  // 运行时从包根 SKILL.md 解析版本号（供 X-Dknowc-Attribution 与 X-MaaS-Client-Version 共用）
  try {
    const root = path.resolve(__dirname, "..");
    const m = fs.readFileSync(path.join(root, "SKILL.md"), "utf-8").match(/^version:\s*"?([^"\n]+)"?/m);
    return m ? m[1].trim() : "unknown";
  } catch { return "unknown"; }
}
function buildAttributionHeader() {
  try {
    const root = path.resolve(__dirname, "..");
    const meta = JSON.parse(fs.readFileSync(path.join(root, "attribution.json"), "utf-8"));
    if (!meta.source) return null;
    const parts = [`kind=${meta.kind || "skill"}`, `agentSource=${meta.source}`];
    const v = readSkillVersion();
    if (v !== "unknown") parts.push(`version=${v}`);
    if (meta.channel) parts.push(`channel=${meta.channel}`);
    return parts.join(";");
  } catch { return null; }
}
function withAttribution(headers) {
  const attr = buildAttributionHeader();
  return attr ? { ...headers, "X-Dknowc-Attribution": attr } : headers;
}

// —— 极简 Cookie 会话 ——
// Agent 注册要求「同一会话」完成领题与作答：指引响应下发 sl-session，后续请求必须带回。
// Node fetch 无 Cookie jar，这里只保留 name=value，不处理 Domain/Path 等属性（全部请求同源同路径段）。
function readSetCookies(res) {
  let list = [];
  try {
    if (typeof res.headers.getSetCookie === "function") {
      list = res.headers.getSetCookie();
    } else {
      const raw = res.headers.get("set-cookie");
      if (raw) list = raw.split(/,(?=[^;,]+=)/);
    }
  } catch { list = []; }
  const out = [];
  for (const line of list) {
    const head = String(line).split(";")[0];
    const idx = head.indexOf("=");
    if (idx <= 0) continue;
    const name = head.slice(0, idx).trim();
    const value = head.slice(idx + 1).trim();
    if (!name) continue;
    out.push([name, value]);
  }
  return out;
}
function mergeCookies(jar, pairs) {
  const next = { ...(jar || {}) };
  for (const [k, v] of pairs || []) {
    if (v === "" || v === "deleted") delete next[k];
    else next[k] = v;
  }
  return next;
}
function cookieHeader(jar) {
  const entries = Object.entries(jar || {});
  return entries.length ? entries.map(([k, v]) => `${k}=${v}`).join("; ") : null;
}

// 通用 JSON 请求：返回 { json, finalUrl, setCookies, requestUnknown, httpStatus }。
// requestUnknown=true 表示超时/断网等"结果未确认"情形 —— 发码请求结果未知时不得立即重发。
async function httpJson(method, url, { body, cookies, headers, timeoutMs = 30000 } = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const h = { ...(headers || {}) };
    if (body !== undefined) h["Content-Type"] = "application/json";
    const ck = cookieHeader(cookies);
    if (ck) h["Cookie"] = ck;
    const r = await fetch(url, {
      method,
      headers: h,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
      redirect: "follow",
    });
    const setCookies = readSetCookies(r);
    const text = await r.text();
    let json;
    try { json = JSON.parse(text); }
    catch { json = { status: false, msg: "非JSON响应(前200字符): " + text.slice(0, 200) }; }
    return { json, finalUrl: r.url || url, setCookies, requestUnknown: false, httpStatus: r.status };
  } catch (e) {
    return {
      json: {
        status: false,
        // 失败原因写进 msg 便于定位（DNS/代理/证书/TLS），不包含任何凭据
        msg: "请求异常: " + (e && e.message ? e.message : String(e))
          + (e && e.cause && (e.cause.code || e.cause.message) ? " (" + (e.cause.code || e.cause.message) + ")" : ""),
      },
      setCookies: [],
      requestUnknown: true,
      finalUrl: url,
      httpStatus: 0,
    };
  } finally { clearTimeout(timer); }
}

// 注册链路（register）专用 POST：
// - 携带 X-MaaS 客户端观测请求头（user-auth maas-1.1.6）：Entry-Surface 固定 DIRECT_API、
//   Client-Name 为本 Skill 真实包名、Client-Version 运行时读 SKILL.md、Client-Instance-Id
//   首次不带（服务端响应头签发后落盘，后续请求回传，不自行生成）；
// - 返回 { body, requestUnknown }：requestUnknown=true 表示超时/断网等"结果未确认"情形
//   （发送结果未知时不得立即补发，由调用方按专用话术处理）。
async function post(url, payload) {
  const { json, setCookies, requestUnknown } = await httpJson("POST", url, {
    body: payload,
    headers: withAttribution({
      "X-MaaS-Entry-Surface": "DIRECT_API",
      "X-MaaS-Client-Name": MAAS_CLIENT_NAME,
      "X-MaaS-Client-Version": readSkillVersion(),
      ...(readInstanceId() ? { "X-MaaS-Client-Instance-Id": readInstanceId() } : {}),
    }),
  });
  const issued = setCookies.find(([k]) => k.toLowerCase() === "x-maas-client-instance-id");
  if (issued && issued[1]) writeInstanceId(issued[1]);
  return { body: json, requestUnknown };
}

async function postWithBearer(url, apiKey, payload) {
  const { json } = await httpJson("POST", url, {
    body: payload,
    headers: withAttribution({
      "Authorization": `Bearer ${apiKey}`,
    }),
  });
  return json;
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
    // 不自动修改 ~/.zshrc：历史块只作读取兜底；清理需用户显式 --clean-zshrc
    return { written: true, path: filePath, error: null };
  } catch (e) {
    return { written: false, path: filePath, error: e && e.message ? e.message : String(e) };
  }
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// —— Agent 注册：响应归类 ——
// 平台返回 status:true 只代表"本步成功"：领题成功≠已发码，发码成功≠注册完成。
function emit(obj, code) {
  console.log(JSON.stringify(obj));
  process.exit(code);
}

function handoffPayload(rawUrl, guideUrl, phone) {
  const vUrl = validateVerificationUrl(rawUrl, guideUrl);
  if (!vUrl) {
    return {
      payload: {
        status: false,
        code: "CAPTCHA_LINK_UNAVAILABLE",
        user_message: "这次开通需要先完成一次页面验证，但验证链接校验没有通过（可能已过期或不可用）。跟我说一声，我重新给你申请一个新的验证链接。",
        instruction: "不得展示未通过校验的链接；用户同意后重新调用 challenge 申请。",
      },
      exitCode: 1,
    };
  }
  return {
    payload: {
      status: false,
      code: "HUMAN_REQUIRED",
      fallbackRequired: true,
      verificationUrl: vUrl,
      verificationUrlValidated: true,
      user_message: `短信还没发送。请打开这个验证链接，核对手机号（${maskPhone(phone)}）后点击“验证并发送短信”，按提示完成验证：\n${vUrl}\n收到短信后把 6 位验证码回复给我，我继续开通，不需要重新填写注册表。`,
      instruction: "转人工接手：把 user_message（含链接）原样转述给手机号持有人后暂停；链接一次性、约 10 分钟有效，仅私下展示给本人，不贴群、不写日志。持有人完成验证后不得再次调用 challenge 或 answer 发码。",
    },
    exitCode: 2,
  };
}

function questionPayload(st, extra = {}) {
  const q = st.question || {};
  return {
    status: true,
    flow: "agent-text",
    question: { id: q.id || null, prompt: q.prompt || "", answerFormat: q.answerFormat || "非负整数，不带单位" },
    questionCount: st.questionCount || 1,
    requiredCorrect: st.requiredCorrect || 1,
    attempt: Number(st.attempt) || 1,
    maxAttempts: Number(st.maxAttempts) || 3,
    expiresAt: st.expiresAt || null,
    ...extra,
    instruction: "直接按 question.prompt 计算答案，然后调用 answer --phone <手机号> --answer <非负整数>；不要把题目、token 或答题过程发给用户。",
  };
}

function errorPayload(code, userMessage, instruction) {
  return { status: false, code, user_message: userMessage, instruction };
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const base = assertEndpointAllowed(a.base || DEFAULT_BASE, "--base");
  const cmd = a._[0];

  if (cmd === "save-key") {
    // 3.7.7：MCP 取 Key 路径的落盘子命令。宿主提供 dknowc-mcp 的 create_api_key 且调用
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
    const zshrcCleaned = (w.written && a["clean-zshrc"]) ? (removeLegacyZshrcBlocks(), true) : false;
    console.log(JSON.stringify({
      zshrcCleaned,
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

  // —— 第一步：领题 ——
  if (cmd === "challenge") {
    if (!a.phone || a.phone === true) {
      console.error("缺少 --phone");
      emit(errorPayload("ARGUMENT_MISSING", null, "缺少 --phone，请传入用户手机号后重试。"), 2);
    }
    const phone = String(a.phone).trim();
    if (!/^1[3-9][0-9]{9}$/.test(phone)) {
      emit(errorPayload("PHONE_INVALID", "这个手机号格式好像不对，麻烦核对一下再发我。", "不重发、不换号，等用户提供正确手机号。"), 1);
    }
    const guideUrl = assertEndpointAllowed(a.guide && a.guide !== true ? String(a.guide) : DEFAULT_GUIDE, "--guide");
    const channel = a.channel && a.channel !== true ? String(a.channel) : DEFAULT_CHANNEL;

    // 同号未过期的题直接复用：刷新题目不增加机会、不延长到期时间，也不该重复请求服务端
    const cached = readChallengeState();
    if (cached && cached.phone === phone && cached.question && !challengeExpired(cached)) {
      emit(questionPayload(cached, { reused: true }), 0);
    }

    const g = await httpJson("GET", guideUrl, { headers: withAttribution({}) });
    const guideOk = !g.requestUnknown && g.json && g.json.challenge && g.json.challenge.url;
    if (!guideOk) {
      // 文字题接口未上线或平台临时回退时，回落原有短信直发分支（3.9.3 之前的行为）。
      // 两条路径对用户等价：退出 0=已发码、退出 2=人工验证链接、退出 1=停点；输出带 flow 标明走了哪条。
      const { body: r, requestUnknown } = await post(base + "/sendMessage", { phone, type: "register", channel });
      const lc = String(r.code || (r.data && r.data.code) || "");
      if (lc === "CAPTCHA_REQUIRED") {
        const h = handoffPayload(r.verificationUrl, base, phone);
        emit({ ...h.payload, flow: "legacy" }, h.exitCode);
      }
      if (lc === "SMS_RATE_LIMIT_PHONE" || lc === "SMS_RATE_LIMIT") {
        const secs = Number(r.retryAfterSeconds || (r.data && r.data.retryAfterSeconds) || 0);
        const mins = secs > 0 ? Math.max(1, Math.floor(secs / 60)) : 0;
        emit({
          ...errorPayload(
            "SMS_RATE_LIMIT",
            mins > 0
              ? `验证码发送太频繁了，短信通道要求约 ${mins} 分钟后再试。你先忙别的，想重发时跟我说一声。`
              : "验证码发送太频繁了，稍等几分钟再试；想重发时跟我说一声。",
            "限频停点：等用户明确要求且冷却过后再发起，不自动重试。",
          ),
          flow: "legacy",
        }, 1);
      }
      if (lc === "CAPTCHA_LINK_UNAVAILABLE" || lc === "CAPTCHA_REPLAY") {
        emit({
          ...errorPayload(
            "CAPTCHA_LINK_UNAVAILABLE",
            "刚才的验证链接已过期或已使用。跟我说一声，我重新给你申请一个新的验证链接。",
            "不重复提交旧链接；用户确认后重新发起。",
          ),
          flow: "legacy",
        }, 1);
      }
      if (lc === "CAPTCHA_REJECTED" || lc === "CAPTCHA_BUSY" || lc === "CAPTCHA_STATE_UNAVAILABLE") {
        emit({
          ...errorPayload(
            "CAPTCHA_REJECTED",
            "这次验证没有通过（或验证服务暂时不可用）。可以稍后重新打开链接再试；还是不行跟我说，我重新申请一个。",
            "据实说明，不伪造验证结果。",
          ),
          flow: "legacy",
        }, 1);
      }
      if (lc.startsWith("SMS_PROVIDER_")) {
        emit({
          ...errorPayload(
            "SMS_PROVIDER_FAILED",
            `短信服务暂时出了点问题，发不出验证码。可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`,
            "供应商失败停点：不自动重试。",
          ),
          flow: "legacy",
        }, 1);
      }
      if (requestUnknown || String(r.msg || "").startsWith("非JSON响应")) {
        emit({
          status: false,
          code: "RESULT_UNKNOWN",
          resultUnknown: true,
          flow: "legacy",
          user_message: "刚才发送请求的结果没有确认（网络波动）。先看一下手机有没有收到验证码短信：收到了直接把 6 位验证码发我；没收到再跟我说，我重新发。",
          instruction: "结果未确认停点：先等用户确认是否收到短信，未确认前不重新发送。",
          detail: r.msg || null,
        }, 1);
      }
      if (r.status) {
        emit({
          status: true,
          code: "SMS_SENT",
          flow: "legacy",
          user_message: `验证码已发送到 ${maskPhone(phone)}，请把最新一条短信里的 6 位验证码发我。`,
          instruction: "已发码：转述 user_message 后暂停，等用户回复 6 位验证码，再调用 register。不得重复发码，也不需要调用 answer。",
        }, 0);
      }
      if (String(r.msg || "").includes("手机号")) {
        emit({ ...errorPayload("PHONE_INVALID", "这个手机号格式好像不对，麻烦核对一下再发我。", "不重复提交同一号码，等用户核对。"), flow: "legacy" }, 1);
      }
      emit({
        ...errorPayload(
          "SEND_FAILED",
          `验证码发送没成功（可能是网络或短信通道问题），可以再试一次；如果连续失败，也可以用网页方式开通：${FALLBACK_REGISTER_URL}`,
          "失败停点：最多重试一次，超限引导网页开通。",
        ),
        flow: "legacy",
        detail: r.msg || (g.json && g.json.msg) || null,
      }, 1);
    }
    const guideFinal = g.finalUrl || guideUrl;
    let challengeUrl;
    let submitUrl;
    try {
      challengeUrl = new URL(String(g.json.challenge.url), guideFinal).toString();
      submitUrl = new URL(String(g.json.submit && g.json.submit.url ? g.json.submit.url : "./agent-registration-send"), guideFinal).toString();
    } catch {
      emit(errorPayload(
        "GUIDE_INVALID",
        `开通服务暂时不可用，可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`,
        "指引地址解析失败，不要自行拼接其他地址。",
      ), 1);
    }

    let jar = mergeCookies({}, g.setCookies);
    const headers = withAttribution({
      "X-MaaS-Entry-Surface": "DIRECT_API",
      "X-MaaS-Client-Name": MAAS_CLIENT_NAME,
      "X-MaaS-Client-Version": readSkillVersion(),
    });

    let r = await httpJson("POST", challengeUrl, { body: { phone, channel }, cookies: jar, headers });
    jar = mergeCookies(jar, r.setCookies);
    // 个别环境要求显式用途；服务端未接受时补一次 purpose，仍失败按错误码处理（不循环重试）
    if (r.json && r.json.status === false && /用途/.test(String(r.json.msg || ""))) {
      r = await httpJson("POST", challengeUrl, { body: { phone, channel, purpose: "register" }, cookies: jar, headers });
      jar = mergeCookies(jar, r.setCookies);
    }

    const j = r.json || {};
    if (j.status === true && j.question) {
      const st = {
        phone,
        guideUrl: guideFinal,
        challengeUrl,
        submitUrl,
        cookies: jar,
        challengeToken: j.challengeToken || null,
        attempt: Number(j.attempt) || 1,
        maxAttempts: Number(j.maxAttempts) || 3,
        expiresAt: Number(j.expiresAt) || null,
        questionCount: Number(j.questionCount) || 1,
        requiredCorrect: Number(j.requiredCorrect) || 1,
        question: j.question,
        createdAt: new Date().toISOString(),
      };
      writeChallengeState(st);
      emit(questionPayload(st), 0);
    }
    if (j.fallbackRequired === true || j.code === "AGENT_TEXT_FAILED") {
      const h = handoffPayload(j.verificationUrl, guideFinal, phone);
      emit(h.payload, h.exitCode);
    }
    if (j.code === "SMS_RATE_LIMIT") {
      const secs = Number(j.retryAfterSeconds || (j.data && j.data.retryAfterSeconds) || 0);
      const mins = secs > 0 ? Math.max(1, Math.floor(secs / 60)) : 0;
      emit(errorPayload(
        "SMS_RATE_LIMIT",
        mins > 0
          ? `验证码发送太频繁了，短信通道要求约 ${mins} 分钟后再试。你先忙别的，想重发时跟我说一声。`
          : "验证码发送太频繁了，稍等几分钟再试；想重发时跟我说一声。",
        "限频停点：等用户明确要求且冷却过后再领题，不自动重试。",
      ), 1);
    }
    if (j.code === "AGENT_TEXT_TARGET_LOCKED") {
      emit(errorPayload(
        "AGENT_TEXT_TARGET_LOCKED",
        `这个手机号的开通请求有点频繁，需要稍后再试；想马上用的话可以走网页方式开通：${FALLBACK_REGISTER_URL}`,
        "目标锁定：本轮停止，不换手机号、不换会话、不换接口绕过。",
      ), 1);
    }
    if (r.requestUnknown) {
      emit({
        ...errorPayload(
          "RESULT_UNKNOWN",
          "刚才的请求结果没有确认（网络波动）。先等一下，我稍后再试；如果手机收到了验证码短信，直接发我。",
          "结果未确认：不并发、不立即重试；等用户确认或稍后单次重试。",
        ),
        requestUnknown: true,
        detail: (r && r.json && r.json.msg) || null,
      }, 1);
    }
    if (j.code === "SMS_REQUEST_REJECTED") {
      emit(errorPayload(
        "SMS_REQUEST_REJECTED",
        "这个手机号这次没能通过开通校验，麻烦核对一下号码再发我。",
        "不重复提交同一号码，等用户核对后再领题。",
      ), 1);
    }
    emit(errorPayload(
      "AGENT_TEXT_UNAVAILABLE",
      `开通服务暂时不可用，可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`,
      "服务不可用：本轮停止，不绕过、不切换其他接口。",
    ), 1);
  }

  // —— 第二步：作答（答案由 Agent 计算后传入）——
  if (cmd === "answer") {
    const st = readChallengeState();
    if (!st) {
      emit(errorPayload(
        "CHALLENGE_MISSING",
        null,
        "本机没有进行中的题目：先调用 challenge 领取题目。",
      ), 1);
    }
    if (a.phone && a.phone !== true && String(a.phone).trim() !== st.phone) {
      emit(errorPayload(
        "PHONE_MISMATCH",
        null,
        "传入手机号与当前题目不一致：请用同一手机号，或重新调用 challenge。",
      ), 1);
    }
    if (challengeExpired(st)) {
      clearChallengeState();
      emit(errorPayload(
        "CHALLENGE_EXPIRED",
        "刚才那道题已经过期了，我重新给你申请一次。",
        "题目过期：重新调用 challenge（新题、新 attempt），不要沿用旧 token。",
      ), 1);
    }
    const rawAnswer = a.answer;
    const answer = rawAnswer === undefined || rawAnswer === true ? "" : String(rawAnswer).trim();
    if (!/^(0|[1-9][0-9]*)$/.test(answer)) {
      emit(errorPayload(
        "ANSWER_INVALID",
        null,
        "答案必须是非负整数字符串（不带单位、空格、小数、负号或前导零；零写 \"0\"）。重新计算后再次调用 answer。",
      ), 1);
    }

    const headers = withAttribution({
      "X-MaaS-Entry-Surface": "DIRECT_API",
      "X-MaaS-Client-Name": MAAS_CLIENT_NAME,
      "X-MaaS-Client-Version": readSkillVersion(),
    });
    const r = await httpJson("POST", st.submitUrl, {
      body: { challengeToken: st.challengeToken, attempt: Number(st.attempt), answer },
      cookies: st.cookies,
      headers,
    });
    const jar = mergeCookies(st.cookies, r.setCookies);
    const j = r.json || {};

    if (j.status === true) {
      clearChallengeState();
      emit({
        status: true,
        code: "SMS_SENT",
        flow: "agent-text",
        user_message: `验证码已发送到 ${maskPhone(st.phone)}，请把最新一条短信里的 6 位验证码发我。`,
        instruction: "已发码：转述 user_message 后暂停，等用户回复 6 位验证码，再调用 register。不得重复发码。",
      }, 0);
    }

    if (j.code === "AGENT_TEXT_RETRY") {
      const nc = j.nextChallenge || j.challenge || null;
      const nq = nc && nc.question;
      if (nc && nq) {
        const next = {
          ...st,
          cookies: jar,
          challengeToken: nc.challengeToken || nc.token || st.challengeToken,
          attempt: Number(nc.attempt) || Number(st.attempt) + 1,
          maxAttempts: Number(nc.maxAttempts) || Number(st.maxAttempts) || 3,
          expiresAt: Number(nc.expiresAt) || st.expiresAt,
          question: nq,
          lastRetryAt: new Date().toISOString(),
        };
        writeChallengeState(next);
        emit(questionPayload(next, { retry: true }), 3);
      }
      emit(errorPayload(
        "AGENT_TEXT_RETRY",
        null,
        "服务端要求换题但未返回可用新题：本轮停止，重新调用 challenge；不要重置 attempt。",
      ), 1);
    }

    if (j.fallbackRequired === true || j.code === "AGENT_TEXT_FAILED") {
      const h = handoffPayload(j.verificationUrl, st.guideUrl || DEFAULT_GUIDE, st.phone);
      clearChallengeState();
      emit(h.payload, h.exitCode);
    }

    if (j.code === "SMS_RATE_LIMIT" || j.code === "AGENT_TEXT_TARGET_LOCKED" || j.code === "AGENT_TEXT_UNAVAILABLE") {
      clearChallengeState();
      const msg = j.code === "SMS_RATE_LIMIT"
        ? "验证码发送太频繁了，稍等几分钟再试；想重发时跟我说一声。"
        : j.code === "AGENT_TEXT_TARGET_LOCKED"
          ? `这个手机号的开通请求有点频繁，需要稍后再试；想马上用的话可以走网页方式开通：${FALLBACK_REGISTER_URL}`
          : `开通服务暂时不可用，可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`;
      emit(errorPayload(j.code, msg, "本轮终止：不换会话、不换手机号、不换接口绕过。"), 1);
    }

    if (r.requestUnknown) {
      // 保留状态：结果未知时由用户决定是否重试，脚本不自动重发
      emit({
        status: false,
        code: "RESULT_UNKNOWN",
        resultUnknown: true,
        user_message: "刚才发送请求的结果没有确认（网络波动）。先看一下手机有没有收到验证码短信：收到了直接把 6 位验证码发我；没收到再跟我说，我重新发。",
        instruction: "结果未确认停点：先等用户确认是否收到短信；未确认前不得再次调用 answer，也不得重新领题发码。",
      }, 4);
    }

    emit(errorPayload(
      j.code || "SEND_FAILED",
      `验证码发送没成功（${j.msg || "网络或短信通道问题"}），可以再试一次；如果连续失败，也可以用网页方式开通：${FALLBACK_REGISTER_URL}`,
      "失败停点：最多重试一次，超限引导网页开通。",
    ), 1);
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
    const { body: r } = await post(base + "/register", payload);
    const data = r.data || {};
    // 2026-10-09（user-auth maas-1.1.6）：registered:true + deliveryStatus:"PENDING"——
    // 账号已创建、Key 资源尚在准备。非错误：不盲目重注册，等用户示意后在短信码有效期内
    // （5 分钟）用同参数重试一次；过期再走重新发码流程。
    if (!data.apiKey && (data.deliveryStatus === "PENDING" || r.registered === true)) {
      console.log(JSON.stringify({
        status: false,
        pending: true,
        msg: r.msg || null,
        // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥
        user_message: "账号已经创建成功，系统正在准备你的访问密钥（一般一两分钟内就好）。稍等后跟我说一声“再试”，我再确认一次；不用重新注册，也不用重新发验证码。",
        instruction: "非错误：不要重新注册、不要重新发码。等用户示意后用同一手机号与同一验证码重试一次 register（短信码 5 分钟有效）；若提示验证码过期，再走重新发码流程。",
      }));
      process.exit(0);
    }
    const ok = Boolean(r.status) && Boolean(data.apiKey);
    let apiKeyToSave = ok ? data.apiKey : "";
    let newKeyCreated = false;
    let newKeyError = null;
    if (ok && a["new-key"]) {
      const keyName = a["new-key-name"] && a["new-key-name"] !== true ? a["new-key-name"] : payload.apiKeyName;
      const keyRemark = a["new-key-remark"] && a["new-key-remark"] !== true
        ? a["new-key-remark"]
        : "由深知可信PPT按用户要求重新生成";
      const { result, apiKey } = await createNewApiKey(
        assertEndpointAllowed(a["open-base"] && a["open-base"] !== true ? a["open-base"] : DEFAULT_OPEN_BASE, "--open-base"),
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
    // 落盘失败时：把明文 Key 写入仅当前用户可读的待用文件（600），stdout 只给路径与掩码，
    // 避免完整密钥出现在对话框/宿主 UI 回显里。Agent 从该文件读取注入环境变量后即可删除。
    const zshrcCleaned = (zshrcWrite.written && a["clean-zshrc"]) ? (removeLegacyZshrcBlocks(), true) : false;
    let pendingKeyFile = null;
    if (ok && apiKeyToSave && !zshrcWrite.written && !a["no-zshrc"]) {
      try {
        const pendingPath = path.join(configDir(), "api_key.pending");
        fs.mkdirSync(configDir(), { recursive: true, mode: 0o700 });
        fs.writeFileSync(pendingPath, `${String(apiKeyToSave).trim()}\n`, { encoding: "utf8", mode: 0o600 });
        pendingKeyFile = pendingPath;
      } catch { /* 临时文件也写不了时，才退回明文输出 */ }
    }
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
    } else if (String(r.msg || "").includes("已存在")) {
      // 老用户但服务端未放行返 Key（生产环境出现过此形态）：据实说明并引导网页
      // 登录，不冒充找回成功、不诱导重复注册。
      userMessage = `这个手机号之前注册过深知账号，这次没能自动取回密钥。可以稍后再试一次，或到平台用手机号验证码登录查看：${FALLBACK_REGISTER_URL}`;
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
      // 只给掩码——脚本输出可能被宿主 UI 回显或模型贴进对话
      apiKey: (apiKeyToSave && !zshrcWrite.written && !a["no-zshrc"] && !pendingKeyFile) ? apiKeyToSave : null,
      pendingKeyFile,
      apiKeyMasked: apiKeyToSave ? `${apiKeyToSave.slice(0, 7)}...${apiKeyToSave.slice(-4)}` : null,
      zshrcCleaned,
      envWriteRequired: Boolean(apiKeyToSave) && !zshrcWrite.written,
      envWriteTarget: zshrcWrite.path,
      envWriteSucceeded: Boolean(zshrcWrite.written),
      envWriteError: zshrcWrite.error,
      envWriteInstruction: zshrcWrite.written
        ? `已写入 ${zshrcWrite.path}；脚本直读该文件，无需重启宿主，本次不再返回明文密钥。`
        : (pendingKeyFile
          ? `未能写入 ${zshrcWrite.path}；明文 Key 已写入仅本用户可读的 ${pendingKeyFile}（600 权限），请由 Agent 读取该文件临时注入环境变量 ${API_KEY_ENV}，用完删除该文件；不得展示给用户、不得写入公开文件。`
          : `未能写入 ${zshrcWrite.path}，本次已在 apiKey 字段返回明文，请由 Agent 临时注入环境变量 ${API_KEY_ENV}（不得展示给用户、不得写入公开文件）。`),
      currentSessionInstruction: `当前任务继续执行初始化时，请用本次返回的 apiKey 临时注入环境变量 ${API_KEY_ENV}，不得向用户展示完整 Key。`,
      newKeyError,
      fallbackRegisterUrl: FALLBACK_REGISTER_URL,
    }));
    process.exit(ok && Boolean(apiKeyToSave) ? 0 : 1);
  }

  console.error("用法: node register_key.mjs <challenge|answer|register|save-key> ...");
  process.exit(2);
}

main();
