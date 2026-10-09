#!/usr/bin/env node
// 国内 MaaS headless 注册助手（供 skillhub skill 调用；纯 node，内置 fetch，无三方依赖）。
//   node register_key.mjs [--base URL] send     --phone <p>
//     退出码三态：0=短信已发送；2=需用户在验证页完成行为验证（CAPTCHA_REQUIRED，短信尚未发送）；1=错误。
//   node register_key.mjs [--base URL] register --phone <p> --vcode <c> [--type 11] [--organ ..] [--name ..] [--channel ..] [--source ..] [--password ..] [--new-key] [--no-persist]
//     可能返回 pending:true（账号已创建、密钥资源准备中）——非错误，稍后同参数重试一次。
//   node register_key.mjs save-key   （MCP 取 Key 路径落盘：密钥经 stdin 或 --api-key 传入）
// 无需 cookie / 加密 / 登录态。2026-10-09 注册链路改造（user-auth maas-1.1.6）：
// sendMessage 两分支（直发/验证链接）、X-MaaS 客户端观测请求头、错误码族映射、
// 验证链接安全校验、register pending 态处理，详见各分支内注释。
// 注册成功自动把 API Key 写入本机专用配置文件
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
// body 的 source 是注册 API 的合同标记：服务端按 source="agent" 放行"老用户直接返 Key"
// 路径（2026-10-09 生产实测：source 传 skill 标识时返回"用户已存在！"错误，source=agent
// 时正常返回 Key）。它与 X-Dknowc-Attribution 统计声明里的 skill 标识是两个不同字段：
// 统计声明头的键名为 agentSource（2026-10-09 平台方改名，避免与 body 的 source 混淆），
// 值仍读 attribution.json 的 dknowc-trusted-search，不受本值影响。
const DEFAULT_SOURCE = "agent";
// 2026-10-09 注册链路改造：MaaS 客户端观测请求头（X-MaaS-*）用本 Skill 真实包名，不冒充
// 其他客户端；Client-Version 运行时读包根 SKILL.md；Instance-Id 由服务端响应头签发后落盘
// 回传，不自行生成（user-auth maas-1.1.6 契约）。
const MAAS_CLIENT_NAME = "dknowc-trusted-search";
const INSTANCE_FILE_NAME = "maas_client_instance";
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

// 来源声明（X-Dknowc-Attribution，仅统计用、不参与鉴权）：
// 读包根 attribution.json（kind/source/channel）+ SKILL.md 的 version；读取失败不加头、不阻断请求。
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
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const headers = withAttribution({ "Content-Type": "application/json" });
    headers["X-MaaS-Entry-Surface"] = "DIRECT_API";
    headers["X-MaaS-Client-Name"] = MAAS_CLIENT_NAME;
    headers["X-MaaS-Client-Version"] = readSkillVersion();
    const iid = readInstanceId();
    if (iid) headers["X-MaaS-Client-Instance-Id"] = iid;
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const issued = response.headers.get("X-MaaS-Client-Instance-Id");
    if (issued && issued.trim()) writeInstanceId(issued.trim());
    const text = await response.text();
    let body;
    try { body = JSON.parse(text); }
    catch { body = { status: false, msg: `非 JSON 响应：${text.slice(0, 200)}` }; }
    return { body, requestUnknown: false };
  } catch (error) {
    const msg = error && error.message ? error.message : String(error);
    return { body: { status: false, msg: `请求异常：${msg}` }, requestUnknown: true };
  } finally {
    clearTimeout(timer);
  }
}

// API Key 创建接口（open 域 Bearer 鉴权）专用 POST：不带 X-MaaS 观测头（仅注册链路契约）。
async function postWithBearer(url, apiKey, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: withAttribution({
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      }),
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await response.text();
    try { return JSON.parse(text); }
    catch { return { code: response.status, errmsg: `非 JSON 响应：${text.slice(0, 200)}` }; }
  } catch (error) {
    const msg = error && error.message ? error.message : String(error);
    return { code: 0, errmsg: `请求异常：${msg}` };
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
  const result = await postWithBearer(url, existingApiKey, { name, remark });
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
    // MCP 取 Key 路径的落盘子命令。宿主提供 dknowc-mcp 的 create_api_key 且调用
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
    const channel = args.channel && args.channel !== true ? args.channel : DEFAULT_CHANNEL;
    const { body: result, requestUnknown } = await post(`${base}/sendMessage`, {
      phone: args.phone,
      type: "register",
      channel,
    });
    const errCode = String(result.code || (result.data && result.data.code) || "");
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    // 2026-10-09 两分支（user-auth maas-1.1.6）：status:true 短信已直发；
    // CAPTCHA_REQUIRED 短信尚未发送——需用户在验证页完成行为验证后由页面发码，
    // 用户完成页面验证后 Agent 不得再调 sendMessage（验证页不是可无限发码的通行证）。
    let userMessage;
    let exitCode = 1;
    let extra = {};
    if (errCode === "CAPTCHA_REQUIRED") {
      const vUrl = validateVerificationUrl(result.verificationUrl, base);
      if (vUrl) {
        userMessage = `短信还没发送。请打开这个验证链接，核对手机号（${maskPhone(args.phone)}）后点击“验证并发送短信”，按提示完成验证：\n${vUrl}\n收到短信后把 6 位验证码回复给我，我继续开通，不需要重新填写注册表。`;
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
          msg: result.msg || "验证链接校验未通过",
          instruction: "不得展示未通过校验的链接；用户同意后重新调用 send 申请新链接。",
        };
      }
    } else if (errCode === "SMS_RATE_LIMIT_PHONE") {
      // 展示服务端间隔（若有）；未给时只说稍后再试，不伪造精确倒计时
      const secs = Number(result.retryAfterSeconds || (result.data && result.data.retryAfterSeconds) || 0);
      const mins = secs > 0 ? Math.max(1, Math.floor(secs / 60)) : 0;
      userMessage = mins > 0
        ? `验证码发送太频繁了，短信通道要求约 ${mins} 分钟后再试。你先忙别的，想重发时跟我说一声。`
        : "验证码发送太频繁了，稍等几分钟再试；想重发时跟我说一声。";
      extra = { instruction: "限频停点：等待用户明确要求且冷却时间过后才重试，不自动重发。" };
    } else if (errCode === "CAPTCHA_LINK_UNAVAILABLE" || errCode === "CAPTCHA_REPLAY") {
      userMessage = "刚才的验证链接已过期或已使用。跟我说一声，我重新给你申请一个新的验证链接。";
      extra = { instruction: "不重复提交旧链接 token；用户确认后重新调用 send 申请新链接。" };
    } else if (errCode === "CAPTCHA_REJECTED" || errCode === "CAPTCHA_BUSY" || errCode === "CAPTCHA_STATE_UNAVAILABLE") {
      userMessage = "这次验证没有通过（或验证服务暂时不可用）。可以稍后重新打开链接再试；还是不行跟我说，我重新申请一个。";
      extra = { instruction: "据实提示验证未通过或暂不可用，不伪造验证凭据、不把失败当成功。" };
    } else if (errCode.startsWith("SMS_PROVIDER_")) {
      userMessage = `短信服务暂时出了点问题，发不出验证码。可以稍后再试，或用网页方式开通：${FALLBACK_REGISTER_URL}`;
      extra = { instruction: "短信供应商失败停点：不自动重试。" };
    } else if (requestUnknown || String(result.msg || "").startsWith("非 JSON 响应")) {
      // 发送结果未确认（超时/断网/响应异常）：先让用户检查是否已收到短信，不马上补发
      userMessage = "刚才发送请求的结果没有确认（网络波动）。先看一下手机有没有收到验证码短信：收到了直接把 6 位验证码发我；没收到再跟我说，我重新发。";
      extra = { resultUnknown: true, instruction: "结果未确认停点：先等用户确认是否收到短信，未确认前不重新发送。" };
    } else if (result.status) {
      userMessage = `验证码已发送到 ${maskPhone(args.phone)}，请把最新一条短信里的 6 位验证码发我。`;
      exitCode = 0;
    } else if (String(result.msg || "").includes("手机号")) {
      userMessage = "这个手机号格式好像不对，麻烦核对一下再发我。";
    } else {
      userMessage = `验证码发送没成功（可能是网络或短信通道问题），可以再试一次；如果连续失败，也可以用网页方式开通：${FALLBACK_REGISTER_URL}`;
    }
    console.log(JSON.stringify({ ...result, ...extra, user_message: userMessage }));
    if (exitCode === 0) console.error("验证码已发送（话术见 user_message，请向用户转述后索取 6 位验证码）。");
    if (exitCode === 2) console.error("需要用户在验证页完成验证（话术见 user_message）：暂停等待短信验证码；用户完成后不得再调 send。");
    process.exit(exitCode);
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

    const { body: result } = await post(`${base}/register`, payload);
    const data = result.data || {};
    // 2026-10-09（user-auth maas-1.1.6）：registered:true + deliveryStatus:"PENDING"——
    // 账号已创建、Key 资源尚在准备。非错误：不盲目重注册，等用户示意后在短信码有效期内
    // （5 分钟）用同参数重试一次；过期再走重新发码流程。
    if (!data.apiKey && (data.deliveryStatus === "PENDING" || result.registered === true)) {
      console.log(JSON.stringify({
        status: false,
        pending: true,
        msg: result.msg || null,
        // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥
        user_message: "账号已经创建成功，系统正在准备你的访问密钥（一般一两分钟内就好）。稍等后跟我说一声“再试”，我再确认一次；不用重新注册，也不用重新发验证码。",
        instruction: "非错误：不要重新注册、不要重新发码。等用户示意后用同一手机号与同一验证码重试一次 register（短信码 5 分钟有效）；若提示验证码过期，再走重新发码流程。",
      }));
      process.exit(0);
    }
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
    // 注册成功自动持久化到本机专用配置文件 ~/.config/dknowc/api_key（1.3.5 起：
    // 不再写 ~/.zshrc，避免污染 shell 配置；读取顺序 env→配置文件→历史 zshrc 兜底）。
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
        ? `这个手机号之前开通过，已直接找回原来的密钥和积分，不用重新注册。我马上开始检索。`
        : `开通成功，访问密钥已写入本机，注册赠送的 10 万积分已到账。我马上开始检索。`;
      if (newKeyError) {
        userMessage += ` 另外你要求的新密钥生成失败（${newKeyError}），已先沿用现有密钥继续，不影响使用；需要的话稍后再重新生成。`;
      }
    } else if (String(result.msg || "").includes("验证码")) {
      userMessage = `验证码校验没通过（可能是输入有误或已过期）。请核对 ${maskPhone(args.phone)} 最新一条短信的 6 位验证码重新发我；需要我重新发送一条，直接说一声。`;
    } else if (String(result.msg || "").includes("已存在")) {
      // 老用户但服务端未放行返 Key：据实说明并引导网页登录，不冒充找回成功、不诱导重复注册
      userMessage = `这个手机号之前注册过深知账号，这次没能自动取回密钥。可以稍后再试一次，或到平台用手机号验证码登录查看：${FALLBACK_REGISTER_URL}`;
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
      // 防明文泄漏：注册成功且已持久化时不输出明文 apiKey，
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
