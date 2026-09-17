#!/usr/bin/env node
// MaaS key bootstrap helper for SkillHub Public.
//   node register_key.mjs send --phone <phone>
//   node register_key.mjs register --phone <phone> --vcode <code> [--new-key] [--no-zshrc]
//
// 注册成功后自动把 Key 写入 ~/.zshrc 标记块（--no-zshrc 跳过）；配合 api_key.py
// 的 zshrc 兜底解析，写入后无需重启宿主即生效。
// 各分支输出 user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥
// （话术库见 reference/onboarding_scripts.md；手机号一律脱敏显示）。

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const ZSHRC_START = "# >>> dknowc api key >>>";
const ZSHRC_END = "# <<< dknowc api key <<<";
// 早期版本遗留的标记块名（本 Skill 历史上无其他块名，保留机制以备后续变更）
const LEGACY_BLOCKS = [
  ["# >>> dknowc trusted search api key >>>", "# <<< dknowc trusted search api key <<<"],
  ["# >>> dknowc trusted consulting api key >>>", "# <<< dknowc trusted consulting api key <<<"],
  ["# >>> dknowc official doc writer api key >>>", "# <<< dknowc official doc writer api key <<<"],
];

const DEFAULT_BASE = "https://platform.dknowc.cn/auth/home/userAuto";
const DEFAULT_OPEN_BASE = "https://open.dknowc.cn";
const DEFAULT_CHANNEL = "46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05";
const DEFAULT_SOURCE = "agent";
const API_KEY_ENV = "DKNOWC_API_KEY";
const LOGIN_URL = "https://platform.dknowc.cn/auth/#/login";

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

function maskPhone(phone) {
  const p = String(phone || "");
  if (p.length < 7) return "***";
  return `${p.slice(0, 3)}****${p.slice(-4)}`;
}

async function postJson(url, payload, headers = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
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

function shellSingleQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function writeApiKeyToZshrc(apiKey) {
  const zshrcPath = path.join(os.homedir(), ".zshrc");
  const block = [
    ZSHRC_START,
    `export ${API_KEY_ENV}=${shellSingleQuote(apiKey)}`,
    ZSHRC_END,
    "",
  ].join("\n");
  let existing = "";
  try {
    existing = fs.existsSync(zshrcPath) ? fs.readFileSync(zshrcPath, "utf8") : "";
  } catch (e) {
    return { written: false, path: zshrcPath, error: e && e.message ? e.message : String(e) };
  }

  // 清理早期版本遗留的标记块（含空块），再写入当前标准块
  for (const [start, end] of LEGACY_BLOCKS) {
    const legacy = new RegExp(`${escapeRegExp(start)}[\\s\\S]*?${escapeRegExp(end)}\\n?`, "m");
    existing = existing.replace(legacy, "");
  }

  const pattern = new RegExp(`${escapeRegExp(ZSHRC_START)}[\\s\\S]*?${escapeRegExp(ZSHRC_END)}\\n?`, "m");
  const next = pattern.test(existing)
    ? existing.replace(pattern, block)
    : `${existing}${existing && !existing.endsWith("\n") ? "\n" : ""}${block}`;

  try {
    fs.writeFileSync(zshrcPath, next, { encoding: "utf8", mode: 0o600 });
    return { written: true, path: zshrcPath, error: null };
  } catch (e) {
    return { written: false, path: zshrcPath, error: e && e.message ? e.message : String(e) };
  }
}

function maskKey(apiKey) {
  if (!apiKey) return null;
  if (apiKey.length <= 12) return "***";
  return `${apiKey.slice(0, 7)}...${apiKey.slice(-4)}`;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  const base = args.base || DEFAULT_BASE;

  if (cmd === "send") {
    if (!args.phone) {
      console.error("缺少 --phone");
      process.exit(2);
    }
    const channel = args.channel && args.channel !== true ? args.channel : DEFAULT_CHANNEL;
    const r = await postJson(`${base}/sendMessage`, { phone: args.phone, type: "register", channel });
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥
    let userMessage;
    if (r.status) {
      userMessage = `验证码已发送到 ${maskPhone(args.phone)}，请把最新一条短信里的 6 位验证码发我。`;
    } else if (String(r.msg || "").includes("手机号")) {
      userMessage = "这个手机号格式好像不对，麻烦核对一下再发我。";
    } else {
      userMessage = `验证码发送没成功（可能是网络或短信通道问题），可以再试一次；如果连续失败，也可以用网页方式开通：${LOGIN_URL}`;
    }
    console.log(JSON.stringify({ ...r, user_message: userMessage }));
    if (r.status) console.error("验证码已发送（话术见 user_message，请向用户转述后索取 6 位验证码）。");
    process.exit(r.status ? 0 : 1);
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
      organ: args.organ && args.organ !== true ? args.organ : "个人",
      name: args.name && args.name !== true ? args.name : "用户",
      apiKeyName: args["apikey-name"] && args["apikey-name"] !== true ? args["apikey-name"] : "agent-key",
      channel: args.channel && args.channel !== true ? args.channel : DEFAULT_CHANNEL,
      source: args.source && args.source !== true ? args.source : DEFAULT_SOURCE,
    };

    const r = await postJson(`${base}/register`, payload);
    const data = r.data || {};
    let apiKey = r.status && data.apiKey ? data.apiKey : "";
    let newKeyCreated = false;
    let newKeyError = null;

    if (apiKey && args["new-key"]) {
      const keyName = args["new-key-name"] && args["new-key-name"] !== true
        ? args["new-key-name"]
        : payload.apiKeyName;
      const keyRemark = args["new-key-remark"] && args["new-key-remark"] !== true
        ? args["new-key-remark"]
        : "由 SkillHub 深知可信咨询按用户要求重新生成";
      const created = await createNewApiKey(
        args["open-base"] && args["open-base"] !== true ? args["open-base"] : DEFAULT_OPEN_BASE,
        apiKey,
        keyName,
        keyRemark,
      );
      if (created.apiKey) {
        apiKey = created.apiKey;
        newKeyCreated = true;
      } else {
        // 新建 Key 失败：沿用现有密钥继续，如实告知，不把旧 Key 冒充新 Key
        newKeyError = created.result.errmsg || created.result.msg || "新 API Key 创建失败";
      }
    }

    // 注册成功自动持久化到 ~/.zshrc 标记块（--no-zshrc 跳过）；
    // 配合 api_key.py 兜底解析，写入后无需重启宿主即生效。
    const zshrcWrite = apiKey && !args["no-zshrc"]
      ? writeApiKeyToZshrc(apiKey)
      : { written: false, path: path.join(os.homedir(), ".zshrc"), error: null };

    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    // 权益（300 次额度 + 实名认证赠金）已在引导开通时告知，此处只做额度到账的轻确认。
    let userMessage;
    if (apiKey) {
      userMessage = Boolean(data.existed)
        ? `这个手机号之前开通过，已直接找回原来的密钥和额度，不用重新注册。我马上开始查询。`
        : `开通成功，访问密钥已写入本机，300 次免费咨询额度已生效。我马上开始查询。`;
      if (newKeyError) {
        userMessage += ` 另外你要求的新密钥生成失败（${newKeyError}），已先沿用现有密钥继续，不影响使用；需要的话稍后再重新生成。`;
      }
    } else if (String(r.msg || "").includes("验证码")) {
      userMessage = `验证码校验没通过（可能是输入有误或已过期）。请核对 ${maskPhone(args.phone)} 最新一条短信的 6 位验证码重新发我；需要我重新发送一条，直接说一声。`;
    } else {
      userMessage = `开通服务暂时没连上（${r.msg || "网络波动"}），可以稍后再试，或用网页方式开通：${LOGIN_URL}`;
    }

    console.log(JSON.stringify({
      status: Boolean(apiKey),
      msg: r.msg,
      url: data.url || null,
      existed: Boolean(data.existed),
      keyCreatedByRegister: Boolean(data.keyCreated),
      newKeyRequested: Boolean(args["new-key"]),
      newKeyCreated,
      user_message: userMessage,
      envName: API_KEY_ENV,
      apiKey,
      apiKeyMasked: maskKey(apiKey),
      currentTaskOnly: false,
      envWriteRequired: false,
      envWriteTarget: zshrcWrite.path,
      envWriteSucceeded: Boolean(zshrcWrite.written),
      envWriteError: zshrcWrite.error || null,
      persistInstruction: zshrcWrite.written
        ? `密钥已自动写入 ~/.zshrc 标记块（${API_KEY_ENV}），配合 api_key.py 兜底解析，无需重启即生效；不要重复写入。`
        : `本次未写入 ~/.zshrc${args["no-zshrc"] ? "（--no-zshrc）" : "（写入失败，见 envWriteError）"}；如需持久化，把 ${API_KEY_ENV} 写入 ~/.zshrc 标记块后无需重启即生效。`,
      fallbackRegisterUrl: LOGIN_URL,
      newKeyError,
    }));
    process.exit(apiKey ? 0 : 1);
  }

  console.error("用法: node register_key.mjs <send|register> ...");
  process.exit(2);
}

main();
