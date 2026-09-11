# 深知可信咨询（dsh 版）

这是深知可信咨询的 dsh 分发版本，通过深知可信工作台 MCP 转接（`mcp__dknowc__credible_chat`）。功能逻辑与 full 版对齐：调用深知可信统一问答接口回答咨询问题，输出带真实来源角标的答案，并默认生成本轮本地可信核验报告 HTML。不内置深知可信统一接口 API Key；首次调用时必须先确认环境变量 `DKNOWC_API_KEY` 已配置（dsh 主进程环境变量，供 MCP Bearer 认证）。未配置时按 SKILL.md 开通引导规则处理（引导前禁示、固定话术、可退路）；注册成功后 Key 自动持久化到 `~/.zshrc`，建议重启 dsh 或新建会话后走 MCP 转接。

## 能力范围

- 可信咨询导办：回答政策法规、政务办事、税务社保、公积金、企业补贴、证照资质、行业标准、公共服务和合规义务问题。
- 统一问答：经 MCP 工具 `mcp__dknowc__credible_chat` 调用 `credibleChat` 能力，不调用可信搜索、深度搜索或政策可视化流程。
- 带角标答案：关键事实、条件、金额、比例、办理路径和风险判断必须带 `[数字]` 来源角标，答案末尾附来源清单（使用渲染脚本输出的重编号答案与现成清单）。
- 默认可信核验报告与干净 Markdown：每轮调用统一问答后，默认用 `scripts/render_trace_html.py` 生成本轮可信核验报告 HTML（首屏核验报告单：依据溯源/引用对应/材料新旧/交付前检查；一篇材料一张卡、原文原段标注、标题链、高可信徽标、未引用素材分组、移动端对照弹层）和移除角标的同名 `.clean.md`。
- 会话隔离产物目录：产物落 `<工作区>/dknowc-output/<会话ID前8位>/official-docs/`，同一工作区多会话互不混杂；dsh 以工作区为文件视图，产物即写即见。

## 首次启动初始化

只要调用本 Skill，Agent 必须先运行：

```bash
python3 scripts/initialize.py
```

dsh 场景下脚本检查插件经 shell-env 注入的 `DSH_DKNOWC_API_KEY`（来源为 dsh 主进程环境变量 `DKNOWC_API_KEY`）。只有返回 `ready=true`、`api_key_configured=true` 后，才继续处理原任务。初始化未通过时，只允许引导用户完成 Key 获取或环境变量配置（或用临时 Key 经 `scripts/mcp_direct.py` 直调 MCP 完成当前任务），不得先输出答案、草稿、大纲、材料清单或分析结论。

## MaaS 注册与环境变量配置

当前版本统一通过环境变量 `DKNOWC_API_KEY` 注入 Key。如当前环境变量未配置，按 SKILL.md 开通引导规则处理，引导素材与话术范例见 `reference/consult_intro.md`，效果示例见 `reference/sample_consult_answer.md` 与 `reference/sample_trace_report.html`：

- 可运行 `scripts/register_key.mjs` 发送验证码并注册/查回 Key（dsh 专属渠道码）；各分支输出 `user_message` 固定话术（原样转述），手机号全程脱敏。
- `register_key.mjs` 注册成功后自动把 Key 写入 `~/.zshrc` 标记块（`--no-zshrc` 跳过，回执 `envWriteSucceeded`）。
- 当前任务拿到 Key 后经 `scripts/mcp_direct.py` 直调 MCP 完成任务（会话的 MCP Bearer 认证已冻结；脚本自动从环境变量或 `~/.zshrc` 解析 Key）。
- Key 已自动持久化到 `~/.zshrc`；建议重启 dsh 或新建会话，之后自动走 MCP 转接。
- MaaS 管理平台登录页：`https://platform.dknowc.cn/auth/#/login`

## 接口地址

- 深知可信工作台 MCP：`https://mcp.dknowc.cn/s6/mcp/`（本 skill 所有接口能力的转接层）
- MaaS 短信验证码：`https://platform.dknowc.cn/auth/home/userAuto/sendMessage`
- MaaS 注册 / 查回 Key：`https://platform.dknowc.cn/auth/home/userAuto/register`
- 可选新建 Key：`https://open.dknowc.cn/open-api/maas/api-key/create`
- MaaS 管理平台：`https://platform.dknowc.cn/`

## 工作区约定

产物按 dsh 会话隔离，落 `<工作区>/dknowc-output/<会话ID前8位>/official-docs/`（`DKNWOC_WS_ROOT` 显式优先，非 dsh 环境回退 `dknowc-output/_default/`）：

- `official-docs/search-results/`：中间产物，MCP 原始返回 JSON、规范化 JSON、答案文件。
- `official-docs/output/`：交付物，可信核验报告 HTML 与干净 Markdown（`render_trace_html.py` 默认输出位置）。

不向 `/tmp` 写中间文件，不使用 `outputs/` 目录，不写入 skill 安装目录。

## 常用测试

```bash
python3 -m py_compile scripts/initialize.py scripts/api_key.py scripts/gov_chat.py scripts/render_trace_html.py scripts/adapt_mcp_result.py scripts/mcp_direct.py
node --check scripts/register_key.mjs
```

请求参数检查（离线兜底脚本）：

```bash
DKNOWC_API_KEY=dry-run-key python3 scripts/gov_chat.py "社保迁移怎么办理？" --show-payload --dry-run
```

公开包不得包含 `_meta.json`、`CHANGE_log.md`、`config.ini`、`config.ini.example`、`register.mjs`、真实 API Key、本地生成的 HTML 输出或缓存文件。
