---
name: dknowc-trusted-search
slug: dknowc-trusted-search
display_name: 深知可信搜索（法律、政策、标准）
display_name_en: dknowc trusted search
description: "当用户需要检索权威材料、政策法规/标准原文、政策清单、可点击溯源、知识专库、多地域政策素材收集与对比核验、企业补贴与税惠材料核验、合规依据核验，或明确要求深度搜索、深度分析、全面查找、多轮核验、完整调研方案时，使用深知可信搜索（法律、政策、标准）。本 skill 负责检索与核验材料，交付直接答案、可点击溯源 HTML 与干净 Markdown；如用户要求把素材写成正式报告、调研报告、分析报告或公文（如'帮我写一份××报告'），应改用深知公文写作 skill（dknowc-official-doc-writer）。"
description_zh: "深知可信搜索（法律、政策、标准）是由北京彩智科技有限公司旗下“深知可信智能”提供的可信搜索与权威材料检索 Skill，面向政策法规、政务办事依据、税务社保、公积金、企业补贴、资质证照、行业标准、公共服务、合规义务、政策调研、城市政策对比和企业投资/技改/税惠材料核验等工作场景。默认调用可信搜索接口，按需调用深度搜索接口，输出带权威来源、知识专库、可点击溯源 HTML 和干净 Markdown 的结果。"
description_en: "dknowc trusted search is a trusted search and authoritative-source retrieval Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It supports policy, regulation, government-service evidence, standards, compliance, subsidy, tax-benefit and policy research tasks. It defaults to trusted search, uses deep search only on explicit user request or confirmation, and delivers a direct answer, clickable provenance HTML, and clean Markdown without citation markers."
category: 通用办公
version: 1.1.2-dsh
author: 彩智科技
permissions:
  network:
    - "https://mcp.dknowc.cn/"
  local_read:
    - "本 Skill 的说明和脚本文件"
  local_write:
    - "本轮可信溯源 HTML、干净 Markdown、可交互政策可视化 HTML 报告（含可选 SVG 快照）和接口结果中间文件"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知可信搜索（法律、政策、标准）（dsh 版）

该 Skill 只负责“搜索型可信材料获取与核验”。简单咨询问答不再由本 Skill 处理；遇到需要直接咨询式问答的场景，应交给专门的深知可信咨询 Skill。

**dsh 接入方式**：本 skill 不再直连深知接口，而是通过深知可信工作台 MCP 工具获取数据——可信搜索用 `mcp__dknowc__trusted_search`，深度搜索用 `mcp__dknowc__deep_query`（MCP 作为接口转接层）。API Key 通过环境变量 `DKNOWC_API_KEY` 注入，用于 MCP client 的 Bearer 认证。

## 最高优先级规则

- 不使用统一咨询接口；本 Skill 不包含也不调用 `gov_chat.py`。
- 默认调用 MCP 工具 `mcp__dknowc__trusted_search`。即使问题比较复杂，也先通过可信搜索建立证据池，再判断是否需要向用户追问或建议深度搜索。
- 只有用户明确说“深度搜索、深度分析、全面查找、多轮核验、完整方案、深度核验”等意图，或在最终回复后确认升级，才调用 `mcp__dknowc__deep_query`。
- ReAct 逻辑保留：如果问题缺少会影响结论的关键信息，先追问；如果先搜索后发现证据不足或条件依赖明显，再向用户补问关键条件。
- 最终解决问题时必须同时交付三项：直接回复答案、可点击溯源 HTML、干净 Markdown。中间追问和阶段性 ReAct 过程不要求交付三件套。
- 最终答案必须先由 Agent 基于搜索材料综合形成，再保存为文本，通过 `render_trace_html.py --answer-file` 传入。HTML 和干净 Markdown 必须来自同一份最终答案。
- 最终答案中的关键事实、金额、比例、适用条件、办理路径、政策名称、标准条款等必须标来源角标，例如 `[1]`、`[2]`。角标必须能被接口返回的材料标题、摘要、段落摘录或原文支撑。
- 不得伪造、误配或泛配角标。找不到直接依据时，应删除该结论、标为“待核验/需以主管部门口径为准”，或继续搜索补证。
- 聊天回复默认不堆大量材料裸链接；保留核心结论、必要来源摘要、知识专库链接、溯源 HTML 路径和干净 Markdown 路径。
- 用户明确说“不要 HTML/不要文件”时，才跳过文件交付；否则 HTML 和干净 Markdown 是最终交付的一部分。

## 启动初始化

API Key 必须通过环境变量 `DKNOWC_API_KEY` 注入（供 MCP Bearer 认证）。只要本 Skill 被调用，第一步必须运行：

```bash
python3 <skillDir>/scripts/initialize.py
```

只有初始化结果满足 `ready=true`、`api_key_configured=true` 时才可进入流程；只要 `ready=true` 即可进入可信搜索、深度搜索、复杂任务 ReAct、政策调研、材料核验或任何可替代正式结果的输出流程。

**Key 检查机制（dsh）**：dsh 的安全机制会清理名字含 KEY 的隐式环境变量，脚本子进程读不到原始的 `DKNOWC_API_KEY`。本 bundle 插件会把 dsh 主进程的 `DKNOWC_API_KEY` 值经 shell-env 显式通道注入为 `DSH_DKNOWC_API_KEY`，脚本检查它来判断用户是否已配置 Key。因此：
- 用户在启动 dsh 的环境变量中配置 `DKNOWC_API_KEY` 即可（如 `~/.zshrc`），无需设置 `DSH_DKNOWC_API_KEY`；
- 配置生效后，`DSH_DKNOWC_API_KEY` 非空，门禁通过；**一次配置，之后免注册**；
- 若用户后续修改/替换 Key，只需更新 `DKNOWC_API_KEY` 并重启 dsh 或新建会话。

如果初始化结果中 `api_key_configured=false`，或 `blocking_issues` 包含 `api_key_missing`，**不要中断当前任务**，先引导用户完成 MaaS Key 获取（见下），拿到 Key 后**用临时直调 MCP 完成当前任务**，任务完成后再建议持久化。

**重要：门禁失败时禁止先探测 MCP 工具。** 初始化失败（`api_key_missing`）已明确说明 Key 未配置，此时 `mcp__dknowc__trusted_search` / `mcp__dknowc__deep_query` 必然返回 401/unauthorized——**不要调用它们来"确认是否可用"**，也不要绕回 MCP 不可用处理分支（那针对的是"Key 已配置但工具异常"的情况）。门禁失败后唯一正确路径是：直接向用户说明需要配置 API Key → 引导注册 → 拿到临时 Key → 用 `mcp_direct.py` 直调完成当前任务。

MaaS Key 获取（通过本 Skill 的 `scripts/register_key.mjs`，使用 dsh 专属渠道码）：

```bash
node <skillDir>/scripts/register_key.mjs send --phone <手机号>
```

返回 `status=true` 后，暂停并向用户索取收到的 6 位验证码，不得自行编造验证码。拿到验证码后执行：

```bash
node <skillDir>/scripts/register_key.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

脚本自动使用 dsh 渠道码 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05` 并固定携带 `source="agent"`。成功后返回 `apiKey`（打码展示）与完整 Key（仅供当前任务临时使用）；不得向用户展示完整 API Key。默认不得重新生成 Key；只有用户明确要求时才追加 `--new-key`。

**临时直调 MCP 完成当前任务（不依赖 dsh 的 mcp-client，也不要求立即持久化）**：注册拿到 Key 后，当前会话的 MCP Bearer 认证已冻结（无法热注入新 Key），因此本轮任务改用**临时 Key 直调 MCP** 完成——用 `DKNOWC_API_KEY=<临时Key> python3 <skillDir>/scripts/mcp_direct.py trusted_search '<JSON参数>' --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search_mcp_raw.json`（深度搜索用 `deep_query` 工具）形式，把临时 Key 通过 bash 前缀赋值传给脚本（绕过 dsh 的环境清理），由 mcp_direct.py 直接 HTTP 调 MCP server 的 tools/call，产出与 dsh mcp-client 一致的 MCP 返回结构；随后照常走 `adapt_mcp_result.py` 规范化 → `render_trace_html.py` 生成溯源 HTML 与干净 Markdown。**不要把临时 Key 写入环境变量或任何配置文件**。

**任务完成后的持久化（一次性，之后免注册）**：当前任务交付完成后，再询问用户是否需要把 `DKNOWC_API_KEY` 保存为后续可复用的环境变量（如追加到 `~/.zshrc`）。只有用户明确同意后，Agent 才能执行持久化写入；写入后建议用户重启 dsh 或新开会话，之后新会话会通过 MCP 转接正常使用。

## 工作区约定（dsh）——会话隔离的产物目录

- **脚本调用一律用 skill 目录的绝对路径**（resourceBase 指引里给出的 "Base directory for this skill: <path>" 就是 skill 目录，以下称 `<skillDir>`）。不要用 `scripts/xxx.py` 相对路径调用脚本——bash 的相对路径基于会话工作区解析，脚本在 bundle 的 skill 目录里，相对路径找不到。
- **产物按会话隔离存放**：每个 dsh 会话在工作区下有独立产物目录，bash 中写作 ``dknowc-output/${DSH_SESSION_ID:0:8}``（DSH_SESSION_ID 由 dsh 注入；本地无此变量时为 `dknowc-output/_default`）。完整路径形如 `dknowc-output/<会话短ID>/official-docs/...`。同一工作区开多个会话时产物互不混杂、互不覆盖。
- **运行产物（接口 JSON、答案文件、溯源 HTML、干净 Markdown、政策可视化 HTML）**一律写入**本会话**目录，用全前缀相对路径：`dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/...`、`dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/...`。脚本对裸文件名也会自动路由到本会话对应子目录。
- 交付给用户的文件路径，以脚本实际打印的路径为准。
- 会话目录仍位于工作区内（dsh 沙箱/权限不受影响），用户可在访达中直接浏览 `dknowc-output/` 找到各会话产物。


## MCP 不可用处理（强制）

- 如果 `mcp__dknowc__trusted_search` / `mcp__dknowc__deep_query` 工具**不存在、调用失败、返回 401/403 鉴权错误或明确报鉴权失败**，说明 `DKNOWC_API_KEY` 未正确配置（dsh 主进程环境变量缺失或无效）。
- 此时必须**暂停原任务**，不得编造材料、不得改用 Web 搜索/网页抓取、不得绕过 MCP 直连接口、不得输出任何可替代正式检索结果的结论。
- 向用户说明：需要将有效的 `DKNOWC_API_KEY` 配置到启动 dsh 的环境变量中（如 `~/.zshrc` 的 `DKNOWC_API_KEY`），然后重启 dsh 或新建会话后重试。
- 若用户已完成配置，可引导重新运行初始化确认后再继续。

## 标准工作流（MCP 转接）

1. 初始化：首次调用前运行 `python3 <skillDir>/scripts/initialize.py`，确认 `ready=true`、`api_key_configured=true`（`api_key_source` 为 `environment` 或 `mcp` 均可）。
2. 判断是否需要追问：如果缺少地域、主体、时间、事项类型、企业条件等关键变量且会改变结论，先问用户；否则先搜索。
3. 可信搜索：调用 MCP 工具 `mcp__dknowc__trusted_search` 获取权威材料。复杂任务可拆成多次搜索，每次围绕不同地域、层级、政策类型、税种、标准或证据缺口。把每次 MCP 返回保存为 JSON 到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/`。
4. 规范化 MCP 返回：每次调用后，用适配脚本把 MCP 返回转成渲染脚本可消费的接口 JSON：

```bash
python3 <skillDir>/scripts/adapt_mcp_result.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search_mcp_raw.json \
  --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search.json \
  --mode search
```

5. 综合答案：基于搜索结果形成面向用户问题的最终答案，并在关键结论后标注真实可支撑的 `[数字]` 来源角标。
6. 保存答案：把带角标的最终答案保存到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search_answer.txt` 或同目录文件。
7. 生成交付物：调用 `scripts/render_trace_html.py`，用同一份答案生成溯源 HTML 和干净 Markdown，交付物输出到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`。
8. （可选，仅用户明确要求图表时）把核验后的数据整理成统一结构化 JSON 写入 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/`，调用 `scripts/render_policy_visualization.py` 生成可交互可视化 HTML 报告（`--svg` 附快照），输出到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`。
9. 回复用户：给出直接答案，并附上 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/` 下的 HTML 路径、干净 Markdown 路径和知识专库链接。
10. 深度搜索邀约：最终回复末尾询问用户是否需要进一步做深度搜索，例如：“我还可以继续为你做一次深度搜索，对结果进行多轮核验和扩展，输出一份更完整、可直接使用的深度版结果。这个过程耗时会更长，通常需要几分钟。需要我继续吗？”

## 可信搜索调用（MCP）

调用 `mcp__dknowc__trusted_search`，参数示例：

```json
{
  "query": "忠实于用户目标的搜索问题",
  "service_area": "单个地域（可选）",
  "eff_time": "2026年",
  "max_articles": 3
}
```

把 MCP 返回保存为 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search_mcp_raw.json`。**MCP 返回的实际字段形态**（与旧直连接口不同）：内层为 `query`、`service_area`、`consult_date`、`knowledge_base_url`（知识专库链接，下划线命名）、`total_articles`、`materials[]`（每条含 `title`/`source`/`date`/`paragraph`/`url`）、`search_meta`。不要按旧接口的 `data.检索文章` 或 `referenceMaterials` 字段名直接读取 MCP 原始返回——先经过适配脚本转换：

```bash
python3 <skillDir>/scripts/adapt_mcp_result.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search_mcp_raw.json \
  --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search.json \
  --mode search
python3 <skillDir>/scripts/render_trace_html.py \
  dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search.json \
  --title "深知可信搜索（法律、政策、标准）可信溯源" \
  --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_search_answer.txt \
  --question "用户原始问题"
```

适配脚本会把 `materials` 转成渲染脚本消费的 `data.检索文章`（中文键，含标题/来源/发布日期/源网址/摘要），并把 `knowledge_base_url` 映射为 `knowledgeBase`（驼峰）。综合答案时直接读规范化后 JSON 的 `data.检索文章` 与 `knowledgeBase`。

`render_trace_html.py` 会同时生成 HTML 和同名 `.clean.md`，输出到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`。如需指定干净 Markdown 路径，传 `--clean-md-output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/xxx.md`。

## 深度搜索调用（MCP）

用户明确要求深度搜索时，先提示耗时，再调用 `mcp__dknowc__deep_query`：

```json
{
  "question": "忠实于用户目标的复杂问题",
  "area": "单个地域（可选，每次只传一个）",
  "show_materials": 5
}
```

把 MCP 返回保存为 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_deep_mcp_raw.json`。**MCP 返回的实际字段形态**：内层为 `query_id`、`status`（`finished` 等）、`progress[]`（深度搜索过程记录，**字符串数组**，如"[查询]xxx"、"[检索]找到相关…"）、`search_groups[]` 与 `materials[]`（深度材料，可能为空——部分任务完成后材料经过程聚合输出）、`timings`。深度搜索**不直接返回答案正文**：最终答案由你基于 `progress` 过程记录与 `materials` 材料综合形成，保存为答案文件后经 `--answer-file` 传入渲染。然后：

```bash
python3 <skillDir>/scripts/adapt_mcp_result.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_deep_mcp_raw.json \
  --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_deep.json \
  --mode deep
python3 <skillDir>/scripts/render_trace_html.py \
  dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_deep.json \
  --title "深知可信搜索（法律、政策、标准）深度搜索溯源" \
  --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/dknowc_deep_answer.txt \
  --question "用户原始问题"
```

适配脚本会把 `materials` / `search_groups` 中的材料归集为渲染脚本消费的 `data.list`，并保留 `progress` 过程记录。

多地域、多层级任务应拆成多次调用，例如中国、重庆市、重庆两江新区分别搜索。如果用户没有明确要求深度搜索，不要主动调用。先完成可信搜索版答案和三件套交付，再询问用户是否升级深度搜索。

## ReAct 与追问规则

- 信息不足且会实质影响结论时，先问 3-6 个最关键问题，例如地域、适用时间、主体类型、项目状态、企业规模、纳税人类型、资质、金额、申报目标。
- 如果缺失信息不影响先做初步判断，可先可信搜索，再基于材料反向追问需要用户确认的条件。
- 如果缺失信息只影响精度、不影响方向，可说明假设并推进，最终答案中标明“初步判断”“待确认事项”和下一步补充路径。
- 多次搜索时，每次调用前要有明确目的，不要机械拆词或重复查询。
- 所有政策、法规、标准、办事条件、申报路径和材料依据必须来自可信搜索或深度搜索结果。

## 参数规则（MCP 版）

可信搜索 MCP 工具的 `query`、`eff_time`、`service_area` 分工必须清楚。

- `query`：自然语言检索问题，聚焦一个层级、一个目的或一种材料类型；不要把多个年份、多个地域或内部调试目的堆进 query。
- `eff_time`：用户问题对应的办理/适用/生效时间，只能传一个值，格式为 `YYYY年`、`YYYY年MM月` 或 `YYYY年MM月DD日`。不要传 `2024-2025年`、`2024至2025年`、`2024 2025`。
- `service_area`：用户问题对应的单个办理地域/政策地域。不要传多个地域；国家层面用 `中国`，市级用城市，区县/园区用具体区县或园区。

推荐示例：

```json
{ "query": "重庆市智能化改造技改补贴政策", "service_area": "重庆", "eff_time": "2026年" }
{ "query": "两江新区工业机器人购置补贴申报条件", "service_area": "重庆两江新区", "eff_time": "2026年" }
{ "query": "企业购置专用设备企业所得税抵免政策", "service_area": "中国", "eff_time": "2026年" }
```

## 配置

本 dsh 版 API Key 统一且只通过环境变量 `DKNOWC_API_KEY` 注入（供 MCP Bearer 认证）；不得从配置文件、命令行参数或其他旧环境变量读取 API Key。本 Skill 不包含 `config.ini`。接口地址与参数由 MCP server 侧统一管理（`https://mcp.dknowc.cn/s6/mcp/`）。

## 可视化

用户明确要求“图表、对比图、热力图、柱状图、雷达图、时间线、流程图、材料清单表格、政策对比、补贴金额对比、政策时间分布”等表达时才生成，是显式触发能力，不属于默认三件套。默认三件套交付完成后，如用户再要求图表，按本流程补生成。

生成前，Agent 基于已核验的可信搜索结果，把数据整理为统一结构化 JSON（每个数据点必须带 `sources` 来源绑定）写入 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/`，再调用脚本。脚本离线运行、零网络依赖、不引用外部 CDN/字体，输出自包含可交互 HTML 报告（主交付）到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`，可选 `--svg` 追加一张静态 SVG 快照用于聊天内直接展示。

支持的场景（`metadata.scenario`，缺省自动识别，`--scenario` 可覆盖）：
- `city_compare` 地域/城市政策对比：对象×指标数据表（主视图）+ 每指标简单柱状对比
- `amount_compare` 补贴金额/税惠数值对比：对象×指标数据表 + 每指标简单柱状对比
- `process_steps` 办理流程/材料清单：流程步骤时间线、材料清单表格（必需/可选徽标）
- `timeline` 政策时间线/分布：横向时间轴（按地域或类型分轨）、按年/月分布直方图

**呈现原则：以“清楚展示搜索数据”为第一优先，不追求花哨。** 默认单页顺序排列，首屏即对象×指标数据表（原始值+单位），随后是每指标一张简单柱状图；不生成雷达图、排名列表、KPI 卡等主观评价模块。来源统一收敛：每行一个“来源”入口（点击展开该对象全部来源），全量来源清单集中到页脚。

统一 JSON schema 约定：
- `metadata`：`title/region/topic/scenario/source_note/question/consult_date/eff_time/knowledge_base_url`
- `metrics`（推荐显式声明）：`code/label/unit/scale/kind/direction`；不声明时自动识别数值列，并在报告中标注“自动口径，未做跨口径校准”。**指标要少而精**：只保留口径统一、能说明问题的关键指标（如最高补贴比例、封顶金额），不要把口径复杂/易误导的字段塞进图
- `items`：`name/positioning/keywords/metrics/note/sources`（兼容旧对比数据）
- `time`：`date/label/title/url/area/kind/detail/sources`
- `steps`：`step/title/detail/duration/owner/url/sources`
- `materials`：`name/required/note/sources`
- `sources`：URL 字符串或 `{url,title}` 对象组成的数组；每个数据点必须携带，用于行级溯源与页脚清单

调用示例：

```bash
python3 <skillDir>/scripts/render_policy_visualization.py \
  --input dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/viz_city_compare.json \
  --title "长三角城市智能制造补贴政策对比" --svg
```

默认输出 `<标题或scenario>_<时间戳>.html`；`--output` 指定文件名；`--scenario` 覆盖自动识别；`--svg` 同时输出同名 `.svg` 快照（仅含数据表对应的简单柱状对比）。输出只写 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`。HTML 为 AI 综合解读，金额等关键数值须能在对应来源原文找到依据，与三件套同一套核验口径。

## 说明

- 本 dsh 版接口调用走 MCP 转接层（`mcp__dknowc__trusted_search` / `mcp__dknowc__deep_query`），不再直连 `trusted_search.py` / `deep_query.py`。这两个脚本保留在包内仅作离线兜底/参考，不作为默认路径。
- MCP 的 Bearer 认证使用环境变量 `DKNOWC_API_KEY`；接入方式见 bundle 的 `cordis.patch.yml`。
