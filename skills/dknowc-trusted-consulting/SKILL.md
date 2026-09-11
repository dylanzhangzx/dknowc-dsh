---
name: dknowc-trusted-consulting
slug: dknowc-trusted-consulting
display_name: 深知可信咨询
display_name_en: dknowc trusted consulting
description: "当用户咨询政策法规、政务办事、税务社保、公积金、企业补贴、资质证照、行业标准、公共服务、合规义务、企业经营政策、投资技改税惠、办事条件、材料清单、申请路径、风险判断，或要求权威依据、可信溯源、带角标答案、深知可信咨询时，使用深知可信咨询。本 dsh 版通过深知可信工作台 MCP 工具 credible_chat 获取答案和参考材料，输出带真实来源角标和来源清单的咨询答案，并默认生成本轮可交互可信核验报告 HTML（首屏核验报告单：依据溯源/引用对应/材料新旧/交付前检查）与移除角标的干净 Markdown。API Key 通过环境变量 DKNOWC_API_KEY 注入（供 MCP Bearer 认证）。"
description_zh: "深知可信咨询是由北京彩智科技有限公司旗下“深知可信智能”提供的可信咨询 Skill，面向政策法规、政务办事、税务社保、公积金、企业补贴、资质证照、行业标准、公共服务、合规义务、企业经营政策和办事导办等场景。它通过 MCP 调用可信统一问答接口，输出带权威来源角标和本地可点击核验报告 HTML 的精准咨询结果。"
description_en: "dknowc trusted consulting is a trusted consultation Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It answers policy, regulation, government service, tax, social security, housing fund, enterprise subsidy, licensing, industry standard, compliance and public-service questions through the trusted unified chat API (via MCP), with citation markers and local verification HTML."
category: 通用办公
version: 1.2.1-dsh
author: 彩智科技
permissions:
  network:
    - "https://mcp.dknowc.cn/"
  local_read:
    - "本 Skill 的说明和脚本文件"
  local_write:
    - "本轮可信核验报告 HTML、干净 Markdown 和接口结果中间文件"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知可信咨询（dsh 版）

本 skill 用于通过深知可信统一问答接口回答用户咨询问题，并生成带角标的本地可信核验报告 HTML。它只覆盖统一接口 `credibleChat` 能力；不要在本 skill 中使用可信搜索、深度搜索或政策可视化流程。

**dsh 接入方式**：本 skill 不再直连深知接口，而是通过深知可信工作台 MCP 工具 `mcp__dknowc__credible_chat` 获取数据（MCP 作为接口转接层）。API Key 通过环境变量 `DKNOWC_API_KEY` 注入，用于 MCP client 的 Bearer 认证；不得硬编码，不得写入公开包，不得在对话中展示完整内容。

## 启动初始化

只要本 Skill 被调用，第一步必须运行：

```bash
python3 <skillDir>/scripts/initialize.py
```

只有初始化结果满足 `ready=true`、`api_key_configured=true` 时才可进入流程；`api_key_source` 为 `environment` 或 `zshrc` 均可。

**Key 检查机制（dsh，三级解析）**：dsh 的安全机制会清理名字含 KEY 的隐式环境变量，脚本子进程读不到原始的 `DKNOWC_API_KEY`。脚本按以下顺序解析：
1. `DSH_DKNOWC_API_KEY`——本 bundle 插件把 dsh 主进程的 `DKNOWC_API_KEY` 值经 shell-env 显式通道注入（与 MCP Bearer 同源）；
2. 进程环境变量 `DKNOWC_API_KEY`（本地裸跑 / bash 前缀临时注入）；
3. `~/.zshrc` 兜底解析（`api_key.py` 同源逻辑）——注册成功后 register_key.mjs 自动把 Key 持久化到 `~/.zshrc`，dsh 主进程在写入之后、重启之前的窗口期内环境变量还没有它，此时不误报缺失。

因此：用户在启动 dsh 的环境变量中配置 `DKNOWC_API_KEY`（如 `~/.zshrc`）即可；配置后**一次配置，之后免注册**；修改/替换 Key 后重启 dsh 或新建会话生效。`api_key_source=zshrc` 时（窗口期），本会话的 MCP Bearer 认证已冻结——**当前任务经 `scripts/mcp_direct.py` 直调完成**（脚本自动从 `~/.zshrc` 解析 Key），重启 dsh 或新开会话后自动恢复正常 MCP 转接。

如果初始化结果中 `api_key_configured=false`，或 `blocking_issues` 包含 `api_key_missing`，**不要中断当前任务**，按下面的开通引导规则向用户说明并引导开通（`guide_message` 优先原样转述），拿到 Key 后**用临时直调 MCP 完成当前任务**（见下），任务完成后建议重启 dsh；用户明确拒绝或犹豫时按退路降级交付，不得反复劝说。

**重要：门禁失败时禁止先探测 MCP 工具。** 初始化失败（`api_key_missing`）已明确说明 Key 未配置，此时 `mcp__dknowc__credible_chat` 必然返回 401/unauthorized——**不要调用它来"确认是否可用"**，也不要绕回 MCP 不可用处理分支（那针对的是"Key 已配置但工具异常"的情况）。门禁失败后唯一正确路径是：直接向用户说明需要配置 API Key → 引导注册 → 拿到 Key → 用 `mcp_direct.py` 直调完成当前任务。

## 开通引导规则（价值前置、时机后移、可退路）

向用户引导时必须做到：

- **引导前禁示**：在用户确认开通或明确拒绝之前，不得输出任何"已核实 / 已查到 / 权威口径是"类答案内容——可信结论只能来自真实接口调用或"未联网核验"标注，禁止用模型自身知识冒充可信咨询结果。
- **脚本 `user_message` 优先原样转述**：register_key.mjs / initialize.py 输出的 `user_message` 字段是给用户的固定话术，要素（安全边界、额度数字、平台地址、"最新一条"提示）不可删改；静态场景用 `reference/onboarding_scripts.md` 的话术库。
- **样例悬念式出示**：用户在 S1 后未立即同意或提出任何疑问，立即出示 `reference/sample_trace_report.html` 并按话术库 S1·附 说明；示例仅供展示，不作素材、不当交付物。
- 结合当前任务和用户语气自然表达，禁止逐字照抄固定模板，禁止说明书式复述流程。
- 不得向用户暴露内部术语和流程名，如"MaaS""API Key""环境变量 `DKNOWC_API_KEY`"等；用户侧只表达为"开通可信咨询功能"，不说"注册""注册账号"。
- 先价值、后验证：必须先让用户理解可信咨询对当前这个问题的价值（权威口径、带出处、可核验），再提出手机号验证；不得开口就要手机号。
- 引导时机尽量后置：优先在用户确认咨询需求或表现出对权威答案的期待之后再引导开通；不要在任务一开始就要求验证。
- 解释要点：① 为什么需要：这个问题涉及具体的办事条件、金额口径或政策判断，凭记忆回答容易过时或记错地区差异，答错影响办事和决策，且普通回答说不清出处；开通后答案基于权威文件库原文，结论可溯源、可核验。② 有什么不一样：基于权威文件库作答（覆盖 600 万篇公开规范性文件、7000 万篇可溯源的权威公开资料，每日更新，覆盖 54 个行业、300 多个地市、2800 多个县），不是普通 AI 联网回答；关键结论带角标、附溯源报告。③ 怎么开：手机号收一次验证码，两步、约 10 秒，不用去网站、不用填表单，其余由 Agent 代办。
- 安全与边界说明（用户问起或犹豫时按需说明，不点名具体平台）：手机号仅用于本次验证，不发营销短信、不打营销电话；本 Skill 已通过所在平台的安全审核上架，服务由北京彩智科技提供；验证后只在本机保存一个访问密钥，用户的对话和材料不会上传；不用了可随时注销。
- 给退路（唯一形态）：用户拒绝或犹豫时，不得反复劝说、不得纠缠；基于模型已有知识作答，并在回答开头或结尾明确标注"未联网核验、政策口径可能过期或存在地区差异"，不使用来源角标冒充可信结论，不生成本轮核验报告；用户后续主动提出开通时再执行注册。说退路时不得承诺"用联网检索替代/同样可核验"——外部检索来源不可控，属违规承诺。
- 交付后轻提示：未开通的用户得到降级回答后，可自然带一句"以后遇到政策口径、办事条件这类问题，可开通可信咨询，每条结论都带原文出处"；每个任务最多提示一次，不追问、不重复。
- 如需向用户介绍可信咨询的能力说明、安全说明和分场景话术范例，参考 `reference/consult_intro.md`；用户犹豫或询问效果时，可读取 `reference/sample_consult_answer.md` 和 `reference/sample_trace_report.html` 向用户展示带角标回答和可信核验报告的效果。两个示例文件均为示例数据，仅供展示，不得作为答案素材引用，不得发给用户当作交付物。所有说明用自己的话自然组织，不得整段照抄参考文件。

首次使用深知可信咨询需要先完成深知可信统一接口账号初始化。本 Skill 的 `scripts/register_key.mjs` 负责发送验证码、注册/查回 Key、可选新建 Key；**注册成功后自动把 Key 写入 `~/.zshrc` 标记块**（`--no-zshrc` 可跳过，回执 `envWriteSucceeded`）。

MaaS Key 获取按两步流程执行（通过本 Skill 的 `scripts/register_key.mjs`，使用 dsh 专属渠道码）：

```bash
node <skillDir>/scripts/register_key.mjs send --phone <手机号>
```

返回 `status=true` 后，暂停并向用户索取收到的 6 位验证码，不得自行编造验证码。拿到验证码后执行：

```bash
node <skillDir>/scripts/register_key.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

注册请求自动使用 dsh 渠道码 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`，并固定携带 `source="agent"`；不传 `type` 字段（注册接口已不再需要）。如果手机号已注册，MaaS 会在验证码校验通过后查回该账号已有可用 API Key；默认不主动新建 Key。成功后，脚本返回 `envName=DKNOWC_API_KEY`、`apiKey`、`apiKeyMasked`、`user_message` 与 `envWriteSucceeded`（自动持久化回执）。不得向用户展示完整 API Key，不得要求用户手动复制 API Key。`user_message` 按固定话术原样转述。

默认不得重新生成 API Key。只有用户明确要求“重新生成 Key”“新建一个 Key”“不要用旧 Key”等表达时，才在上述注册命令后追加 `--new-key`：

```bash
node <skillDir>/scripts/register_key.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户 --new-key
```

`--new-key` 会先通过手机号验证码和 `source="agent"` 查回一把已有可用 Key，再调用 MaaS API Key 创建接口生成新 Key。新 Key 创建失败时，脚本会自动沿用现有密钥继续，并在 `user_message` 中如实告知（不把旧 Key 冒充新 Key）；按脚本输出转述即可，不必中断任务。

**拿到 Key 后的当前任务（dsh 临时直调）**：注册成功脚本已自动把 Key 写入 `~/.zshrc`；当前会话的 MCP Bearer 认证在启动时已冻结（无法热注入新 Key），因此本轮任务改用**临时 Key 直调 MCP** 完成——`mcp_direct.py` 会自动从环境变量或 `~/.zshrc` 解析 Key，直接 HTTP 调 MCP server 的 tools/call，产出与 dsh mcp-client 一致的 MCP 返回结构；随后照常走 `adapt_mcp_result.py` 规范化 → `render_trace_html.py` 生成核验报告：

```bash
python3 <skillDir>/scripts/mcp_direct.py credible_chat '<JSON参数>' --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_mcp_raw.json
```

**持久化与重启**：`envWriteSucceeded=true` 时无需任何额外动作，也不要重复写入；仅当 `envWriteSucceeded=false`（写入失败或 `--no-zshrc`）时，按 `persistInstruction` 处理后续持久化。交付当前任务后建议用户**重启 dsh 或新建会话**，之后新会话会通过 MCP 转接正常使用（Key 已在 `~/.zshrc`，dsh 主进程启动时自动加载）。

如用户不希望通过脚本获取 Key，给出管理平台登录页供其自助开通：https://platform.dknowc.cn/auth/#/login ；随后按退路规则降级交付，不因此阻塞任务。

## 核心约束

- 始终把用户原始问题通过 MCP 工具 `mcp__dknowc__credible_chat` 发起（临时直调场景经 `mcp_direct.py`），把工具返回保存为 JSON 供核验报告渲染使用。
- 最终给用户的答案必须带来源角标，例如 `[1]`、`[2]`。关键政策名称、条件、金额、比例、办理路径、适用范围、时间要求和风险判断都要挂接到真实支撑材料。
- 角标必须与接口返回的材料真实对应。不能用主题相近但未支撑该结论的材料挂角标；找不到依据时，应删除该结论、标为“需进一步核验”，或重新调用接口补证。
- 每次调用统一接口后，默认必须生成本轮可信核验报告 HTML 和移除角标的干净 Markdown。只有用户明确说“不要生成 HTML/不要文件”时才跳过。
- 核验报告应展示：首屏核验报告单（四项指标）、咨询问题、本轮最终答案正文（角标可点击定位材料）、右栏核验材料面板（搜索/未引用素材分组），以及右栏底部的"云端溯源存档"区（取接口返回的 `traceUrl`，如有）。统一问答接口不返回搜索类知识专库链接，`traceUrl` 是云平台为本次问答留存的接口侧可信溯源报告：本地报告用于离线查阅与打印归档，云端存档适合向他人出示查验、也可在本地文件遗失时兜底；逐条核验以来源卡上的"查看原文"链接为准。不要把报告改写成另一个独立调研报告。
- 用户可见的核验报告输出到本会话 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`，中间产物（接口 JSON、答案文件）存 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/`。不要固定文件名，应让 `render_trace_html.py` 根据用户问题自动生成短文件名；不向 `/tmp` 写任何中间文件。
- API Key 只能通过环境变量 `DKNOWC_API_KEY` 注入（dsh 场景脚本会依次检查 `DSH_DKNOWC_API_KEY` / 环境变量 / `~/.zshrc`），不要从配置文件、命令行参数或聊天内容读取或展示。
- 接口报错按脚本输出的 `user_message` 转述并遵守其行为约束；**HTTP 402/429（额度）禁止任何形式重试**（不重发、不换问法、不当网络异常反复调用），确认处理前不再调用接口，按退路降级交付。
- 如果用户只是追问“你是否用了 skill”“你调用了几次”等元问题，不要再次调用本 skill；直接基于当前对话说明。

## 工作区约定（dsh）——会话隔离的产物目录

- **脚本调用一律用 skill 目录的绝对路径**（resourceBase 指引里给出的 "Base directory for this skill: <path>" 就是 skill 目录，以下称 `<skillDir>`）。不要用 `scripts/xxx.py` 相对路径调用脚本——bash 的相对路径基于会话工作区解析，脚本在 bundle 的 skill 目录里，相对路径找不到。
- **产物按会话隔离存放**：每个 dsh 会话在工作区下有独立产物目录，bash 中写作 ``dknowc-output/${DSH_SESSION_ID:0:8}``（DSH_SESSION_ID 由 dsh 注入；本地无此变量时为 `dknowc-output/_default`）。完整路径形如 `dknowc-output/<会话短ID>/official-docs/...`。同一工作区开多个会话时产物互不混杂、互不覆盖。
- **运行产物（接口 JSON、答案文件、核验报告 HTML、干净 Markdown）**一律写入**本会话**目录，用全前缀相对路径：`dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/...`、`dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/...`。脚本对裸文件名也会自动路由到本会话对应子目录。
- 交付给用户的文件路径，以脚本实际打印的路径为准。
- 会话目录仍位于工作区内（dsh 沙箱/权限不受影响），用户可在访达中直接浏览 `dknowc-output/` 找到各会话产物。dsh 的 Web 界面直接以工作区为文件视图，产物落工作区即对用户可见，无需额外的"交付复制"步骤。


## MCP 不可用处理（强制）

- 如果 `mcp__dknowc__credible_chat` 工具**不存在、调用失败、返回 401/403 鉴权错误或明确报鉴权失败**，说明 `DKNOWC_API_KEY` 未正确配置（dsh 主进程环境变量缺失或无效，且 `~/.zshrc` 中也没有）。
- 此时必须**暂停原任务**，不得编造答案、不得改用 Web 搜索/网页抓取、不得绕过 MCP 直连接口、不得输出任何可替代正式咨询结果的结论。
- 向用户说明：需要将有效的 `DKNOWC_API_KEY` 配置到启动 dsh 的环境变量中（如 `~/.zshrc` 的 `DKNOWC_API_KEY`），然后重启 dsh 或新建会话后重试。
- 若 `~/.zshrc` 已有 Key（`api_key_source=zshrc` 的窗口期），当前任务改用 `mcp_direct.py` 直调完成，不视为 MCP 故障；重启 dsh 后自动恢复。
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

3. 把 MCP 工具返回的 JSON 保存到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_mcp_raw.json`。

4. 用适配脚本把 MCP 返回规范化成渲染脚本可消费的接口 JSON：

```bash
python3 <skillDir>/scripts/adapt_mcp_result.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_mcp_raw.json \
  --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting.json \
  --mode chat
```

5. 读取规范化后 JSON 中的字段（MCP 返回的实际形态）：`answer`（接口答案正文，含角标）、`referenceMaterials`（参考材料，含 title/url/sourceUrl/content 摘录）、`policyFiles`（政策文件原文清单）、`recommendationItems`（办事事项，含线上办理入口）、`trace_report_url`（接口侧溯源报告链接，适配层已映射为 `traceUrl`，由核验报告"云端溯源存档"区承载，不在对话中输出）。

6. 形成面向用户的最终答案：

- 如果接口正文已经适合作为最终答案，且带有可用角标，可直接使用。
- 如果需要整理、压缩、表格化或补充咨询判断，把整理后的最终答案保存到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting_answer.txt`。
- 整理后的答案仍必须保留真实角标；不要新增无法对应到材料的角标。

7. 生成可信核验报告（含答案自检文件，见"答案自检"节）：

```bash
python3 <skillDir>/scripts/render_trace_html.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting.json \
  --title "深知可信咨询核验报告" \
  --question "用户原始问题" \
  --self-check-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting_selfcheck.json
```

如果第 6 步生成了最终答案文件，必须传入：

```bash
python3 <skillDir>/scripts/render_trace_html.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting.json \
  --title "深知可信咨询核验报告" \
  --question "用户原始问题" \
  --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting_answer.txt \
  --self-check-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting_selfcheck.json
```

`render_trace_html.py` 会同时生成可信核验报告 HTML 和同名 `.clean.md`（移除全部角标的干净 Markdown），输出到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`，文件名形如 `问题前缀_可信核验报告_年月日_时分.html`。如需指定干净 Markdown 路径，传 `--clean-md-output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/xxx.md`。"来源"清单只属于对话输出：即使答案文件末尾带了来源清单，脚本也会在生成核验报告和 clean.md 前自动去除该块——报告的来源由右栏核验材料面板承载，clean.md 保持纯正文。

脚本还会在 stdout 输出三样重编号结果（接口材料自带全量召回序号如 126、601，脚本统一重编号为 1..n）：① `dknowc_consulting_answer_final.txt` 路径（重编号后的最终答案）；② 角标映射（如 `[126]→[1]`）；③ 现成的"对话来源清单"（已重编号、只含被引用材料）。**对话回复的正文和来源清单必须直接使用这些输出**，保证对话、核验报告、干净 Markdown 三处编号一致；不要自行用接口原始序号组装备注和清单。

核验报告规则：

- 首屏为核验报告单：依据溯源 / 引用对应 / 材料新旧 / 交付前检查 四项指标（均由脚本真实计算）；统一问答接口不返回材料类型字段（类型为公文写作 Skill 自定概念），本 Skill 不设类型标签与材料构成指标；政策现行效力无法自动判定，如实列为"现行效力 · 建议人工复核"。
- 报告按"一篇材料一张卡"组织：接口返回的同一篇多段落合并为摘录，不再按段拆卡（杜绝角标语义错位）；摘录上方标注"▍ 原文原段（非 AI 生成）"，超 4 行折叠可"展开全文"；材料卡展示"标题：章节位置"链与"高可信"徽标（发布日期可信度为高）。
- 右栏核验材料面板：正文引用材料按编号排列并计入核验结论；接口召回但答案未采用的材料置于"未引用素材"分组（灰标，不计入核验结论，缺链不影响通过）。
- 交付状态约束：核验报告是交付物，交付时必须为核验通过状态。Agent 可修正的问题——答案无角标、角标未绑定材料、答案自检未全部通过、缺少自检文件——都会被脚本在生成前硬校验拒绝，必须修正后重跑，不得带问题交付；仅接口未返回原文链接、政策效力无法自动判定等不可抗因素在报告内以温和提示呈现（如"接口未返回原文链接，可经摘录与知识专库回看"），不作为核验失败。
- 角标编号：渲染时被引用角标按首次出现顺序重编号为 1..n（接口材料自带全量召回序号如 101、601，不直接透传），未引用材料顺延编号。
- 移动端（≤680px）点击角标或证据灰框，底部弹层顶部展示"正文表述（AI 生成）↔ 原文原段（非 AI 生成）"对照区 + 材料卡；支持浏览器打印归档（自动切换单栏全展开）。

8. 回复用户（三件套交付：带角标答案 + 可信核验报告 HTML + 干净 Markdown）：

- 先给最终答案（正文使用 `dknowc_consulting_answer_final.txt` 的重编号内容），保留角标；答案末尾附"来源"清单，**直接使用脚本打印的"对话来源清单"**（已按 `[n]《材料标题》· 发布机构 · 日期` 格式、重编号、只含被引用材料生成）。不得罗列接口返回的全部材料，不得使用接口原始序号。
- 不要再给用户输出接口返回的 `可信溯源报告` 链接；本地核验报告已承载同一类核验信息。
- 给出核验报告 HTML 路径和干净 Markdown 路径，均使用 `render_trace_html.py` 实际打印的路径。
- 如接口材料不足，明确说明“当前接口返回材料不足以支撑某结论”，不要编造。

## 答案自检

生成核验报告前检查，并把五项结果如实写入 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_consulting_selfcheck.json`：

- 答案中是否至少包含一个 `[数字]` 角标。
- 每个角标编号是否能在接口来源列表中找到。
- 每个被角标支撑的句子是否能从对应材料标题、摘要、段落摘录或原文链接中核验。
- 聊天答案和通过 `--answer-file` 传给核验报告的答案是否一致。
- 答案末尾的“来源”清单是否覆盖答案中出现的全部角标，且每条来源信息与接口返回材料一致。

自检 JSON 格式（键用中文名，值支持 `通过`/`pass`/`✓`/`通过：说明文字` 等写法）：

```json
{"角标存在": "通过", "角标对应来源": "通过：3 个角标全部命中来源材料", "结论可核验": "通过", "答案一致": "通过：与对话输出一致", "来源清单覆盖": "通过"}
```

如果答案没有角标而接口返回了来源材料，先重写答案再生成核验报告；脚本也会硬校验拒绝无角标答案，不要尝试绕过。

## 说明

- 本 dsh 版接口调用走 MCP 转接层（`mcp__dknowc__credible_chat`），不再直连 `scripts/gov_chat.py`。`gov_chat.py` 保留在包内仅作离线兜底/参考（报错话术与 `user_message` 同源），不作为默认路径。
- MCP 的 Bearer 认证使用环境变量 `DKNOWC_API_KEY`；接入方式见 bundle 的 `cordis.patch.yml`。
- `area` 默认留空，由接口根据问题识别地域；只有用户明确指定且需要覆盖时才传。
- dsh 的 Web 界面直接以工作区为文件视图：核验报告与干净 Markdown 落在会话工作区即对用户可见（访达同样可直达），无需宿主环境交付复制步骤。

## 参考资料（渐进式读取）

| 文件 | 阶段 | 加载条件 |
|---|---|---|
| `reference/onboarding_scripts.md` | 引导/注册/报错时 | 注册漏斗 S1-S6 固定话术、接口报错话术与行为约束、FAQ、通用禁则（脚本 user_message 优先，本文件兜底） |
| `reference/consult_intro.md` | 引导用户时 | 可信咨询能力与数据素材（统一口径）、引导时机与顺序、安全与边界说明 |
| `reference/sample_consult_answer.md` | 引导用户时 | 用户对回答效果有疑问或犹豫，需展示带角标回答形态 |
| `reference/sample_trace_report.html` | 引导用户时 | 需要向用户展示可信核验报告效果 |
