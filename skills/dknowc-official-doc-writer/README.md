# 深知公文写作（SkillHub Public 版）

这是深知公文写作的 SkillHub 分发版本。功能逻辑与主干完整版保持一致，但不内置深知搜索 API Key。API Key 只对需要深知搜索的任务（查政策依据、数据支撑、案例参考、最新政策情况）是前置条件；不涉及搜索的简单通知、改写润色、只生成 Word 等任务可直接使用，不要求配置 Key。需要搜索时，由 Agent 通过 MaaS 注册接口完成手机号注册、验证码确认和 API Key 获取，并写入本机 Key 专用配置文件（`~/.config/dknowc/api_key`）。

## 能力范围

- 深知可信搜索：通过 `scripts/dkag_search.py` 调用搜索接口获取政策、数据和案例素材。
- 公文范文大纲：通过 `scripts/outline_reference.py` 在搜索前获取范文参考大纲和搜索建议。
- 公文写作流程：由 `SKILL.md` 进行任务路由，按任务复杂度选择直接生成、追问、搜索、审查或严格流水线。
- 搜索策略：`reference/search_policy.md` 保留深知搜索逻辑、素材四分类和来源限制。
- 任务路由：`reference/task_router.md` 定义简单任务、常规任务、复杂任务和高风险任务的处理方式。
- 质量审查：`reference/review_checklist.md` 定义公文内容、可信溯源、文种专项和 Word 输出检查项。
- Word 排版：通过 `scripts/format_document.py` 生成普通格式 `.docx`，支持标准 Markdown 表格和宽表横向页面。
- 产出物 HTML：执行过搜索时，通过 `scripts/source_note_html.py` 和 `scripts/render_trace_html.py` 生成单文件产出物 HTML（顶部切换 **正文（去索引） / 溯源核验报告 / 知识专库** 三页）：正文页为干净正式正文（与 Word 正文一致）；溯源核验报告页含 **AI 自验收**（过程回顾条）、核验单与带角标的正文（角标为可点击引文胶囊）；知识专库页按检索分组展示来源材料；原文链接原样给出、附存档快照兜底。顶栏「导出」可导出正文 Markdown（.md）或 PDF（正文 / 溯源核验报告）。文件名按用户需求（正文标题）生成，形如 `XXX.html`。
- 已有 Word 审查：通过 `scripts/review_document.py` 只读提取已有 `.docx` 的格式信息和待核验事实表述。
- 红头文件：通过 `scripts/template_generator.py` 代码化生成红头和表尾，不依赖 `templates/` 中的 Word 模板。
- 个人素材库与写作偏好：`scripts/local_memory.py` 管理本机私有素材库与偏好（不随公开包分发）。
- PDF：当前版本不支持自动生成 PDF；用户明确要求 PDF 时，交付 `.docx` 并建议用户使用本机 Word/WPS 另存或导出为 PDF。

## 依赖

```bash
pip3 install python-docx requests
```

`Python`、`python-docx`、`requests` 是运行本 Skill 的基础前置条件。初始化检查如显示 `ready=false`，应先完成缺失项处理，并重新检查通过后再继续执行搜索、写作、Word、红头或溯源核验报告 HTML 生成。有效 API Key 只对需要深知搜索的任务是前置条件；不涉及搜索的写作任务无需配置 Key。

标准公文字体不随 Skill 分发，字体也不作为初始化阻断项。Word 文档会写入公文常用字体名称；如打开端缺少对应字体，Word/WPS 可能自动替换，需以本机打开后的显示为准。

还需要 Node.js 18+ 用于调用 MaaS 注册接口：

```bash
node --version
```

## 首次启动初始化

调用本 Skill 后，Agent 应先运行 `python3 <skillDir>/scripts/initialize.py` 检查 Python、`python-docx`、`requests` 等基础运行环境。只要 `ready=true` 即可开始写作。

API Key 按需配置：

- 不涉及搜索的任务（简单通知、改写润色、只生成 Word 等）：不要求配置 API Key，可直接使用。
- 需要搜索的任务（查政策依据、数据支撑、案例参考、最新政策情况）：若初始化结果显示 `api_key_configured=false` 或 `search_ready=false`，按 `reference/onboarding_scripts.md` 固定话术引导用户完成注册获取 Key。注册成功后无需重启：脚本在进程环境变量缺失时自动从专用配置文件（`~/.config/dknowc/api_key`）读取 Key。

## 需要搜索时，注册并配置深知搜索 API Key

只有当前任务需要深知搜索（政策依据、数据支撑、案例参考，或查最新政策、最新情况）时，才需要配置 API Key（3.7.5 起统一走脚本通道，不再走 MCP）。配置 API Key 后，深知公文写作可调用深知可信搜索，从权威文件库中检索政策依据、权威数据和典型案例，检索结果附原文来源，便于写作时引用和核验。不涉及搜索的写作任务无需配置 Key，可直接使用。引导与注册各环节的固定话术（含报错处理）见 `reference/onboarding_scripts.md`；向用户介绍搜索能力可参考 `reference/search_intro.md`，用户犹豫时可用 `reference/sample_search_result.md` 与 `reference/sample_trace_report.html` 展示效果（示例数据，仅供展示）。

SkillHub 版默认使用：

- 接入点 `type=6`，即深知可信搜索。
- 渠道码 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`（dsh 专属）。
- 统一环境变量 `DKNOWC_API_KEY` 保存 API Key，由公文范文大纲接口和深知可信搜索接口共用。

当任务需要搜索且当前环境变量 `DKNOWC_API_KEY` 未配置时，进入 MaaS 注册。第 1 步，发送短信验证码（只调用一次、不自动重试）：

```bash
node <skillDir>/scripts/register.mjs send --phone 13812345678
```

发码有两个分支，都必须支持（2026-10-09 注册链路改造，user-auth maas-1.1.6）：

- **退出 0（`status=true`，短信直发）**：转述脚本输出的 `user_message`（含脱敏手机号与"最新一条"提示），暂停并请用户提供收到的 6 位验证码。
- **退出 2（`code="CAPTCHA_REQUIRED"`，短信尚未发送）**：转述 `user_message` 并原样给出脚本返回、经安全校验的验证链接，暂停等待用户在页面完成验证并回复短信验证码。用户在页面完成验证后不得再调 send；只说"验证好了"时仅追问短信码。链接一次性、约 10 分钟有效。（退出 2 也可能是参数错误，需结合 JSON 的 `code` 字段判断。）
- **退出 1（错误）**：按 `user_message` 处理；限频、验证链接过期、供应商失败、发送结果未确认等各有停点，不循环重试。

第 2 步，注册并获取 API Key：

```bash
node <skillDir>/scripts/register.mjs register --phone 13812345678 --vcode 123456 --organ 个人 --name 用户
```

注册第二步会固定携带 `source="agent"`（注册接口的合同标记，服务端按它放行老用户直接返 Key），并继续使用 SkillHub 渠道码；调用来源统计走 `X-Dknowc-Attribution` 请求头（`agentSource=` 为本 Skill 标识），两者互不影响。手机号已注册时，默认查回该账号已有可用 API Key；手机号未注册时，按 MaaS 注册流程创建账号并获取 API Key；账号已建但密钥仍在准备时返回 `pending=true`（非错误，稍后同参数重试一次）。成功后，脚本会把 API Key 写入本机专用配置文件（`~/.config/dknowc/api_key`），并返回 `user_message`（含注册赠送 10 万积分与实名认证再送 10 万积分告知，Agent 必须转述）。返回的完整 Key 仅供 Agent 当前任务临时注入环境变量使用，不得向用户展示完整 API Key，不得要求用户手动复制 Key。

默认不重新生成 API Key。只有用户明确要求重新生成或新建 Key 时，才追加 `--new-key`：

```bash
node <skillDir>/scripts/register.mjs register --phone 13812345678 --vcode 123456 --organ 个人 --name 用户 --new-key
```

如自动注册链路失败，可按脚本 `user_message` 降级引导用户访问 MaaS 平台：

```text
https://platform.dknowc.cn/auth/#/login
```

搜索接口固定为：

```text
https://open.dknowc.cn/dependable/search/
```

API Key 只能通过环境变量 `DKNOWC_API_KEY` 注入或本机专用配置文件（`~/.config/dknowc/api_key`）持久化，不得硬编码，不得写入公开包。脚本读取顺序为进程环境变量优先、缺失时自动读取配置文件，历史 `~/.zshrc` 中的 Key 块仅作迁移期兜底，无需重启宿主。

## 交付形态

交付形态由两个独立开关决定（详见 `reference/task_router.md`）：

- **是否命中文公文范式** → 决定要不要 Word：命中 15 种法定公文（决议、决定、命令、公报、公告、通告、意见、通知、通报、报告、请示、批复、议案、函、纪要，含复函与提醒函）时生成 `.docx`；用户明确要求 Word/红头时也生成 Word。
- **是否执行过深知搜索** → 决定要不要产出物 HTML：只要用过深知可信搜索或深度搜索，就生成单文件产出物 HTML（正文 / 溯源核验报告 / 知识专库 三页）。

两者可同时成立。非公文且执行过搜索时，交付产出物 HTML 并询问用户是否需要另出 Word。

## 版本说明

当前 dsh 版基于 SkillHub 母版 `3.8.1`（版本号 `3.8.1-dsh`）。

检索通道：统一走脚本通道（`deep_query.py` / `dkag_search.py` / `outline_reference.py`，需 API Key）。3.7.5 起不再走 MCP「深知可信工作台」通道——MCP 侧大结果落盘方案改造完成后另行加回。

## 常用测试

语法检查：

```bash
python3 -m py_compile scripts/outline_reference.py scripts/dkag_search.py scripts/merge_search_results.py scripts/format_document.py scripts/template_generator.py scripts/initialize.py scripts/source_note_html.py scripts/render_trace_html.py scripts/review_document.py
node --check scripts/register.mjs
```

范文大纲生成：

```bash
python3 <skillDir>/scripts/outline_reference.py "请写一份关于基层治理工作的调研报告，重点包括背景、做法、问题和建议。"
```

普通 Word 生成：

```bash
python3 <skillDir>/scripts/format_document.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/dknowc-test.md --output dknowc-test.docx
```

红头 Word 生成：

```bash
python3 <skillDir>/scripts/template_generator.py 通知 --input dknowc-test.docx --org "XX单位" --doc-number "XX〔2026〕1号" --output dknowc-test-red.docx
```

搜索结果保存：

```bash
python3 <skillDir>/scripts/dkag_search.py "人才服务政策" --area 某省 --purpose "核查当地人才服务政策依据" --clean --output result_gd.json
```

多次搜索合并：

```bash
python3 <skillDir>/scripts/merge_search_results.py result_gd.json result_bj.json --output merged.json
```

溯源核验报告 HTML：

```bash
python3 <skillDir>/scripts/source_note_html.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/trace-report.json --output trace-report.html
```
