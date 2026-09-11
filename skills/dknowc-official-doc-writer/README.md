# 深知公文写作（dsh 版）

这是深知公文写作的 SkillHub 分发版本。功能逻辑与主干完整版保持一致，但不内置深知搜索 API Key。API Key 只对需要深知搜索的任务（查政策依据、数据支撑、案例参考、最新政策情况）是前置条件；不涉及搜索的简单通知、改写润色、只生成 Word 等任务可直接使用，不要求配置 Key。需要搜索时，由 Agent 通过 MaaS 注册接口完成手机号注册、验证码确认和 API Key 获取，并写入本机 `~/.zshrc` 中的 `DKNOWC_API_KEY`。

## 能力范围

- 深知可信搜索：通过 `scripts/dkag_search.py` 调用搜索接口获取政策、数据和案例素材。
- 公文范文大纲：通过 `scripts/outline_reference.py` 在搜索前获取范文参考大纲和搜索建议。
- 公文写作流程：由 `SKILL.md` 进行任务路由，按任务复杂度选择直接生成、追问、搜索、审查或严格流水线。
- 搜索策略：`reference/search_policy.md` 保留深知搜索逻辑、素材四分类和来源限制。
- 任务路由：`reference/task_router.md` 定义简单任务、常规任务、复杂任务和高风险任务的处理方式。
- 质量审查：`reference/review_checklist.md` 定义公文内容、可信溯源、文种专项和 Word 输出检查项。
- Word 排版：通过 `scripts/format_document.py` 生成普通格式 `.docx`，支持标准 Markdown 表格和宽表横向页面。
- 溯源核验报告：执行过搜索时，通过 `scripts/source_note_html.py` 和 `scripts/render_trace_html.py` 生成独立 HTML 溯源核验报告（含原文标题链、原文原段标注、高可信标识、未引用召回与检索筛选）。
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

调用本 Skill 后，Agent 应先运行 `python3 scripts/initialize.py` 检查 Python、`python-docx`、`requests` 等基础运行环境。只要 `ready=true` 即可开始写作。

API Key 按需配置：

- 不涉及搜索的任务（简单通知、改写润色、只生成 Word 等）：不要求配置 API Key，可直接使用。
- 需要搜索的任务（查政策依据、数据支撑、案例参考、最新政策情况）：此时若初始化结果显示 `api_key_configured=false` 或 `search_ready=false`，先按 `reference/onboarding_scripts.md` 固定话术引导用户完成注册获取 Key。注册成功后无需重启：脚本在进程环境变量缺失时自动从 ~/.zshrc 读取 Key。

## 需要搜索时，注册并配置深知搜索 API Key

只有当前任务需要深知搜索（政策依据、数据支撑、案例参考，或查最新政策、最新情况）时才需要配置 API Key。配置 API Key 后，深知公文写作可调用深知可信搜索，从权威文件库中检索政策依据、权威数据和典型案例，检索结果附原文来源，便于写作时引用和核验。不涉及搜索的写作任务无需配置 Key，可直接使用。引导与注册各环节的固定话术（含报错处理）见 `reference/onboarding_scripts.md`；向用户介绍搜索能力可参考 `reference/search_intro.md`，用户犹豫时可用 `reference/sample_search_result.md` 与 `reference/sample_trace_report.html` 展示效果（示例数据，仅供展示）。

SkillHub 版默认使用：

- 接入点 `type=6`，即深知可信搜索。
- 渠道码 `7F9FBE52-849B-43FE-BB88-220E2A415FD8`。
- 统一环境变量 `DKNOWC_API_KEY` 保存 API Key，由公文范文大纲接口和深知可信搜索接口共用。

当任务需要搜索且当前环境变量 `DKNOWC_API_KEY` 未配置时，进入 MaaS 注册。第 1 步，发送短信验证码：

```bash
node scripts/register.mjs send --phone 13812345678
```

返回 `status=true` 后，转述脚本输出的 `user_message`（含脱敏手机号与"最新一条"提示），暂停并请用户提供收到的 6 位验证码。

第 2 步，注册并获取 API Key：

```bash
node scripts/register.mjs register --phone 13812345678 --vcode 123456 --organ 个人 --name 用户
```

注册第二步会固定携带 `source="agent"`，并继续使用 SkillHub 渠道码。手机号已注册时，默认查回该账号已有可用 API Key；手机号未注册时，按 MaaS 注册流程创建账号并获取 API Key。成功后，脚本会把 API Key 写入 `~/.zshrc` 中的 `DKNOWC_API_KEY` 配置块，并返回 `user_message`（含 300 次免费额度与实名认证赠金告知，Agent 必须转述）。返回的完整 Key 仅供 Agent 当前任务临时注入环境变量使用，不得向用户展示完整 API Key，不得要求用户手动复制 Key。

默认不重新生成 API Key。只有用户明确要求重新生成或新建 Key 时，才追加 `--new-key`：

```bash
node scripts/register.mjs register --phone 13812345678 --vcode 123456 --organ 个人 --name 用户 --new-key
```

如自动注册链路失败，可按脚本 `user_message` 降级引导用户访问 MaaS 平台：

```text
https://platform.dknowc.cn/auth/#/login
```

搜索接口固定为：

```text
https://open.dknowc.cn/dependable/search/
```

API Key 只能通过环境变量 `DKNOWC_API_KEY` 引入，不得硬编码，不得写入公开包。注册脚本可将 Key 写入本机 `~/.zshrc`；脚本读取顺序为进程环境变量优先、缺失时自动解析 `~/.zshrc`，无需重启宿主。

## 版本说明

当前 dsh 版基于母版 `3.6.1`：溯源核验报告 0907 会议八项改版（身份章、五项指标拟人化更名、原文原段身份标注与折叠、标题链、高可信徽标、未引用召回分组、检索筛选胶囊、移动端对照弹层、一篇一卡数据层修复）；注册漏斗话术固化（onboarding_scripts.md 固定话术库、脚本 user_message 原样转述、注册成功自动持久化 `~/.zshrc`）；外部公文专家格式反馈修复（落款双段定位、版记回退、联系人电话按行文方向、字体表述规范）。dsh 侧：门禁三级 Key 解析（DSH_DKNOWC_API_KEY/环境变量/zshrc 兜底）、mcp_direct 直调自动解析 zshrc、范式大纲与全部脚本重打会话隔离补丁。

## 常用测试

语法检查：

```bash
python3 -m py_compile scripts/outline_reference.py scripts/dkag_search.py scripts/merge_search_results.py scripts/format_document.py scripts/template_generator.py scripts/initialize.py scripts/source_note_html.py scripts/render_trace_html.py scripts/review_document.py
node --check scripts/register.mjs
```

范文大纲生成：

```bash
python3 scripts/outline_reference.py "请写一份关于基层治理工作的调研报告，重点包括背景、做法、问题和建议。"
```

普通 Word 生成：

```bash
python3 scripts/format_document.py official-docs/input/dknowc-test.md --output dknowc-test.docx
```

红头 Word 生成：

```bash
python3 scripts/template_generator.py 通知 --input dknowc-test.docx --org "XX单位" --doc-number "XX〔2026〕1号" --output dknowc-test-red.docx
```

搜索结果保存：

```bash
python3 scripts/dkag_search.py "人才服务政策" --area 某省 --purpose "核查当地人才服务政策依据" --clean --output result_gd.json
```

多次搜索合并：

```bash
python3 scripts/merge_search_results.py result_gd.json result_bj.json --output merged.json
```

溯源核验报告 HTML：

```bash
python3 scripts/source_note_html.py official-docs/input/trace-report.json --output trace-report.html
```
