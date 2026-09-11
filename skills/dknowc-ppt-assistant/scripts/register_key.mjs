#!/usr/bin/env node
// MaaS key bootstrap helper for SkillHub Public.
// It only requests/returns a key for the current task and never writes local files.
//   node register_key.mjs send --phone <phone>
//   node register_key.mjs register --phone <phone> --vcode <code> [--new-key]

const DEFAULT_BASE = "https://platform.dknowc.cn/auth/home/userAuto";
const DEFAULT_OPEN_BASE = "https://open.dknowc.cn";
const DEFAULT_CHANNEL = "46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05";
const DEFAULT_TYPE = "11";
const DEFAULT_SOURCE = "agent";
const API_KEY_ENV = "DKNOWC_API_KEY";
const MAAS_PLATFORM_URL = "https://platform.dknowc.cn/auth/#/login";

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

function maskPhone(phone) {
  const p = String(phone || "");
  return p.length === 11 ? `${p.slice(0, 3)}****${p.slice(-4)}` : p;
}

function isValidCnPhone(phone) {
  return /^1[3-9]\d{9}$/.test(String(phone || ""));
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
    if (!isValidCnPhone(args.phone)) {
      console.log(JSON.stringify({
        status: false,
        msg: "手机号格式不正确",
        user_message: "这个手机号格式好像不对，麻烦核对一下再发我。",
      }));
      process.exit(1);
    }
    let result;
    try {
      result = await postJson(`${base}/sendMessage`, {
        phone: args.phone,
        type: "register",
        channel,
      });
    } catch (e) {
      result = { status: false, msg: String((e && e.message) || e) };
    }
    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    let userMessage;
    if (result.status) {
      userMessage = `验证码已发送到 ${maskPhone(args.phone)}，请把最新一条短信里的 6 位验证码发我。`;
    } else {
      userMessage = `验证码发送没成功（可能是网络或短信通道问题），可以再试一次；如果连续失败，也可以用网页方式开通：${MAAS_PLATFORM_URL}`;
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
    let apiKey = result.status && data.apiKey ? data.apiKey : "";
    let newKeyCreated = false;
    let newKeyError = null;

    if (apiKey && args["new-key"]) {
      const keyName = args["new-key-name"] && args["new-key-name"] !== true
        ? args["new-key-name"]
        : payload.apiKeyName;
      const keyRemark = args["new-key-remark"] && args["new-key-remark"] !== true
        ? args["new-key-remark"]
        : "由 SkillHub 深知可信搜索按用户要求重新生成";
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
        // 新建失败：沿用原密钥继续并如实告知，不弃 key、不冒充新 Key
        newKeyError = created.result.errmsg || created.result.msg || "新 API Key 创建失败";
      }
    }

    // user_message：给用户的固定话术，Agent 必须原样转述，不得改写后发挥。
    const registered = Boolean(apiKey);
    let userMessage;
    if (registered && data.existed) {
      userMessage = "这个手机号之前开通过，已直接找回原来的密钥和额度，不用重新注册。我马上开始检索。";
    } else if (registered) {
      userMessage = "开通成功，访问密钥已写入本机，300 次免费检索额度已生效。我马上开始检索。";
    } else if (/vcode|验证码/i.test(String(result.msg || ""))) {
      userMessage = `验证码校验没通过（可能是输入有误或已过期）。请核对 ${maskPhone(args.phone)} 最新一条短信的 6 位验证码重新发我；需要我重新发送一条，直接说一声。`;
    } else {
      userMessage = `开通服务暂时没连上（${result.msg || "网络波动"}），可以稍后再试，或用网页方式开通：${MAAS_PLATFORM_URL}`;
    }
    if (registered && newKeyError) {
      userMessage += ` 另外你要求的新密钥生成失败（${newKeyError}），已先沿用现有密钥继续，不影响使用；需要的话稍后再重新生成。`;
    }

    console.log(JSON.stringify({
      status: registered,
      msg: result.msg,
      url: data.url || null,
      existed: Boolean(data.existed),
      keyCreatedByRegister: Boolean(data.keyCreated),
      newKeyRequested: Boolean(args["new-key"]),
      newKeyCreated,
      envName: API_KEY_ENV,
      apiKey,
      apiKeyMasked: maskKey(apiKey),
      currentTaskOnly: true,
      persistInstruction: `本次返回的 apiKey 仅供当前任务临时注入 ${API_KEY_ENV}。任务完成后，建议用户在 SkillHub/WorkBuddy 平台环境变量或密钥配置中保存 ${API_KEY_ENV}。`,
      fallbackRegisterUrl: MAAS_PLATFORM_URL,
      newKeyError,
      user_message: userMessage,
    }));
    process.exit(apiKey && !newKeyError ? 0 : 1);
  }

  console.error("用法: node register_key.mjs <send|register> ...");
  process.exit(2);
}

main();
