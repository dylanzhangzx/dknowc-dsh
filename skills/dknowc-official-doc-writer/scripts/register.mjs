#!/usr/bin/env node
// 国内 MaaS headless 注册助手（供 skillhub skill 调用；纯 node，内置 fetch，无三方依赖）。
//   node register.mjs [--base URL] send     --phone <p>
//   node register.mjs [--base URL] register --phone <p> --vcode <c> [--type 6] [--organ ..] [--name ..] [--channel ..] [--source ..] [--password ..] [--new-key]
// 无需 cookie / 加密 / 登录态。默认打生产，--base 可切测试环境。

import fs from "fs";
import os from "os";
import path from "path";

const DEFAULT_BASE = "https://platform.dknowc.cn/auth/home/userAuto";
const DEFAULT_OPEN_BASE = "https://open.dknowc.cn";
const DEFAULT_CHANNEL = "46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05";
const DEFAULT_TYPE = "6";
const DEFAULT_SOURCE = "agent";
const API_KEY_ENV = "DKNOWC_API_KEY";
const MAAS_PLATFORM_URL = "https://platform.dknowc.cn/";
const FALLBACK_REGISTER_URL = MAAS_PLATFORM_URL;
const ZSHRC_START = "# >>> dknowc official doc writer api key >>>";
const ZSHRC_END = "# <<< dknowc official doc writer api key <<<";

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

async function post(url, payload) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 30000);
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
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

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function main() {
  const a = parseArgs(process.argv.slice(2));
  const base = a.base || DEFAULT_BASE;
  const cmd = a._[0];

  if (cmd === "send") {
    if (!a.phone) { console.error("缺少 --phone"); process.exit(2); }
    const r = await post(base + "/sendMessage", { phone: a.phone, type: "register", channel: a.channel && a.channel !== true ? a.channel : DEFAULT_CHANNEL });
    console.log(JSON.stringify(r));
    if (r.status) console.error("验证码已发送，请向用户索取收到的 6 位验证码后再执行 register。");
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
        newKeyError = result.errmsg || result.msg || "新 API Key 创建失败";
        apiKeyToSave = "";
      }
    }
    const zshrcWrite = ok && apiKeyToSave && !newKeyError && !a["no-zshrc"]
      ? writeApiKeyToZshrc(apiKeyToSave)
      : { written: false, path: path.join(os.homedir(), ".zshrc"), error: null };
    console.log(JSON.stringify({
      status: ok && Boolean(apiKeyToSave) && !newKeyError,
      msg: r.msg,
      url: data.url || null,
      existed: Boolean(data.existed),
      keyCreatedByRegister: Boolean(data.keyCreated),
      newKeyRequested: Boolean(a["new-key"]),
      newKeyCreated,
      envName: API_KEY_ENV,
      apiKey: apiKeyToSave,
      apiKeyMasked: apiKeyToSave ? `${apiKeyToSave.slice(0, 7)}...${apiKeyToSave.slice(-4)}` : null,
      envWriteRequired: false,
      envWriteTarget: zshrcWrite.path,
      envWriteSucceeded: Boolean(zshrcWrite.written),
      envWriteError: zshrcWrite.error,
      envWriteInstruction: zshrcWrite.written
        ? `已写入 ${zshrcWrite.path}。当前任务可继续使用返回的 apiKey；后续新对话如仍检测不到 ${API_KEY_ENV}，请重启 WorkBuddy 后再试。`
        : `未能写入 ${zshrcWrite.path}，请由 Agent 或平台密钥配置将返回的 apiKey 写入环境变量 ${API_KEY_ENV}。`,
      currentSessionInstruction: `当前任务继续执行初始化时，请用本次返回的 apiKey 临时注入环境变量 ${API_KEY_ENV}，不得向用户展示完整 Key。`,
      newKeyError,
      fallbackRegisterUrl: FALLBACK_REGISTER_URL,
    }));
    process.exit(ok && Boolean(apiKeyToSave) && !newKeyError ? 0 : 1);
  }

  console.error("用法: node register.mjs <send|register> ...");
  process.exit(2);
}

main();
