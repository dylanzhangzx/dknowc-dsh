# 深知可信咨询（dsh 版）

这是深知可信咨询的 dsh 分发版本，通过深知可信工作台 MCP 转接（mcp__dknowc__credible_chat）。功能逻辑与 full 版 1.0.1 对齐：调用深知可信统一问答接口回答咨询问题，输出带真实来源角标的答案，并默认生成本轮本地可信溯源 HTML。Public 版不内置深知可信统一接口 API Key；首次调用时必须先确认环境变量 `DKNOWC_API_KEY` 已配置。未配置时，应说明本 Skill 需要通过 `DKNOWC_API_KEY` 获取深知可信内容，并引导用户注册或登录深知可信智能 MaaS 账号获取 Key；持久化环境变量是独立步骤，必须在用户明确同意后再处理。

## 能力范围

- 可信咨询导办：回答政策法规、政务办事、税务社保、公积金、企业补贴、证照资质、行业标准、公共服务和合规义务问题。
- 统一问答：固定调用 `scripts/gov_chat.py` 的 `credibleChat` 能力，不调用可信搜索、深度搜索或政策可视化流程。
- 带角标答案：关键事实、条件、金额、比例、办理路径和风险判断必须带 `[数字]` 来源角标，答案末尾附来源清单。
- 默认溯源 HTML 与干净 Markdown：每轮调用统一问答后，默认用 `scripts/render_trace_html.py` 生成本轮可点击溯源 HTML 和移除角标的同名 `.clean.md`。

## 首次启动初始化

只要调用本 Skill，Agent 必须先运行：

```bash
python3 scripts/initialize.py
```

只有返回 `ready=true`、`api_key_configured=true`、`api_key_source=environment`，且未返回 `search_ready=false` 后，才继续处理原任务。初始化未通过时，只允许引导用户完成 MaaS Key 获取或环境变量配置，不得先输出答案、草稿、大纲、材料清单或分析结论。

## MaaS 注册与环境变量配置

当前版本统一通过环境变量 `DKNOWC_API_KEY` 注入 Key，不再扫描或复用其他深知系列 Skill 的本地 `config.ini`，业务调用脚本也不再读取本地配置文件或传入 `szUserId`。如当前环境变量未配置：

- 可运行 `scripts/register_key.mjs` 发送验证码并注册/查回 Key。
- `register_key.mjs` 只返回 Key，不持久化保存 Key。
- 当前任务拿到 Key 后可临时注入 `DKNOWC_API_KEY` 并继续执行。
- 任务完成后，Agent 询问用户是否需要持久化 `DKNOWC_API_KEY`；用户同意后再单独处理。
- MaaS 管理平台地址：`https://platform.dknowc.cn/`

## 接口地址

- 可信统一接口：`https://open.dknowc.cn/chat/trusted/unification`
- MaaS 短信验证码：`https://platform.dknowc.cn/auth/home/userAuto/sendMessage`
- MaaS 注册 / 查回 Key：`https://platform.dknowc.cn/auth/home/userAuto/register`
- 可选新建 Key：`https://open.dknowc.cn/open-api/maas/api-key/create`
- MaaS 管理平台：`https://platform.dknowc.cn/`

## 工作区约定

本 Skill 自持 `official-docs/` 工作区，命名与深知公文写作 Skill 一致：

- `official-docs/search-results/`：中间产物，接口 JSON、答案文件（`gov_chat.py --json-only --output ...` 落盘位置）。
- `official-docs/output/`：交付物，HTML 溯源报告（`render_trace_html.py` 默认输出位置）。

不向 `/tmp` 写中间文件，不使用 `outputs/` 目录。

## 常用测试

```bash
python3 -m py_compile scripts/initialize.py scripts/gov_chat.py scripts/render_trace_html.py scripts/check_release.py
node --check scripts/register_key.mjs
python3 scripts/check_release.py
```

请求参数检查：

```bash
DKNOWC_API_KEY=dry-run-key python3 scripts/gov_chat.py "社保迁移怎么办理？" --show-payload --dry-run
```

公开包不得包含 `_meta.json`、`CHANGE_log.md`、`config.ini`、`config.ini.example`、`register.mjs`、真实 API Key、本地生成的 HTML 输出或缓存文件。
