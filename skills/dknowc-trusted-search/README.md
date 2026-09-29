# 深知可信搜索（法律、政策、标准）（dsh 版）

这是深知可信搜索（法律、政策、标准）的 SkillHub Public 分发版本。功能逻辑与 full 版对齐，不再调用统一咨询接口；检索统一走本 Skill 脚本通道（1.3.5 起彻底回退 MCP 通道，MCP 大结果落盘方案效果有问题，待技术侧改造后恢复）。本版本不内置 API Key；优先从环境变量 `DKNOWC_API_KEY` 读取，宿主进程读不到 shell 环境变量时自动从本机专用配置文件 `~/.config/dknowc/api_key` 读取（历史 `~/.zshrc` Key 块迁移期兜底，避免 WorkBuddy 等宿主误报缺 Key）；未配置时 Agent 可先通过 MaaS 手机号验证码流程获取 Key（注册成功自动写入专用配置文件并清理旧 zshrc 块）。

## 能力范围

- 可信搜索：查找原文、依据、权威材料或来源时调用 `scripts/trusted_search.py`（API Key）返回重点来源文章；**按问题复杂度分级，判据是"先数对象"**——**只有 1 个对象/地域**（含"北京有哪些租房补贴政策""怎么申请""条件是什么"这类单地域枚举、单点事实、单政策解读）走可信搜索建证据池；**≥2 个对象/地域要放在一起比、跨地域跨层级聚合、或用户明确表达深度意图**时才用 `scripts/deep_query.py` **单路**深度搜索（query 直接用用户原始问题、默认不传地域，服务端按 query 中的地域概念自动拆子查询）；**拿不准时先走可信搜索**，证据不足再升级。政策依据型再以可信搜索补搜文号/原文。
- 深度搜索：仅在用户明确要求或确认升级后，调用 `scripts/deep_query.py`（deep-query/v3，非流式）做多轮检索和分析。
- 最终交付：直接回复答案、溯源核验报告 HTML、无来源角标的干净 Markdown。**角标编号契约**：答案里 `[n]` 的 n = 该材料在本次传入 JSON（多路检索为合并产物，每篇带 `编号` 字段）中的 1-based 序号；必须边写边标，禁止写完正文再回头反查补标——编号写错会静默绑到另一份材料，核验单不会报错（渲染器只重排"展示编号"，不解绑绑定关系）。
- 默认核验报告：最终解决问题时，用 `scripts/render_trace_html.py` 生成《标题_溯源核验报告_时间戳.html》（1.3.0 起对齐公文写作 3.7.0 重构：核验报告/知识专库双视图、句后引文胶囊原地展开溯源卡、章节引用徽章、复制全文与打印归档、检索分组 tabs 与热词筛选；核验报告单五项指标全部真实计算，正常结论即"核验完成"——缺原文链接黄色提醒不拖垮结论；生成前内置 policyFiles 文号匹配、原文链接活性检测、存档快照兜底；生成前硬校验答案必须有 [n] 角标且逐条绑定材料），并同步生成同名 `.clean.md`；`--self-check-file` 传入答案自检结果。
- 宿主环境交付：交付前运行 `scripts/deliver_outputs.py`，自动探测宿主工作区（WorkBuddy 等）复制产出物并返回用户可见路径；多会话并发（最新两个工作区间隔小于 10 分钟）时判定歧义，停止自动复制并要求 `--dest` 指定。
- 政策可视化（1.4.0 起**并入核验报告，只有这一条路**）：需要图表时，把带来源的结构化图表 JSON 写入 `official-docs/search-results/`，用 `render_trace_html.py --charts-json` 与核验报告**一次成稿**——图表跟着数据走：`metadata.section` 指定所属章节、直接插进该章正文之后（如奖励金额对比的图就排在"奖励金额对比"那一节里）；缺锚点时才退化为核验报告单之后的独立"数据可视化"章节，**一次任务只交付 1 个 HTML，任何时候都不产出第二份图表报告**。是否画图有明确判据：用户明确要图（图表/柱状图/折线图/饼图/环形图/可视化/画个图…）必须画；用户没提时 Agent 可自行判断，但须同时满足"≥2 对象/时点/构成项可比 + 数值可绑定来源 + 图比文字更易读 + 结论是数据性的"四条（`对比/梳理/分析/系统` 等分析措辞不算画图指令）。可用图型只有四类：对象×指标→柱状、趋势→折线、并列对比→分组柱、构成占比→环形；不做地图。**用包内定制版 ECharts 内联渲染**（`resources/echarts.custom.min.js` 526KB 定制构建，单文件完全离线可开），点击图表项跳转来源原文；资源缺失或数据不足（<2 点/系列）整章略过、不阻断报告。

## 首次启动初始化

只要调用本 Skill，Agent 必须先运行：

```bash
python3 <skillDir>/scripts/initialize.py
```

只有返回 `ready=true`、`api_key_configured=true`、`api_key_source` 为 `environment`、`keyfile` 或 `zshrc` 后才继续处理原任务。初始化未通过时，只允许引导用户完成 MaaS Key 获取或环境变量配置，不得先输出答案、草稿、大纲、材料清单或分析结论。

## MaaS 注册与环境变量配置

当前版本统一通过 `DKNOWC_API_KEY` 提供 Key（读取顺序：环境变量 → 本机专用配置文件 `~/.config/dknowc/api_key` → 历史 `~/.zshrc` 迁移期兜底），不扫描或复用其他深知系列 Skill 的本地 `config.ini`，业务调用脚本经 `api_key.py` 统一解析、不读取 `config.ini` 或传入 `szUserId`。如当前环境变量未配置：

- 可运行 `scripts/register_key.mjs` 发送验证码并注册/查回 Key（send/register 各分支输出 `user_message` 固定话术，Agent 必须原样转述）；宿主提供「深知可信工作台」（dknowc-mcp）且用户已完成 OAuth 授权时，优先经其 `create_api_key` 工具直接取 Key 并用 `save-key` 子命令落盘，免去手机号验证码（随公文写作 3.7.7 移植）。
- 所有向深知 MaaS 发请求的脚本（trusted_search / deep_query / register_key.mjs）统一携带 `X-Dknowc-Attribution` 来源声明头（`kind=skill;source=dknowc-trusted-search;version=…;channel=skillhub`，读包根 `attribution.json` + SKILL.md version 动态构造；仅统计用、不参与鉴权，读取失败不加头不阻断）。
- 注册成功自动把 Key 写入本机专用配置文件 `~/.config/dknowc/api_key`（600 权限，`--no-persist` 跳过；跳过后可用 `persist` 命令补写），并清理历史 `~/.zshrc` Key 块；业务脚本与 `initialize.py` 直读该文件，无需重启宿主。
- 返回的 `apiKey` 先供当前任务临时注入 `DKNOWC_API_KEY` 继续执行。
- MaaS 平台登录页：`https://platform.dknowc.cn/auth/#/login`

## 开通引导（1.2.1 起固定话术）

初始化检测到 Key 未配置时输出 `guide_message`（S1 三段式：价值 / 权益+开通方式 / 退路+样例钩子），Agent 优先原样转述；注册漏斗与报错场景的完整固定话术见 `reference/onboarding_scripts.md`（S1-S6 场景话术、注册与搜索链路报错对照表、FAQ、通用禁则）。核心纪律：引导前禁示（确认前不得输出"已核实/已查到"类内容）、权益前置（注册赠送 10 万积分 + 实名认证再送 10 万积分在引导时告知）、退路唯一（"依据待核验"标注，禁止承诺联网检索替代）、手机号全程脱敏。用户犹豫或询问效果时，用 `reference/sample_search_result.md` 与 `reference/sample_trace_report.html` 展示检索结果和溯源报告效果（两文件均为示例数据，仅供展示，不得作为交付物）。

## 接口地址

- 可信搜索接口：`https://open.dknowc.cn/dependable/search`
- 深度搜索接口：`https://open.dknowc.cn/api/services/deep-query/v3`（非流式，请求体字段 `query`，`areas` 支持多地域）
- MaaS 平台登录页：`https://platform.dknowc.cn/auth/#/login`

## 工作区与产物约定

本 Skill 的所有中间产物与交付物统一落在 Skill 目录下的 `official-docs/` 工作区，不再向 `/tmp` 或顶层 `outputs/` 写文件：

- `official-docs/search-results/`：查询/搜索/深度搜索结果 JSON 与答案文件。
- `official-docs/output/`：可点击溯源 HTML（图表并入其中）与干净 Markdown 等最终交付物。

查询脚本配合 `--json-only --output <文件名>` 原生落盘到 `search-results/`；渲染脚本自动从 `search-results/` 读取、向 `output/` 写入。

## 常用测试

```bash
python3 -m py_compile scripts/api_key.py scripts/initialize.py scripts/trusted_search.py scripts/deep_query.py scripts/mcp_convert.py scripts/merge_search_results.py scripts/chart_embed.py scripts/render_trace_html.py scripts/deliver_outputs.py scripts/check_release.py
node --check scripts/register_key.mjs
python3 <skillDir>/scripts/check_release.py
```

请求参数检查：

```bash
python3 <skillDir>/scripts/trusted_search.py "公积金租房提取政策原文" --show-payload --dry-run
python3 <skillDir>/scripts/deep_query.py "重庆智能化改造补贴和税惠综合判断" --show-payload --dry-run
```

公开包不得包含 `_meta.json`、`CHANGE_log.md`、`config.ini`、`config.ini.example`、真实 API Key、本地生成的 HTML/SVG 输出或缓存文件；`official-docs/` 工作区内只允许保留 `.gitkeep` 占位。
