---
name: dknowc-trusted-consulting
slug: dknowc-trusted-consulting
display_name: 深知可信咨询
display_name_en: dknowc trusted consulting
description: "当用户咨询政策法规、政务办事、税务社保、公积金、企业补贴、资质证照、行业标准、公共服务、合规义务、企业经营政策、投资技改税惠、办事条件、材料清单、申请路径、风险判断，或要求权威依据、可信溯源、带角标答案、深知可信咨询时，使用深知可信咨询。本 dsh 版通过深知可信工作台 MCP 工具 credible_chat 获取答案和参考材料，输出带真实来源角标的咨询答案，并默认生成本轮交互式可信溯源 HTML。API Key 通过环境变量 DKNOWC_API_KEY 注入（供 MCP Bearer 认证）。"
description_zh: "深知可信咨询是由北京彩智科技有限公司旗下“深知可信智能”提供的可信咨询 Skill，面向政策法规、政务办事、税务社保、公积金、企业补贴、资质证照、行业标准、公共服务、合规义务、企业经营政策和办事导办等场景。它通过 MCP 调用可信统一问答接口，输出带权威来源角标和本地可点击溯源 HTML 的精准咨询结果。"
description_en: "dknowc trusted consulting is a trusted consultation Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It answers policy, regulation, government service, tax, social security, housing fund, enterprise subsidy, licensing, industry standard, compliance and public-service questions through the trusted unified chat API (via MCP), with citation markers and local provenance HTML."
category: 通用办公
version: 1.0.2-dsh
author: 彩智科技
permissions:
  network:
    - "https://mcp.dknowc.cn/"
  local_read:
    - "本 Skill 的说明和脚本文件"
  local_write:
    - "本轮可信溯源 HTML 和接口结果中间文件"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知可信咨询（dsh 版）

本 skill 用于通过深知可信统一问答接口回答用户咨询问题，并生成带角标的本地 HTML 溯源报告。它只覆盖统一接口 `credibleChat` 能力；不要在本 skill 中使用可信搜索、深度搜索或政策可视化流程。

**dsh 接入方式**：本 skill 不再直连深知接口，而是通过深知可信工作台 MCP 工具 `mcp__dknowc__credible_chat` 获取数据（MCP 作为接口转接层）。API Key 通过环境变量 `DKNOWC_API_KEY` 注入，用于 MCP client 的 Bearer 认证；不得硬编码，不得写入公开包，不得在对话中展示完整内容。

## 启动初始化

只要本 Skill 被调用，第一步必须运行：

```bash
python3 <skillDir>/scripts/initialize.py
```

初始化用于检查 Python 环境与 API Key 认证是否就绪。只有初始化结果满足 `ready=true`、`api_key_configured=true` 时才可进入流程；只要 `ready=true` 即可继续咨询、问答、分析、拟稿、整理或任何可替代正式结果的输出流程。

**Key 检查机制（dsh）**：dsh 的安全机制会清理名字含 KEY 的隐式环境变量，脚本子进程读不到原始的 `DKNOWC_API_KEY`。本 bundle 插件会把 dsh 主进程的 `DKNOWC_API_KEY` 值经 shell-env 显式通道注入为 `DSH_DKNOWC_API_KEY`，脚本检查它来判断用户是否已配置 Key。因此：
- 用户在启动 dsh 的环境变量中配置 `DKNOWC_API_KEY` 即可（如 `~/.zshrc`），无需设置 `DSH_DKNOWC_API_KEY`；
- 配置生效后，`DSH_DKNOWC_API_KEY` 非空，门禁通过；**一次配置，之后免注册**；
- 若用户后续修改/替换 Key，只需更新 `DKNOWC_API_KEY` 并重启 dsh 或新建会话。

如果初始化结果中 `api_key_configured=false`，或 `blocking_issues` 包含 `api_key_missing`，**不要中断当前任务**，先引导用户完成 MaaS Key 获取（见下），拿到 Key 后**用临时直连完成当前任务**，任务完成后再建议持久化。

**重要：门禁失败时禁止先探测 MCP 工具。** 初始化失败（`api_key_missing`）已明确说明 Key 未配置，此时 `mcp__dknowc__credible_chat` 必然返回 401/unauthorized——**不要调用它来"确认是否可用"**，也不要绕回 MCP 不可用处理分支（那针对的是"Key 已配置但工具异常"的情况）。门禁失败后唯一正确路径是：直接向用户说明需要配置 API Key → 引导注册 → 拿到临时 Key → 用 `mcp_direct.py` 直调完成当前任务。

如果检测到未配置 Key，先暂停原任务并向用户说明：

```text
深知可信咨询需要通过 API Key 调用深知可信统一接口，获取可溯源的可信内容。当前还未检测到可用的 API Key，所以暂时不能继续查询。

你可以注册或登录深知可信智能 MaaS 账号获取 API Key。拿到 Key 后，本轮任务可以直接使用它完成查询；任务完成后，我会再询问你是否把它保存为后续可复用的环境变量。
```

MaaS Key 获取（通过本 Skill 的 `scripts/register_key.mjs`，使用 dsh 专属渠道码）：

```bash
node <skillDir>/scripts/register_key.mjs send --phone <手机号>
```

返回 `status=true` 后，暂停并向用户索取收到的 6 位验证码，不得自行编造验证码。拿到验证码后执行：

```bash
node <skillDir>/scripts/register_key.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

脚本自动使用 dsh 渠道码 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05` 并固定携带 `source="agent"`。成功后返回 `apiKey`（打码展示）与完整 Key（仅供当前任务临时使用）；不得向用户展示完整 API Key。默认不得重新生成 Key；只有用户明确要求时才追加 `--new-key`。

**临时直连完成当前任务（不依赖 dsh 的 mcp-client，也不要求立即持久化）**：注册拿到 Key 后，当前会话的 MCP Bearer 认证已冻结（无法热注入新 Key），因此本轮任务改用**临时 Key 直调 MCP** 完成——用 `DKNOWC_API_KEY=<临时Key> python3 <skillDir>/scripts/mcp_direct.py credible_chat '<JSON参数>' --output official-docs/search-results/dknowc_mcp_raw.json` 形式，把临时 Key 通过 bash 前缀赋值传给脚本（绕过 dsh 的环境清理），由 mcp_direct.py 直接 HTTP 调 MCP server 的 tools/call，产出与 dsh mcp-client 一致的 MCP 返回结构；随后照常走 `adapt_mcp_result.py` 规范化 → `render_trace_html.py` 生成溯源 HTML。**不要把临时 Key 写入环境变量或任何配置文件**。

**任务完成后的持久化（一次性，之后免注册）**：当前任务交付完成后，再询问用户是否需要把 `DKNOWC_API_KEY` 保存为后续可复用的环境变量（如追加到 `~/.zshrc`）。只有用户明确同意后，Agent 才能执行持久化写入；写入后建议用户重启 dsh 或新开会话，之后新会话会通过 MCP 转接正常使用。

## 核心约束

- 始终把用户原始问题通过 MCP 工具 `mcp__dknowc__credible_chat` 发起，把工具返回保存为 JSON 供溯源渲染使用。
- 最终给用户的答案必须带来源角标，例如 `[1]`、`[2]`。关键政策名称、条件、金额、比例、办理路径、适用范围、时间要求和风险判断都要挂接到真实支撑材料。
- 角标必须与接口返回的材料真实对应。不能用主题相近但未支撑该结论的材料挂角标；找不到依据时，应删除该结论、标为“需进一步核验”，或重新调用接口补证。
- 每次咨询后，默认必须生成本轮 HTML 溯源报告。只有用户明确说“不要生成 HTML/不要文件”时才跳过。
- HTML 报告应展示本轮最终答案正文、答案中的角标、右侧可信来源、段落下可展开的来源摘录，以及接口返回的知识专库入口（如有）。不要把 HTML 改写成另一个独立调研报告。
- 用户可见的 HTML 输出到本 Skill 的 `official-docs/output/`，中间产物（接口 JSON、答案文件）存 `official-docs/search-results/`。不要固定文件名，应让 `render_trace_html.py` 根据用户问题自动生成短文件名；不向 `/tmp` 写任何中间文件。
- 如果用户只是追问“你是否用了 skill”“你调用了几次”等元问题，不要再次调用本 skill；直接基于当前对话说明。

## 工作区约定（dsh）——脚本与产物的路径区分

- **脚本调用一律用 skill 目录的绝对路径**（resourceBase 指引里给出的 "Base directory for this skill: <path>" 就是 skill 目录，以下称 `<skillDir>`）。不要用 `scripts/xxx.py` 这种相对路径调用脚本——bash 命令的相对路径是基于当前工作区（session cwd）解析的，而脚本在 bundle 的 skill 目录里，相对路径会找不到。
- 因此所有脚本调用写成：`python3 <skillDir>/scripts/initialize.py`、`python3 <skillDir>/scripts/adapt_mcp_result.py`、`python3 <skillDir>/scripts/render_trace_html.py ...`。
- **运行产物（接口 JSON、答案文件、溯源 HTML）一律写入当前会话工作区**（即 bash 默认的当前工作目录），用相对路径 `official-docs/search-results/...`、`official-docs/output/...`。脚本已按 `WS_ROOT = 当前工作目录` 解析这些相对路径，产物会落到工作区，不会写进 bundle。
- 交付给用户的 HTML 路径，以 `render_trace_html.py` 实际打印的绝对路径为准。

## MCP 不可用处理（强制）

- 如果 `mcp__dknowc__credible_chat` 工具**不存在、调用失败、返回 401/403 鉴权错误或明确报鉴权失败**，说明 `DKNOWC_API_KEY` 未正确配置（dsh 主进程环境变量缺失或无效）。
- 此时必须**暂停原任务**，不得编造答案、不得改用 Web 搜索/网页抓取、不得绕过 MCP 直连接口、不得输出任何可替代正式咨询结果的结论。
- 向用户说明：需要将有效的 `DKNOWC_API_KEY` 配置到启动 dsh 的环境变量中（如 `~/.zshrc` 的 `DKNOWC_API_KEY`），然后重启 dsh 或新建会话后重试。
- 若用户已完成配置，可引导重新运行初始化确认后再继续。

## 标准流程（MCP 转接）

1. 先完成初始化门禁：

```bash
python3 <skillDir>/scripts/initialize.py
```

2. 调用 MCP 工具 `mcp__dknowc__credible_chat`，参数示例：

```json
{
  "query": "用户原始问题",
  "area": "用户明确指定的地域（可选，默认留空由接口识别）"
}
```

3. 把 MCP 工具返回的 JSON 保存到 `official-docs/search-results/dknowc_mcp_raw.json`。

4. 用适配脚本把 MCP 返回规范化成渲染脚本可消费的接口 JSON：

```bash
python3 <skillDir>/scripts/adapt_mcp_result.py official-docs/search-results/dknowc_mcp_raw.json \
  --output official-docs/search-results/dknowc_consulting.json \
  --mode chat
```

5. 读取规范化后 JSON 中的 `resp.content`、`referenceMaterials` 等字段。

6. 形成面向用户的最终答案：

- 如果接口正文已经适合作为最终答案，且带有可用角标，可直接使用。
- 如果需要整理、压缩、表格化或补充咨询判断，把整理后的最终答案保存到 `official-docs/search-results/dknowc_consulting_answer.txt`。
- 整理后的答案仍必须保留真实角标；不要新增无法对应到材料的角标。

7. 生成 HTML 溯源报告：

```bash
python3 <skillDir>/scripts/render_trace_html.py official-docs/search-results/dknowc_consulting.json \
  --title "深知可信咨询可信溯源" \
  --question "用户原始问题"
```

如果第 6 步生成了最终答案文件，必须传入：

```bash
python3 <skillDir>/scripts/render_trace_html.py official-docs/search-results/dknowc_consulting.json \
  --title "深知可信咨询可信溯源" \
  --question "用户原始问题" \
  --answer-file official-docs/search-results/dknowc_consulting_answer.txt
```

8. 回复用户：

- 先给最终答案，保留角标。
- 不要再给用户输出接口返回的 `可信溯源报告` 链接；本地 HTML 已承载同一类溯源信息。
- 给出本地 HTML 路径，使用 `render_trace_html.py` 实际打印的自动生成路径。
- 如接口材料不足，明确说明“当前接口返回材料不足以支撑某结论”，不要编造。

## 答案自检

生成 HTML 前检查：

- 答案中是否至少包含一个 `[数字]` 角标。
- 每个角标编号是否能在接口来源列表中找到。
- 每个被角标支撑的句子是否能从对应材料标题、摘要、段落摘录或原文链接中核验。
- 聊天答案和通过 `--answer-file` 传给 HTML 的答案是否一致。

如果答案没有角标而接口返回了来源材料，先重写答案再生成 HTML；不要交付仅有“未识别到正文角标”提示的报告。

## 说明

- 本 dsh 版接口调用走 MCP 转接层（`mcp__dknowc__credible_chat`），不再直连 `scripts/gov_chat.py`。`gov_chat.py` 保留在包内仅作离线兜底/参考，不作为默认路径。
- MCP 的 Bearer 认证使用环境变量 `DKNOWC_API_KEY`；接入方式见 bundle 的 `cordis.patch.yml`。
- `area` 默认留空，由接口根据问题识别地域；只有用户明确指定且需要覆盖时才传。
