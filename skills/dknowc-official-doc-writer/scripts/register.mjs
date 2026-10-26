#!/usr/bin/env node
// 国内 MaaS headless 注册助手（供 skillhub skill 调用；纯 node，内置 fetch，无三方依赖）。
//   node register.mjs [--base URL] send     --phone <p>
//     退出码三态：0=短信已发送；2=需用户在验证页完成行为验证（CAPTCHA_REQUIRED，短信尚未发送）；1=错误。
//   node register.mjs [--base URL] register --phone <p> --vcode <c> [--type 6] [--organ ..] [--name ..] [--channel ..] [--source ..] [--password ..] [--new-key]
//     可能返回 pending:true（账号已创建、密钥资源准备中）——非错误，稍后同参数重试一次。
//   node register.mjs save-key     # 3.7.7：把 MCP create_api_key 拿到的密钥落盘（stdin 优先，或 --api-key）
// 无需 cookie / 加密 / 登录态。默认打生产，--base 可切测试环境。
// 2026-10-09 注册链路改造（user-auth maas-1.1.6）：sendMessage 两分支（直发/验证链接）、
// X-MaaS 客户端观测请求头、错误码族映射、验证链接安全校验，详见各分支内注释。

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
// body 的 source 是注册 API 的合同标记：服务端按 source="agent" 放行"老用户直接返 Key"
// 路径（生产环境可能出现：source=dknowc-official-doc-writer 时返回"用户已存在！"错误，
// source=agent 时正常返回 Key）。它与 X-Dknowc-Attribution 统计声明里的 skill 标识是两个
// 字段：统计声明头的键名为 agentSource（2026-10-09 平台方确认改名，避免与 body 的
// source 混淆），值仍读 attribution.json 的 dknowc-official-doc-writer，不受本值影响。
const DEFAULT_SOURCE = "agent";
// 2026-10-09 注册链路改造：MaaS 客户端观测请求头（X-MaaS-*）用本 Skill 真实包名，不冒充
// 其他客户端；Client-Version 运行时读包根 SKILL.md；Instance-Id 由服务端响应头签发后落盘
// 回传，不自行生成（user-auth maas-1.1.6 契约）。
const MAAS_CLIENT_NAME = "dknowc-official-doc-writer";
const INSTANCE_FILE_NAME = "maas_client_instance";
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

// —— 2026-10-09 注册链路改造新增（user-auth maas-1.1.6 契约）——

// Client-Instance-Id 持久化：与 api_key 同目录（~/.config/dknowc/maas_client_instance）。
// 值来自服务端响应头签发，仅做回传；读不到/落盘失败都不阻断请求。
function instanceIdFilePath() {
  const home = os.homedir();
  if (process.platform === "win32") {
    const appdata = process.env.APPDATA || home;
    return path.join(appdata, "dknowc", INSTANCE_FILE_NAME);
  }
  const xdg = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(xdg, "dknowc", INSTANCE_FILE_NAME);
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

// 验证页链接安全校验：展示给用户前必须通过。规则（开发文档 2026-10-09）：
// 与调用方预配置的 API base 同源（生产 https://platform.dknowc.cn；测试环境随 --base，
// 不硬编码生产 host）、精确页面路径、无用户名/密码、无 query、fragment 仅为 #token=
// 后跟 43 位 Base64URL 字符（A-Z a-z 0-9 _ -）；拒绝编码/路径遍历/其他版本与非规范 URL。
const VERIFICATION_PAGE_PATH = "/auth/open-api/maas/identity/v1/sms-verification-page";
function verificationPageOrigin(base) {
  // 从 base 裁掉 /auth/home/userAuto 得到环境前缀（生产即 https://platform.dknowc.cn）
  const m = String(base || "").match(/^(https?:\/\/[^\/]+)\/auth\/home\/userAuto\/?$/);
  return m ? m[1] : null;
}
function validateVerificationUrl(rawUrl, base) {
  const origin = verificationPageOrigin(base);
  if (!origin) return null;
  try {
    const u = new URL(String(rawUrl || ""));
    if (u.username || u.password || u.search) return null;
    if (u.origin !== origin) return null;
    if (u.pathname !== VERIFICATION_PAGE_PATH) return null;
    if (!/^#token=[A-Za-z0-9_-]{43}$/.test(u.hash)) return null;
    if (String(rawUrl) !== u.toString()) return null; // 拒绝编码/非规范写法
    return u.toString();
  } catch { return null; }
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

// 注册链路（sendMessage / register）专用 POST：
// - 携带 X-MaaS 客户端观测请求头（user-auth maas-1.1.6）：Entry-Surface 固定 DIRECT_API、
//   Client-Name 为本 Skill 真实包名、Client-Version 运行时读 SKILL.md、Client-Instance-Id
//   首次不带（服务端响应头签发后落盘，后续请求回传，不自行生成）；
// - 返回 { body, requestUnknown }：requestUnknown=true 表示超时/断网等"结果未确认"情形
//   （发送结果未知时不得立即补发，由调用方按专用话术处理）。
async function post(url, payload) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 30000);
  try {
    const headers = withAttribution({ "Content-Type": "application/json" });
    headers["X-MaaS-Entry-Surface"] = "DIRECT_API";
    headers["X-MaaS-Client-Name"] = MAAS_CLIENT_NAME;
    headers["X-MaaS-Client-Version"] = readSkillVersion();
    const iid = readInstanceId();
    if (iid) headers["X-MaaS-Client-Instance-Id"] = iid;
    const r = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: ctl.signal,
    });
    const issued = r.headers.get("X-MaaS-Client-Instance-Id");
    if (issued && issued.trim()) writeInstanceId(issued.trim());
    const text = await r.text();
    let body;
    try { body = JSON.parse(text); }
    catch { body = { status: false, msg: "非JSON响应(前200字符): " + text.slice(0, 200) }; }
    return { body, requestUnknown: false };
  } catch (e) {
    return {
      body: { status: false, msg: "请求异常: " + (e && e.message ? e.message : String(e)) },
      requestUnknown: true,
    };
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
    const { body: r, requestUnknown } = await post(base + "/sendMessage", { phone: a.phone, type: "register", channel });
    const code = String(r.code || (r.data && r.data.code) || "");
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    // 2026-10-09 两分支（user-auth maas-1.1.6）：status:true 短信已直发；
    // CAPTCHA_REQUIRED 短信尚未发送——需用户在验证页完成行为验证后由页面发码，
    // 用户完成页面验证后 Agent 不得再调 sendMessage（验证页不是可无限发码的通行证）。
    let userMessage;
    let exitCode = 1;
    let extra = {};
    if (code === "CAPTCHA_REQUIRED") {
      const vUrl = validateVerificationUrl(r.verificationUrl, base);
      if (vUrl) {
        userMessage = `短信还没发送。请打开这个验证链接，核对手机号（${maskPhone(a.phone)}）后点击“验证并发送短信”，按提示完成验证：\n${vUrl}\n收到短信后把 6 位验证码回复给我，我继续开通，不需要重新填写注册表。`;
        extra = {
          verificationUrl: vUrl,
          verificationUrlValidated: true,
          instruction: "等待用户验证：将 user_message（含链接）转述给用户后暂停，等用户回复 6 位短信验证码。用户在页面完成验证后不得再次调用 send；链接一次性、约 10 分钟有效，过期或已用需用户同意后重新 send 申请新链接。",
        };
        exitCode = 2;
      } else {
        // 链接校验不通过：不向用户展示原始链接（防钓鱼/防篡改），按"链接不可用"处理
        userMessage = "这次开通需要先完成一次页面验证，但验证链接校验没有通过（可能已过期或不可用）。跟我说一声，我重新给你申请一个新的验证链接。";
        extra = {
          verificationUrl: undefined, // 确保 JSON 输出不携带未通过校验的链接
          code: "CAPTCHA_LINK_UNAVAILABLE",
          msg: r.msg || "验证链接校验未通过",
          instruction: "不得展示未通过校验的链接；用户同意后重新调用 send 申请新链接。",
        };
      }
    } else if (code === "SMS_RATE_LIMIT_PHONE") {
      // 展示服务端间隔（若有）；未给时只说稍后再试，不伪造精确倒计时
      const secs = Number(r.retryAfterSeconds || (r.data && r.data.retryAfterSeconds) || 0);
      const mins = secs > 0 ? Math.max(1, Math.floor(secs / 60)) : 0;
      userMessage = mins > 0
        ? `验证码发送太频繁了，短信通道要求约 ${mins} 分钟后再试。你先忙别的，想重发时跟我说一声。`
        : "验证码发送太频繁了，稍等几分钟再试；想重发时跟我说一声。";
      extra = { instruction: "限频停点：等待用户明确要求且冷却时间过后才重试，不自动重发。" };
    } else if (code === "CAPTCHA_LINK_UNAVAILABLE" || code === "CAPTCHA_REPLAY") {
      userMessage = "刚才的验证链接已过期或已使用。跟我说一声，我重新给你申请一个新的验证链接。";
      extra = { instruction: "不重复提交旧链接 token；用户确认后重新调用 send 申请新链接。" };
    } else if (code === "CAPTCHA_REJECTED" || code === "CAPTCHA_BUSY" || code === "CAPTCHA_STATE_UNAVAILABLE") {
      userMessage = "这次验证没有通过（或验证服务暂时不可用）。可以稍后重新打开链接再试；还是不行跟我说，我重新申请一个。";
      extra = { instruction: "据实提示验证未通过或暂不可用，不伪造验证凭据、不把失败当成功。" };
    } else if (code.startsWith("SMS_PROVIDER_")) {
      userMessage = `短信服务暂时出了点问题，发不出验证码。可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`;
      extra = { instruction: "短信供应商失败停点：不自动重试。" };
    } else if (requestUnknown || String(r.msg || "").startsWith("非JSON响应")) {
      // 发送结果未确认（超时/断网/响应异常）：先让用户检查是否已收到短信，不马上补发
      userMessage = "刚才发送请求的结果没有确认（网络波动）。先看一下手机有没有收到验证码短信：收到了直接把 6 位验证码发我；没收到再跟我说，我重新发。";
      extra = { resultUnknown: true, instruction: "结果未确认停点：先等用户确认是否收到短信，未确认前不重新发送。" };
    } else if (r.status) {
      userMessage = `验证码已发送到 ${maskPhone(a.phone)}，请把最新一条短信里的 6 位验证码发我。`;
      exitCode = 0;
    } else if (String(r.msg || "").includes("手机号")) {
      userMessage = "这个手机号格式好像不对，麻烦核对一下再发我。";
    } else {
      userMessage = `验证码发送没成功（可能是网络或短信通道问题），可以再试一次；如果连续失败，也可以用网页方式开通：${FALLBACK_REGISTER_URL}`;
    }
    console.log(JSON.stringify({ ...r, ...extra, user_message: userMessage }));
    if (exitCode === 0) console.error("验证码已发送（话术见 user_message，请向用户转述后索取 6 位验证码）。");
    if (exitCode === 2) console.error("需要用户在验证页完成验证（话术见 user_message）：暂停等待短信验证码；用户完成后不得再调 send。");
    process.exit(exitCode);
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
