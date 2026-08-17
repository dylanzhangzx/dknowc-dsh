---
name: dknowc-official-doc-writer
slug: dknowc-official-doc-writer
display_name: "深知公文写作"
display_name_en: "dknowc official doc writer"
description: "当用户要求写一份正式文稿、成稿或报告——如'帮我写一份××分析报告'、'写一份××调研报告'、'写一份××政策分析报告'、'写一份××工作报告/总结/方案/汇报材料'，或要求起草通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、管理办法、发言稿、讲话稿、经验材料等正式文种时，使用深知公文写作。本 skill 面向单位办公室、综合岗、文秘、材料岗和企事业单位用户，把零散想法、会议记录、工作素材、调研资料、检索材料或初稿整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿，正式交付支持生成 Word 文档（用户明确需要时可生成红头文件）。涉及政策依据、数据支撑、标准规范或案例参考时，本 skill 内部可通过深知可信搜索（MCP）获取素材并单独生成可信溯源报告。注意区分：若用户只是要求检索/查证政策原文、收集多地域素材或做深度搜索核验，而不是把素材写成成稿，应改用深知可信搜索 skill（dknowc-trusted-search）。"
description_zh: "深知公文写作，是由北京彩智科技有限公司旗下“深知可信智能”提供的正式材料写作助手，准确、规范地完成企事业单位与政府机关等场景下的文档编写需求，所有依据或参考材料，都全程可溯源到权威部门发布的规范性文件。本技能用于公文写作、正式文书起草、汇报材料整理、讲话稿撰写、工作总结和方案报告生成，帮助用户把零散想法、会议记录、工作素材、调研资料或初稿整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿。依托深知可信搜索（经 MCP 转接），获取准确有效的法规政策依据、行业信息与数据、标准规范和案例参考，并单独生成所有材料的溯源说明与原文清单。正式交付时支持生成 Word 文档；并可按用户明确要求自动生成红头文件。"
description_en: "dknowc official doc writer is a formal-document writing Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It helps users draft, rewrite, polish, review and generate structured workplace documents, including official documents, formal letters, reports, meeting minutes, summaries, plans, speeches, research reports and other business materials. When evidence, data, standards or reference cases are needed, it retrieves traceable materials from authoritative sources via the dknowc trusted workbench MCP and generates a separate source-reference report. Final outputs can be generated as Word documents, and red-head document formatting is supported when explicitly requested by the user."
category: "通用办公"
version: "3.4.1-dsh"
author: "彩智科技"
permissions:
  network:
    - "https://mcp.dknowc.cn/"
  local_read:
    - "本 Skill 的 reference、config、official-docs 等规则、标准、配置和参考资料文件"
  local_write:
    - "本地初始化状态文件"
    - "用户明确授权保存的写作偏好"
    - "生成的 Word 文档"
    - "可信溯源报告与搜索结果中间文件"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知公文写作

深知公文写作由北京彩智科技有限公司旗下“深知可信智能”提供，是面向正式材料写作场景的组合型 Agent Skill。它不是固定从头到尾执行的演示脚本，而是根据任务选择最小必要流程，帮助用户完成公文写作、正式文书起草、汇报材料整理、讲话稿撰写、总结方案生成、素材检索、可信溯源报告和 Word 交付。

## 权限说明

本 Skill（dsh 版）的深知搜索接口调用走深知可信工作台 MCP 转接层（`mcp__dknowc__trusted_search`，Bearer 认证使用环境变量 `DKNOWC_API_KEY`）；公文范文大纲能力保留原脚本 `scripts/outline_reference.py` 直连。运行过程中会读取本 Skill 的规则、标准、配置和参考资料文件，并在本地写入初始化状态文件、用户授权保存的写作偏好、生成的 Word 文档、可信溯源报告和搜索结果中间文件。Skill 包内不包含真实 API Key，API Key 必须通过环境变量 `DKNOWC_API_KEY` 注入，不得硬编码，不得写入公开包，不得在对话中展示完整内容。

## 设计模式

本 Skill 组合使用五种模式：

- Tool Wrapper：封装公文范文大纲、深知搜索、普通 Word 排版、红头文件生成和可信溯源报告 HTML 生成。
- Generator：根据文种标准、用户材料和素材指引生成公文正文。
- Reviewer：按审查清单检查格式、逻辑、素材来源和公文风险。
- Inversion：复杂任务或关键信息缺失时，先向用户追问。
- Pipeline：仅在政策依据型、长篇复杂材料、红头交付等场景执行带检查点的严格流程。

## 启动初始化

本 dsh 版不内置深知搜索 API Key。API Key 必须通过环境变量 `DKNOWC_API_KEY` 注入（供 MCP Bearer 认证）。本 Skill 被调用后，先运行一次初始化检查：

```bash
python3 <skillDir>/scripts/initialize.py
```

初始化用于检查 Python、`python-docx`、`requests` 等基础运行环境，不要求用户提供单位或个人信息，也不上传检测结果。初始化不是 API Key 硬性门禁：只有当当前任务确实需要调用深知搜索时，API Key 才是前置条件。

**Key 检查机制（dsh）**：dsh 的安全机制会清理名字含 KEY 的隐式环境变量，脚本子进程读不到原始的 `DKNOWC_API_KEY`。本 bundle 插件会把 dsh 主进程的 `DKNOWC_API_KEY` 值经 shell-env 显式通道注入为 `DSH_DKNOWC_API_KEY`，脚本检查它来判断用户是否已配置 Key。因此：
- 用户在启动 dsh 的环境变量中配置 `DKNOWC_API_KEY` 即可（如 `~/.zshrc`），无需设置 `DSH_DKNOWC_API_KEY`；
- 配置生效后，`DSH_DKNOWC_API_KEY` 非空，搜索就绪门禁通过；**一次配置，之后免注册**；
- 若用户后续修改/替换 Key，只需更新 `DKNOWC_API_KEY` 并重启 dsh 或新建会话。

### 不需要搜索的任务

简单通知、内部事务通知、改写、润色、审查、基于用户材料写作、只生成 Word 或红头文件等不涉及政策、数据、案例检索的任务，只要 `python3`、`python_docx`、`requests` 就绪即可继续写作，不要求配置 API Key，也不必引导用户注册 MaaS。初始化结果显示 `api_key_configured=false` 或 `search_ready=false` 时，不阻断这类任务，直接按原任务流程继续。

### 需要搜索的任务

只有任务确实需要深知搜索（需要政策依据、数据支撑、案例参考，或用户明确要求查最新政策、最新情况、权威数据）时，API Key 才是前置条件。此时如果初始化结果中 `api_key_configured=false`、`search_ready=false`，或 `search_blocking_issues` 包含 `api_key_missing`，先向用户简要说明开通搜索的用途，再引导完成注册获取 Key；拿到 Key 后用**临时直调 MCP 完成当前任务**（见下），任务完成后再建议持久化。

向用户说明时必须做到：

- 结合当前任务和用户语气自然表达，禁止逐字照抄固定模板，禁止说明书式复述流程。
- 不得向用户暴露内部术语和流程名，如"MaaS""API Key""环境变量 DKNOWC_API_KEY""验证码注册流程""范文大纲 → 搜索方案 → 正式写作"等；用户侧只需表达为"开通搜索功能"。
- 解释要点：① 为什么需要：这份材料需要查最新的政策依据、权威数据和案例，开通搜索后可直接检索权威文件库中的素材，素材来源可溯源，方便核验；② 怎么配：如需使用搜索功能，可提供手机号完成验证，注册由 Agent 代为处理，无需用户填写单位信息。
- 如需向用户介绍深知搜索的能力说明，参考 `reference/search_intro.md` 中的说明素材，用自己的话自然组织，不得整段照抄该文件。

语气示范（不要照抄，模仿这种自然口吻组织语言）：

```text
这份调研报告需要查最新的政策依据、权威数据和案例。深知搜索可检索权威文件库中的素材，检索结果都带原文来源，方便你核验，材料写出来更有依据。

如需使用搜索功能，提供手机号完成验证即可，注册由我代为处理，你不需要填写单位信息。
```

引导配置时，用户提供手机号和收到的验证码即可。注册和获取 Key 由 Agent 处理；获取到的 Key 仅供**当前任务临时使用**，本轮用 `DKNOWC_API_KEY=<临时Key> python3 <skillDir>/scripts/mcp_direct.py trusted_search '<JSON参数>' --output official-docs/search-results/xxx_mcp_raw.json` 直调 MCP 完成搜索（bash 前缀赋值绕过 dsh 的环境清理），随后走 `adapt_mcp_result.py` 规范化 → `source_note_html.py` / `render_trace_html.py` 生成溯源报告。任务完成后再询问用户是否把 `DKNOWC_API_KEY` 持久化到本机环境变量（如 `~/.zshrc`），只有用户明确同意后才写入；写入后建议用户重启 dsh 或新开会话。

MaaS 初始化按两步流程执行：

```bash
node <skillDir>/scripts/register.mjs send --phone <手机号>
```

返回 `status=true` 后，暂停并向用户索取收到的 6 位验证码，不得自行编造验证码。

拿到验证码后执行：

```bash
node <skillDir>/scripts/register.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

脚本默认固定 `type=6`（深知可信搜索），自动使用 dsh 渠道码 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`，并固定携带 `source="agent"`。手机号已注册时，脚本默认查回该账号已有可用 API Key；手机号未注册时，按 MaaS 注册流程创建账号并获取 API Key。成功后，脚本返回环境变量名和 API Key，仅供 Agent 当前任务临时注入环境变量使用（dsh 场景下该 Key 供 MCP Bearer 认证）。不得向用户展示完整 API Key，不得要求用户手动复制 API Key。当前任务应使用脚本返回的 Key 重新运行初始化检查；确认通过后继续处理用户原任务。

默认不得重新生成 API Key。只有用户明确要求“重新生成 Key”“新建一个 Key”“不要用旧 Key”等表达时，才在上述注册命令后追加 `--new-key`：

```bash
node <skillDir>/scripts/register.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户 --new-key
```

`--new-key` 会先通过手机号验证码和 `source="agent"` 查回一把已有可用 Key，再调用 MaaS API Key 创建接口生成新 Key，并仅把新 Key 写入 `~/.zshrc` 中的环境变量 `DKNOWC_API_KEY`。如新 Key 创建失败，必须暂停并说明错误，不得把旧 Key 当作新 Key 使用。

如接口失败、短信发送受限、验证码错误、`source` 未被接口接受或用户不希望自动注册，暂停原任务并给出 MaaS 管理平台地址作为降级方案：

```text
https://platform.dknowc.cn/
```

## 参考资料（渐进式读取）

按任务条件只加载命中的参考资料，不一次性读取全部文件。每个文件只在对应阶段读取，未命中条件不预读。

| 文件 | 阶段 | 加载条件 |
| --- | --- | --- |
| `reference/task_router.md` | 任务开始 | 判断任务类型与复杂度，所有任务先读 |
| `reference/fact_discipline.md` | 起草/改稿前 | 所有正式写作任务，约束事实边界 |
| `reference/anti_ai_patterns.md` | 定稿前/审查 | 正式正文语言复核、去 AI 味、审查模式 |
| `scripts/prose_lint.py` | 定稿前 | 检查草稿语言、格式、重复风险（可选） |
| `reference/search_policy.md` | 搜索前 | 需要政策/数据/案例检索时 |
| `reference/search_guide.md` | 执行搜索后 | 生成可信溯源报告 HTML 时 |
| `reference/material_usage_guidance.md` | 执行搜索后 | 召回素材如何进入正文 |
| `reference/output_guide.md` | 生成 Word 前 | 正文 Markdown 格式、Word 交付 |
| `reference/review_checklist.md` | 生成前后 | 按任务风险执行审查时 |
| `reference/search_intro.md` | 引导用户时 | 需要向用户说明搜索功能时 |
| `reference/standards/*.md` | 按文种 | 命中对应文种时读取（见"写作规则"） |

## 工作区约定（dsh）——脚本与产物的路径区分

- **脚本调用一律用 skill 目录的绝对路径**（resourceBase 指引里给出的 "Base directory for this skill: <path>" 就是 skill 目录，以下称 `<skillDir>`）。不要用 `scripts/xxx.py` 这种相对路径调用脚本——bash 命令的相对路径是基于当前工作区（session cwd）解析的，而脚本在 bundle 的 skill 目录里，相对路径会找不到。
- 因此所有脚本调用写成：`python3 <skillDir>/scripts/initialize.py`、`python3 <skillDir>/scripts/outline_reference.py ...`、`python3 <skillDir>/scripts/format_document.py ...`、`node <skillDir>/scripts/register.mjs ...` 等。
- **运行产物（搜索结果 JSON、合并 JSON、大纲 JSON、正文临时文件、Word 文档、溯源报告 HTML）一律写入当前会话工作区**（即 bash 默认的当前工作目录），用相对路径 `official-docs/input/...`、`official-docs/search-results/...`、`official-docs/output/...`、`official-docs/outline-results/...`。脚本已按 `WS_ROOT = 当前工作目录` 解析这些相对路径，产物会落到工作区，不会写进 bundle。
- 交付给用户的 `.docx` / HTML 路径，以脚本实际打印的绝对路径为准。

## MCP 不可用处理（强制）

- 搜索子能力依赖 MCP：如果 `mcp__dknowc__trusted_search` 工具**不存在、调用失败、返回 401/403 鉴权错误或明确报鉴权失败**，说明 `DKNOWC_API_KEY` 未正确配置（dsh 主进程环境变量缺失或无效）。
- **涉及搜索的任务**（需政策依据、数据支撑、案例参考）此时必须暂停搜索，不得编造政策数据、不得改用 Web 搜索/网页抓取、不得绕过 MCP 直连接口；向用户说明需将有效的 `DKNOWC_API_KEY` 配置到启动 dsh 的环境变量（如 `~/.zshrc`）后重启 dsh 或新建会话重试。
- **不涉及搜索的纯写作任务**（简单通知、改写、润色、基于用户材料写作、只生成 Word/红头）不依赖 MCP，不受影响，按原流程继续写作交付。
- 范文大纲能力走原脚本直连（`outline_reference.py`），不受 MCP 影响；但注意其读取的 `DKNOWC_API_KEY` 同样被 dsh 清理，dsh 环境下若无有效 Key 则跳过范文大纲能力，不中断写作。

## 工作原则

- 首次使用时先运行 `python3 <skillDir>/scripts/initialize.py` 检查 Python、依赖和 `DKNOWC_API_KEY` 环境变量配置。初始化不要求用户提供单位或个人信息，也不上传检测结果。
- Python 和 `python-docx`、`requests` 依赖属于基础前置条件：如无法运行 `python3`，或初始化结果显示 `python_docx=false`、`requests=false`，必须暂停执行 Skill 的写作、搜索、Word、红头和可信溯源报告能力。
- API Key 属于按需前置条件：只有当前任务需要深知搜索（政策依据、数据支撑、案例参考、查最新政策情况）时，才要求 `api_key_configured=true`、`search_ready=true`。不需要搜索的简单通知、改写、润色、基于用户材料写作或只生成 Word 的任务，即使 `api_key_configured=false`、`search_ready=false` 也不阻断，直接按原任务流程继续。
- 发现 `python-docx` 或 `requests` 缺失且 `dependency_install_prompt_needed=true` 时，可以先向用户说明影响，并征得用户同意后执行 `python3 -m pip install python-docx requests`；未经用户同意不得自行安装依赖。安装后必须重新运行 `python3 <skillDir>/scripts/initialize.py` 确认 `ready=true` 后再继续。如用户不同意安装依赖，执行 `python3 <skillDir>/scripts/initialize.py --decline-dependency-install` 记录拒绝状态，后续不再反复询问，但仍因缺少必备依赖而暂停相关能力。
- 如缺少 Python 或当前环境无权限安装依赖，应提示用户切换到具备 Python 的 Agent/运行环境，或由用户/平台管理员先完成 Python 与依赖安装。
- 字体不作为 Skill 初始化阻断项，也不主动检测、安装或引导用户安装字体。Word 文档会写入公文常用字体名称；交付时简单提醒用户：如打开端缺少对应字体，Word/WPS 可能自动替换，需以本机打开后的显示为准。
- 仅在用户明确同意保存常用设置时，使用 `--save` 写入本机 `config/user_profile.json`；不得主动索取与当前公文无关的信息。
- 用户未配置发文机关、文号前缀或地域时，仍可生成文档：分别使用 `XX单位`、`XX〔年份〕XX号` 等醒目占位符，地域则根据当前任务询问或保持未指定。交付时提醒用户核对占位符。
- 不得根据示例、历史文档或搜索地域猜测用户所属单位，不得把任何具体客户名称作为默认值。

- 简单短文本任务可以直接完成，不强制走完整流水线（即不强制大纲、搜索、素材确认环节）；但交付物仍必须是 Word 文档，不因任务简单而改为在对话中直接输出正文。
- 正式写作需求优先调用 `scripts/outline_reference.py` 获取范文参考大纲和后续搜索建议；接口未返回可用大纲或调用失败时，不中断任务，也不另行生成替代大纲，直接忽略该能力并按 3.1.4 原流程继续。
- 公文范文大纲接口不是深知搜索，不提供事实依据，只提供结构参考和搜索建议；不得把范文大纲中的内容当作政策、数据或案例依据。
- 大纲接口返回 `outline_available=true` 时，必须先向用户展示整理后的“建议大纲 + 搜索建议”并等待确认或调整；用户确认后，再根据确认后的大纲和搜索建议进入原有深知搜索流程。
- 只有在政策、数据、案例、文号、标准等支撑材料必要时才搜索。
- 搜索逻辑遵循 `reference/search_policy.md`，素材四分类和来源限制不得改变。
- 执行过搜索时，召回材料如何进入正文遵循 `reference/material_usage_guidance.md`；材料服务于观点，不得把搜索结果简单拼贴成正文。
- 本 Skill 内所有政策、数据、案例、素材检索默认只能使用深知可信工作台 MCP 工具 `mcp__dknowc__trusted_search`（作为深知搜索的接口转接层）；不得使用 Web Search、Web Fetch、浏览器搜索或公开网页抓取替代深知搜索。`scripts/dkag_search.py` 保留在包内仅作离线兜底/参考，不作为默认路径。
- 只要准备调用深知搜索，必须先给出搜索方案并等待用户确认；不得在同一轮里一边给方案一边执行搜索。
- 对复杂材料，先尝试范文大纲接口；只有接口返回可用大纲时才确认大纲和搜索建议。对简单短文本，能合理假设就先写。
- 所有正式写作任务（起草、改写、润色、压缩、审查后定稿等），默认交付 `.docx` Word 文档，即使用户没有明确说“生成 Word”；执行过搜索时另附 HTML 可信溯源报告。这是固定交付物，不得因任务简单而改为在对话中直接输出正文。
- 只有用户明确说“直接在对话里给正文”“不要生成 Word”“先看文字草稿”时，才在聊天中输出正文全文。
- 正式写作任务不得先在对话中发送“正文初稿”“压缩版”“预览版”或完整正文；应直接生成 Word，只给简短说明和文件路径。
- 正式公文 Word 默认保持纯净：正文中不得附带来源角标、`【素材使用情况】`、`【知识专库链接】` 或长 URL；执行过搜索时，可信溯源信息单独生成 HTML 辅助交付物。
- 生成的普通 Word 文档末尾必须保留 `【AI生成提示】内容由AI生成，内容仅供参考。`，这是普通 Word 正式交付的固定要求；红头文件为保证国标版记排版，不保留该提示，红头脚本会自动移除普通 Word 中已有提示。
- Markdown 草稿只能作为生成 Word 的内部临时文件；不得向用户展示、链接、发送或要求用户审阅 `.md` 草稿。
- 生成 Word 时，凡正文超过一行，必须先写入临时 `.txt` 或 `.md` 文件，再把文件路径作为 `scripts/format_document.py` 的输入参数；不得把整篇多行正文直接塞进 `--text` 参数，也不得用临时 Python 脚本直接手写 `python-docx` 生成正式交付文件。
- 默认只生成普通 Word；只有用户明确说“红头文件”“红头版”“套红头”“生成红头”时，才生成红头文件。
- 当前版本不支持自动生成 PDF，且不得主动向用户提及 PDF 交付能力。用户明确要求“输出 PDF”“生成 PDF”“转成 PDF”等时，只生成对应 Word 或红头 Word，并明确说明：当前版本暂不支持自动生成 PDF，建议用户使用已生成的 `.docx` 在本机 Word/WPS 中另存或导出为 PDF。
- 不得使用 LibreOffice、ReportLab、PyPDF2/pypdf、浏览器打印、HTML 转 PDF 或其他降级方案生成正式公文 PDF。
- 任一关键步骤出现异常时，必须暂停并向用户确认下一步；不得自行跳过搜索、改用 Web 搜索、改写任务目标或继续生成正式结果。
- 生成前后按任务风险调用 `reference/review_checklist.md`。

## 任务路由

开始工作前先判断任务类型和复杂度。具体规则见 `reference/task_router.md`。

常见路由：

- 简单会议通知、内部事务通知：读取对应标准，直接生成 Word 文档；只有用户明确说“直接在对话里给正文”“不要生成 Word”“先看文字草稿”时，才在对话中输出正文。
- 普通通知、函、短报告：必要时追问少量关键信息，然后生成。
- 请示、复函、政策依据型报告：通常需要搜索，按搜索规则执行。
- 管理办法、实施方案、调研报告、工作总结、产业研究总结：通常先确认大纲或搜索方案，再生成 Word。
- 用户要求“看看有什么问题”：进入 Reviewer 模式，优先输出问题清单。
- 用户要求“生成 Word”：只生成普通 Word。
- 用户明确要求“红头文件/红头版/套红头/生成红头”：先生成普通 Word，再使用代码化红头脚本生成红头文件。
- 用户明确要求“PDF”：仍只生成对应 Word 作为正式公文主产物；如同时要求红头 PDF，先生成红头 Word；然后说明当前版本暂不支持自动生成 PDF，建议用户用 Word/WPS 自行导出。

## 范文大纲规则

正式写作需求进入搜索或正文生成前，优先尝试调用公文范文大纲接口：

```bash
python3 <skillDir>/scripts/outline_reference.py "用户写作需求" --output outline_任务名.json
```

`用户写作需求` 必须尽量使用用户原始需求的完整表述，保留文种、主题、地域、用途、重点内容和交付要求；不得只传入压缩后的标题或文件名。例如用户要求“关于深圳市人工智能赋能基层治理应用情况的调研报告，重点包括发展背景、主要做法、典型应用场景、存在问题和下一步建议”，不得压缩成“深圳市人工智能赋能基层治理应用情况调研报告”后调用。

未指定目录的范文大纲结果保存到 `official-docs/outline-results/`。调用时使用环境变量 `DKNOWC_API_KEY`，不得向用户展示 API Key、接口参数或内部保存路径。脚本输出中 `request_success` 只表示接口请求成功，是否有可用大纲必须看 `outline_available`；`outline_available=false` 时，直接忽略范文大纲能力，不向用户确认大纲，也不要让模型自行生成替代大纲。

触发范围：

- 起草、撰写、生成正式公文或事务文书
- 报告、总结、计划、方案、汇报材料、讲话稿、发言材料、经验交流材料、调研分析、政策研究等长篇材料
- 用户明确要求“先给大纲”“参考范文结构”“设计写作框架”

可跳过范围：

- 简单会议通知、时间地点变更、短告知、短提醒
- 用户明确要求直接输出短正文，且无需政策、数据、案例或复杂结构
- 用户提供完整大纲并要求严格按其大纲写作

范文大纲接口同样使用 `DKNOWC_API_KEY`。任务不需要搜索且未配置 Key 时，直接跳过范文大纲，按文种标准写作，不引导用户配置 Key；任务需要搜索时，按“启动初始化”先确保 API Key 已配置，再调用范文大纲接口。

大纲接口返回可用结果时，向用户展示：

- 建议标题和文种
- 建议大纲，每个一级标题附简短写作目的和要点
- 后续搜索建议，只展示检索方向和用途，不展示脚本参数

用户可见确认内容必须使用清晰的 Markdown 分节和列表，不得把大纲、写作要点和搜索建议压缩成一个长段落，也不得只给“确认执行/调整后执行”而不展示可读结构。推荐格式：

```text
我先根据范文库生成了参考大纲和后续搜索建议，请确认是否按这个结构继续，或告诉我需要调整哪些部分。

建议大纲：

一、发展背景与战略意义
- 写作目的：……
- 主要要点：
  - ……
  - ……

二、主要做法与推进路径
- 写作目的：……
- 主要要点：
  - ……

后续搜索建议：

1. 政策依据
- 检索方向：……
- 用途：……

2. 数据支撑
- 检索方向：……
- 用途：……

3. 参考案例
- 检索方向：……
- 用途：……
```

确认话术：

```text
我先根据范文库生成了一个参考大纲和后续搜索建议，请确认是否按这个结构继续，或告诉我需要调整哪些部分。确认后我再进入政策、数据和案例检索。
```

用户确认或修改后，再进入深知搜索方案设计。大纲接口返回的 `search_suggestions` 只能作为搜索方案设计输入，必须转化为用户可理解的搜索项后再次确认；不得直接当作已经检索到的素材。

大纲接口未返回可用结果、超时、权限异常或服务异常时：

- 不阻断写作流程。
- 不向用户展示“未获取到可用范文大纲”之类的中间状态，除非用户明确询问。
- 不让模型自行生成替代大纲，也不进入“大纲确认”环节。
- 直接按 3.1.4 原流程继续：需要搜索时设计搜索方案并等待用户确认；不需要搜索时按文种标准直接写作或生成 Word。

## 搜索规则

需要搜索时，严格遵循 `reference/search_policy.md`：

1. 设计搜索方案，覆盖政策依据、数据支撑、参考案例等必要维度；不要把“表述参考型”设计为独立搜索项。
2. 使用自然语言 query，按行政层级和素材类型拆分检索。
3. 向用户展示搜索方案并停止，等待用户确认或调整。
4. 用户确认搜索方案后，必须调用深知可信工作台 MCP 工具 `mcp__dknowc__trusted_search` 执行深知搜索；如用户调整，按调整后的方案执行。每次调用把 MCP 返回保存为 JSON，再用 `scripts/adapt_mcp_result.py` 规范化为 `dkag_search.py --json-only` 同构的接口 JSON（保持后续合并、溯源报告脚本兼容）。搜索项的“搜索目的”作为 `purpose` 说明保留在规范化 JSON 中，用于后续知识专库链接外显文字；该内容不得展示给用户。
   - 多个搜索项必须默认串行执行：完成第 1 项并确认结果 JSON 写入后，再执行第 2 项，以此类推。
   - 不得使用并发、后台任务、并行命令、批量同时请求或多 Agent 同时调用搜索接口。
   - 只有用户明确要求提速并确认可接受并发风险，且平台和接口限流条件允许时，才可以并发搜索；否则一律串行。
5. 将召回素材分为四类：政策依据型、数据支撑型、参考案例型、表述参考型；表述参考型只能从已召回材料中归纳，不单独搜索。
6. 按 `reference/material_usage_guidance.md` 判断各类材料的正文用途，区分依据、数据、案例和表述参考。
7. 严禁将外省政策作为本省政策依据。
8. 对政策依据、数据支撑、参考案例做充分性自检，必要时补搜。
9. 用户确认素材后，再进入大纲或 Word 生成；正式写作任务不得把正文初稿作为聊天消息发出，直接生成 Word（执行过搜索时另附 HTML 可信溯源报告）。
10. 执行过搜索时，正式公文正文不再内嵌来源角标、知识专库链接或溯源卡片；必须另行生成 `标题_可信溯源报告.html`，将完整正文写入 HTML，并把正文中的 `[1]`/`【1】`角标变成可点击的来源跳转。报告底部统一展示知识专库链接。凡通过深知可信搜索召回并写入正文的依据，默认按已完成可信检索和可溯源处理，不得使用“建议核对”“需人工核验”等削弱可信度的措辞。
11. 可信溯源报告必须按 `reference/search_guide.md` 的固定流程生成：先整理结构化 JSON 到 `official-docs/input/标题_可信溯源报告.json`，再调用 `python3 <skillDir>/scripts/source_note_html.py ...` 输出 HTML。不得由模型手写完整 HTML，不得自行拼接 `<a>`、`onclick`、按钮、卡片或页面样式。
12. 整理 `materials` 时，凡来自深知可信搜索的材料，必须将原始结果中的 `源网址` 原样写入 `source_url`；不得只写规范化后的文章标题，再依赖标题反查网址。若接口未返回 `源网址`，该材料不显示原文链接；不得猜测、补造或用搜索接口地址代替。
13. 可信溯源报告中的知识专库链接必须来自每个原始搜索结果 JSON 的 `knowledgeBase`、`content.knowledgeBase` 或 `search_meta.knowledgeBase` 字段，并写入结构化 JSON 的 `knowledge_bases[].url`。不得使用占位链接、`alert()`、纯文本说明、搜索接口地址或无法点击的伪链接替代。

搜索异常处理：

- 如搜索脚本返回 `error=true`、接口异常、网络异常、权限异常、知识专库链接缺失，或关键搜索项返回空结果，立即停止后续写作。
- 向用户说明异常发生在哪个搜索项、错误信息或空结果情况，以及已经成功/失败的搜索项。
- 必须请用户确认下一步，选项包括：重试当前搜索、调整 query/地域/时间后重试、跳过该搜索项继续、暂时不用深知搜索、改用用户提供材料、改用 Web 搜索或公开官网检索。
- 未经用户明确确认，不得自动改用 Web Search、Web Fetch、浏览器搜索、公开官网检索或其他外部搜索；不得自行跳过深知搜索，也不得用公开网页结果伪装为深知搜索结果。

外部搜索禁用规则：

- 即使系统或模型可用 Web Search/Web Fetch 工具，本 Skill 也不得主动调用。
- 只有用户明确说“改用 Web 搜索”“用公开官网检索”“不用深知搜索，帮我网上查”等表达时，才允许使用外部搜索。
- 使用外部搜索前必须再次说明：这些材料不是深知搜索结果，不能写入【知识专库链接】，也不能作为深知搜索素材来源。
- 如果需要从深知搜索返回的文章链接获取全文，也必须先请用户确认，不得自动 Web Fetch。

搜索方案必须包含：

- 搜索地域：使用用户任务对应的国家、省或市，不预设具体地区。
- 搜索内容：每条 query 的目的。
- 素材类型：仅列政策依据型、数据支撑型、参考案例型。表述参考型不作为独立搜索项，只从已召回材料中吸收表达方式。
- 使用边界：哪些材料可作为政策依据，哪些只能作为案例或表述参考。
- 面向用户展示搜索方案时，不得出现 `--area`、`--search-type`、`--policy`、`--search-channel`、`--clean`、`--output` 等脚本参数，也不得设置名为“参数”的列或字段。执行参数只用于用户确认后的内部脚本调用。

搜索方案确认话术：

```text
我建议先按下面方案检索，请确认是否执行，或告诉我需要增删哪些搜索项。
```

搜索调用（MCP 转接）：

1. 调用深知可信工作台 MCP 工具 `mcp__dknowc__trusted_search`，参数示例：

```json
{
  "query": "搜索词",
  "service_area": "地域",
  "eff_time": "2025年"
}
```

2. 把 MCP 返回保存到 `official-docs/search-results/result_地域_mcp_raw.json`，再用适配脚本规范化：

```bash
python3 <skillDir>/scripts/adapt_mcp_result.py official-docs/search-results/result_地域_mcp_raw.json \
  --output official-docs/search-results/result_地域.json \
  --mode search
```

未指定目录的搜索结果文件会保存到 `official-docs/search-results/`；合并搜索结果时也只能读取和写入本 Skill 的 `official-docs/input/`、`official-docs/output/`、`official-docs/search-results/` 工作目录。

`eff_time` 只用于 `2025年`、`2025年08月`、`2025年08月15日` 这类单个明确时间点；不要传 `2023-2025` 这类范围。没有明确时间点时省略 `eff_time`。

深知搜索接口（经 MCP）默认每篇材料返回 2 个相关段落；调用时不要额外传段落数量或精简参数。

合并命令（合并规范化后的 JSON）：

```bash
python3 <skillDir>/scripts/merge_search_results.py result1.json result2.json --output merged.json
```

## 写作规则

生成正文前，按文种读取对应标准文件：

- 报告：`reference/standards/01_report.md`
- 请示：`reference/standards/02_qingshi.md`
- 批复：`reference/standards/03_pifu.md`
- 通知：`reference/standards/04_tongzhi.md`
- 意见：`reference/standards/05_yijian.md`
- 函：`reference/standards/06_han.md`
- 会议纪要：`reference/standards/07_minutes.md`
- 通报：`reference/standards/08_tongbao.md`
- 通告：`reference/standards/09_tonggao.md`
- 公告：`reference/standards/10_gonggao.md`
- 无意见复函：`reference/standards/11_fuhan_approve.md`
- 有意见复函：`reference/standards/12_fuhan_objection.md`
- 提醒函：`reference/standards/13_reminder.md`
- 决定、决议、命令、公报、议案等低频法定文种：`reference/standards/16_decision.md`、`reference/standards/17_resolution.md`、`reference/standards/18_order.md`、`reference/standards/19_gazette.md`、`reference/standards/20_motion.md`，或未明确文种时使用 `reference/standards/14_generic.md`
- 事务文书：`reference/standards/15_business_docs.md`、`reference/standards/21_explanation.md`、`reference/standards/22_application.md`、`reference/standards/23_publicity.md`、`reference/standards/24_procurement.md`

写作时正文不加引用标记。执行过搜索时，正文只写正式内容，不在文末追加素材使用情况或知识专库链接；素材溯源说明作为单独 HTML 辅助文件生成，格式见 `reference/search_guide.md`。

正文一律使用中文全角标点，引号使用中文全角引号 `" " ' '`，禁止英文半角引号 `"` `'`。生成正文时直接写全角引号，不依赖排版脚本转换；定稿检查时按 `reference/anti_ai_patterns.md` 核对。

所有正式写作、改写、润色、压缩任务，生成正文前必须按 `reference/fact_discipline.md` 约束事实边界：材料已给事实保持原状态强度，材料未谈事项省略，占位符不得残留，改稿以最新版底稿为主线，不得为显得完整而补写责任、时限、下一步等材料没有的内容。

对工作总结、工作要点、实施方案、专项整治方案、会议讲话、研讨发言、汇报材料等长篇材料，生成正文前还应读取 `reference/standards/99_expressions.md`，内部完成结构选择、小标题策略和段落功能分配。该文件只提供通用写作方法，不得机械套用参考句式，也不得用表达增强替代事实、措施和责任。长篇材料定稿前按 `reference/anti_ai_patterns.md` 做语言复核，排查旁白句、思考泄露、二元包装、口号收尾、空泛词和格式噪点。

执行过搜索时，生成正文前必须读取 `reference/material_usage_guidance.md`。它只提供材料使用原则，不强制套用固定结构；写作时应优先满足用户任务和文种要求，再把政策、数据、案例材料转化为支撑观点的内容。

执行过搜索时，知识专库链接必须逐条从搜索结果 JSON 的 `knowledgeBase` 字段复制到可信溯源报告 HTML，不得手写、猜测、改写或使用合并文件中丢失来源的链接。若某个搜索结果没有 `knowledgeBase`，按搜索异常处理规则请用户确认。

高风险事实处理：

- 政策名称、文号、发布日期、精确数字、排名、占比、金额、全国首个/领先/唯一等表述，只有来源明确且口径一致时才写成确定结论。
- 超出用户题目时间范围的信息，只能作为背景、延续动态或趋势参考，不得混作当期政策、当期成效或已经完成事项。
- 无法通过深知可信搜索确认的具体数据和文号，不写入正文；如确有参考价值，只能改用概括表述。可信溯源报告只展示已通过深知可信搜索完成召回、来源定位和溯源核验的材料，不再列“需人工核验信息”。
- 通知、函、请示等短公文默认少检索、少堆依据，优先把事项、对象、责任、时限和报送要求写清楚。
- 调研报告、政策研究报告和产业研究材料必须形成“事实支撑-问题判断-原因分析-对策建议”的链条，避免只堆政策、数据和案例。

表格写作与排版规则：

- 只有在需要呈现重复记录、指标对比、政策维度比较、责任分工、时间安排、问题清单等行列数据时，才使用表格；普通论述、原因分析和建议段落不得为了显得丰富而硬塞表格。
- 表格不得直接作为文档小节标题使用。表格应归入统一的章节编号体系中，放在一个汇总性、比较性或综述性小节内。
- 正文中每张表格都必须有表题，如“表1 五省粮食产量对比”。表题是表格名称，不是小节标题；表题作为普通文字出现在小节标题下方，不使用 `#`、`##`、`###` 或 `####` 标题语法。不得生成无表题表格。
- 正文中的表格编号按全文出现顺序连续编号（表1、表2、表3……），不按章节重新编号；多个表格可以归入同一个汇总小节，各自拥有独立表题编号。
- 生成 Word 时允许使用标准 Markdown 表格。普通竖版表格建议控制在 3-6 列；超过 6 列的宽表、用户明确要求“横排表格”的表格，或表格前一行写有 `<!-- landscape-table -->` 标记时，排版脚本会单独切换到横向 A4 页面生成表格，再恢复竖向正文。
- 表格跨页时不重复表头；排版脚本会尽量避免同一行、同一单元格内容被拆到两页。若单个单元格内容过长，Word 仍可能强制分页，因此长内容应改为正文段落或分条说明。
- 表格内容应简洁可读。若单元格主要是长段落，应改为正文段落、分条说明、清单或附件，不应塞入正文表格。

## 审查规则

以下情况必须执行审查：

- 执行过搜索
- 请示、复函、政策依据型报告
- 管理办法、实施方案、调研报告
- 工作总结、工作要点、专项整治方案、会议讲话、研讨发言、汇报材料等长篇材料
- 用户要求正式 Word 或红头文件
- 用户明确要求检查、审核、把关

审查清单见 `reference/review_checklist.md`。发现问题时先列问题，再说明修改建议。用户上传已有 Word 时，格式审查和内容审查可以分别执行，也可以组合执行；执行内容审查并使用搜索时，必须生成可信溯源报告 HTML。

语言与格式审查时，可按 `reference/anti_ai_patterns.md` 检查旁白句、思考泄露、二元包装、口号收尾、空泛词和格式噪点；需要时可选运行 `python3 <skillDir>/scripts/prose_lint.py <草稿文件> --format --structure` 做语言质检。脚本只提示语言、格式和重复风险，不检查文种要素完整性，不自动改写；不得把脚本结果作为不加判断的硬性清洗命令。

## Word 输出

首次使用或用户要求检查环境时：

```bash
python3 <skillDir>/scripts/initialize.py
```

如果 `python3` 不可运行，或初始化结果显示 `ready=false`、`python_docx=false`、`requests=false`，必须先暂停，不得继续执行本 Skill 的搜索、写作、Word、红头和可信溯源报告 HTML 生成。缺失 `python-docx` 或 `requests` 时，先请用户确认是否允许安装。API Key 只在任务需要深知搜索时才要求：不需要搜索的任务（简单通知、改写、润色、只生成 Word）即使 `api_key_configured=false`、`search_ready=false` 也可正常生成 Word；需要搜索的任务缺少有效 API Key 时，按“启动初始化”中的 MaaS 注册和环境变量配置流程处理。

用户明确授权保存常用设置时，才执行：

```bash
python3 <skillDir>/scripts/initialize.py --organization "用户提供的单位" --doc-prefix "用户提供的前缀" --region "用户提供的地域" --save
```

需要生成 Word 时，正文必须使用 `reference/output_guide.md` 支持的 Markdown 格式。

普通 Word：

```bash
python3 <skillDir>/scripts/format_document.py official-docs/input/official_doc_content.txt
```

调用前先把正文写入本 Skill 工作目录下的 `official-docs/input/` 临时正文文件。默认保存到 `config/format.json` 的 `output.dir`，且输出只能位于 `official-docs/output/`；脚本默认从正文标题生成正式文件名，并在同名文件已存在时追加 `_v1`、`_v2`。如用户明确要求保存文件名，可传入 `--output 文件名.docx`。只有一句话以内的极短文本才允许使用 `--text`；多行正文不得直接通过命令行参数传入，避免换行被破坏后整篇文档变成一个段落。

红头 Word：

```bash
python3 <skillDir>/scripts/template_generator.py 通知 --input 普通Word文件路径 --org "发文机关" --doc-number "发文字号"
```

红头脚本只能在用户明确要求红头时调用。用户只要求“生成 Word”“正式 Word”“排版文件”时，不调用红头脚本。

当前版本不支持自动生成 PDF，也不提供 PDF 转换命令。用户明确要求 PDF 时，生成正式 `.docx` 或红头 `.docx` 后，提示用户使用本机 Word/WPS 的“另存为 PDF”或“导出 PDF”功能完成转换；不得声称已生成 PDF。

生成成功后，优先返回正式 `.docx` 文件路径和一句简短说明。执行过搜索并生成可信溯源报告 HTML 时，可同时返回辅助文件路径，但必须明确主文件是正式成稿、可信溯源报告不是正文附件。不要发送 Markdown 草稿、正文初稿、完整正文或中间文件路径。

如需先把正文落为临时 Markdown 文件供脚本读取，必须在同一工作流中继续生成 `.docx`；不得停在 Markdown 草稿，也不得把 Markdown 文件作为阶段性成果发给用户。只有用户明确要求“先看草稿”“先发 Markdown”“不要生成 Word”时，才可以交付 Markdown 或正文预览。

对“写一份/起草/生成/整理/形成/润色/改写……”等所有正式写作任务，默认理解为需要 Word 正式文件交付（执行过搜索时另附 HTML 可信溯源报告）；不得因为用户未写“Word”就先把正文粘贴到聊天窗口。简单会议通知、内部事务通知、短改写等任务同样默认交付 Word。
