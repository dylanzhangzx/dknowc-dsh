#!/usr/bin/env node
// 国内 MaaS headless 注册助手（供 skillhub skill 调用；纯 node，内置 fetch，无三方依赖）。
//   node register_key.mjs [--base URL] send     --phone <p>
//   node register_key.mjs [--base URL] register --phone <p> --vcode <c> [--type 11] [--organ ..] [--name ..] [--channel ..] [--source ..] [--password ..] [--new-key] [--no-zshrc]
// 无需 cookie / 加密 / 登录态。注册成功后自动把 API Key 写入 ~/.zshrc 标记块（--no-zshrc 跳过）；
// 业务脚本从 ~/.zshrc 直读，无需重启宿主。默认打生产，--base 可切测试环境。

import fs from "fs";
import os from "os";
import path from "path";

const DEFAULT_BASE = "https://platform.dknowc.cn/auth/home/userAuto";
const DEFAULT_OPEN_BASE = "https://open.dknowc.cn";
const DEFAULT_CHANNEL = "46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05";
const DEFAULT_TYPE = "11";
const DEFAULT_SOURCE = "agent";
const API_KEY_ENV = "DKNOWC_API_KEY";
const MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login";
const FALLBACK_REGISTER_URL = MAAS_PLATFORM_URL;
const ZSHRC_START = "# >>> dknowc api key >>>";
const ZSHRC_END = "# <<< dknowc api key <<<";

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

function shellSingleQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
  } catch (error) {
    const msg = error && error.message ? error.message : String(error);
    return { written: false, path: zshrcPath, error: msg };
  }

  const pattern = new RegExp(`${escapeRegExp(ZSHRC_START)}[\\s\\S]*?${escapeRegExp(ZSHRC_END)}\\n?`, "m");
  const next = pattern.test(existing)
    ? existing.replace(pattern, block)
    : `${existing}${existing && !existing.endsWith("\n") ? "\n" : ""}${block}`;

  try {
    fs.writeFileSync(zshrcPath, next, { encoding: "utf8", mode: 0o600 });
    return { written: true, path: zshrcPath, error: null };
  } catch (error) {
    const msg = error && error.message ? error.message : String(error);
    return { written: false, path: zshrcPath, error: msg };
  }
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
    const zshrcWrite = ok && apiKeyToSave && !args["no-zshrc"]
      ? writeApiKeyToZshrc(apiKeyToSave)
      : { written: false, path: path.join(os.homedir(), ".zshrc"), error: null };
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    // 权益告知（300 次额度 + 实名认证赠金）已前移到开通引导（initialize.guide_message / onboarding_scripts S1），
    // 此处只做轻确认，避免成功节点信息过重导致转述截断。
    let userMessage;
    if (ok && apiKeyToSave) {
      userMessage = Boolean(data.existed)
        ? `这个手机号之前开通过，已直接找回原来的密钥和额度，不用重新注册。我马上开始检索。`
        : `开通成功，访问密钥已写入本机，300 次免费检索额度已生效。我马上开始检索。`;
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
      apiKey: apiKeyToSave,
      apiKeyMasked: maskKey(apiKeyToSave),
      envWriteRequired: false,
      envWriteTarget: zshrcWrite.path,
      envWriteSucceeded: Boolean(zshrcWrite.written),
      envWriteError: zshrcWrite.error,
      envWriteInstruction: zshrcWrite.written
        ? `已写入 ${zshrcWrite.path}；脚本直读该文件，无需重启宿主。当前任务可继续使用返回的 apiKey。`
        : `未能写入 ${zshrcWrite.path}，请由 Agent 或平台密钥配置将返回的 apiKey 写入环境变量 ${API_KEY_ENV}。`,
      currentSessionInstruction: `当前任务继续执行初始化时，请用本次返回的 apiKey 临时注入环境变量 ${API_KEY_ENV}，不得向用户展示完整 Key。`,
      newKeyError,
      fallbackRegisterUrl: FALLBACK_REGISTER_URL,
    }));
    process.exit(ok && Boolean(apiKeyToSave) ? 0 : 1);
  }

  console.error("用法: node register_key.mjs <send|register> ...");
  process.exit(2);
}

main();
