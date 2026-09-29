---
name: "深知公文写作"
slug: "dknowc-official-doc-writer-skillhub"
display_name: "深知公文写作"
display_name_en: "dknowc official doc writer"
description: "深知公文写作，是面向单位办公室、综合岗、文秘、材料岗和企事业单位用户的正式材料写作助手。核心用于公文写作、正式文书起草、汇报材料整理、讲话稿撰写、工作总结和方案报告生成，帮助用户把零散想法、会议记录、工作素材、调研资料或初稿，整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿。支持通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、方案、总结、管理办法、汇报材料、发言稿、讲话稿、调研报告、经验材料等常见文种和工作材料。可进行起草、改写、润色、扩写、压缩、标题优化、结构调整、语气统一和内容审查。涉及政策依据、数据支撑、标准规范或案例参考时，可调用深知可信搜索获取素材，并单独生成溯源核验报告，帮助用户写得有依据、能复核、可交付。正式交付时支持生成 Word 文档；用户明确需要时，也可生成红头文件。"
description_zh: "深知公文写作，是由北京彩智科技有限公司旗下“深知可信智能”提供的正式材料写作助手，准确、规范地完成企事业单位与政府机关等场景下的文档编写需求，所有依据或参考材料，都全程可溯源到权威部门发布的规范性文件。本技能用于公文写作、正式文书起草、汇报材料整理、讲话稿撰写、工作总结和方案报告生成，帮助用户把零散想法、会议记录、工作素材、调研资料或初稿整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿。本技能还能严格按公文相关国家标准，支持通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、方案、总结、管理办法、汇报材料、发言稿、讲话稿、调研报告、经验材料等常见文种和工作材料。依托深知可信搜索，获取准确有效的法规政策依据、行业信息与数据、标准规范和案例参考，并单独生成所有材料的溯源说明与原文清单，帮助用户写得有依据、能复核、可交付。正式交付时支持生成 Word 文档；并可按用户明确要求自动生成红头文件。"
description_en: "dknowc official doc writer is a formal-document writing Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It helps users draft, rewrite, polish, review and generate structured workplace documents, including official documents, formal letters, reports, meeting minutes, summaries, plans, speeches, research reports and other business materials. When evidence, data, standards or reference cases are needed, it can use dknowc Trusted Search to retrieve traceable materials from authoritative sources and generate a separate source-reference report. Final outputs can be generated as Word documents, and red-head document formatting is supported when explicitly requested by the user."
category: "office-efficiency"
version: "3.7.7-dsh"
author: "彩智科技"
permissions:
  network:
    - "https://open.dknowc.cn/"
    - "https://platform.dknowc.cn/"
  local_read:
    - "本 Skill 的 reference、config、official-docs、knowledge-base 等规则、标准、配置、参考资料和个人素材库文件"
  local_write:
    - "本地初始化状态文件"
    - "本机 Key 专用配置文件（~/.config/dknowc/api_key）中的 DKNOWC_API_KEY"
    - "用户明确授权保存的写作偏好"
    - "用户明确授权保存的个人素材库文件（knowledge-base/ 目录）"
    - "生成的 Word 文档"
    - "溯源核验报告与搜索结果中间文件"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知公文写作

深知公文写作由北京彩智科技有限公司旗下“深知可信智能”提供，是面向正式材料写作场景的组合型 Agent Skill。它不是固定从头到尾执行的演示脚本，而是根据任务选择最小必要流程，帮助用户完成公文写作、正式文书起草、汇报材料整理、讲话稿撰写、总结方案生成、素材检索、溯源核验报告和 Word 交付。

> **dsh Key 机制**：dsh 清理名字含 KEY 的隐式环境变量，但**专用配置文件读取不受影响**——注册成功后 Key 写入 `~/.config/dknowc/api_key`，本会话检索/大纲脚本立即可用（无需重启 dsh）。仅 dsh 捆绑的 MCP 兜底工具需重启后加载新 Key。
>
> **dsh 检索通道**：检索与范文大纲一律走脚本直连（全量结构化返回）；dsh 捆绑的 MCP 工具（trusted_search / deep_query / doc_outline）返回为精简视图，仅作应急兜底（经 `mcp_direct.py` + `adapt_mcp_result.py`，含 outline 模式），不据此生成正式溯源核验报告。

## 权限说明

本 Skill 会访问 `https://open.dknowc.cn/` 用于公文范文大纲、深知可信搜索和溯源核验报告整理；访问 `https://platform.dknowc.cn/auth/#/login` 用于 MaaS 手机号验证码注册、API Key 获取和管理平台地址说明。运行过程中会读取本 Skill 的规则、标准、配置和参考资料文件，并在本地写入初始化状态文件、用户授权保存的写作偏好、生成的 Word 文档、溯源核验报告和搜索结果中间文件。MaaS 注册取 Key 成功后，会把 `DKNOWC_API_KEY` 写入本机 Key 专用配置文件（`~/.config/dknowc/api_key`，纯文本一行 Key、600 权限，不写 `~/.zshrc`）；脚本读取顺序为进程环境变量优先、缺失时自动读取该文件，历史 `~/.zshrc` 中的 Key 块仅作迁移期兜底。Skill 包内不包含真实 API Key，API Key 必须通过环境变量 `DKNOWC_API_KEY` 注入或配置文件持久化，不得硬编码，不得写入公开包，不得在对话中展示完整内容。

## 设计模式

本 Skill 组合使用五种模式：

- Tool Wrapper：封装公文范文大纲、深知搜索、普通 Word 排版、红头文件生成和溯源核验报告 HTML 生成。
- Generator：根据文种标准、用户材料和素材指引生成公文正文。
- Reviewer：按审查清单检查格式、逻辑、素材来源和公文风险。
- Inversion：复杂任务或关键信息缺失时，先向用户追问。
- Pipeline：仅在政策依据型、长篇复杂材料、红头交付等场景执行带检查点的严格流程。

## 启动初始化

SkillHub Public 版不内置深知搜索 API Key。API Key 必须通过环境变量 `DKNOWC_API_KEY` 注入。本 Skill 被调用后，先运行一次初始化检查：

```bash
python3 <skillDir>/scripts/initialize.py
```

初始化用于检查 Python、`python-docx`、`requests` 等基础运行环境，不要求用户提供单位或个人信息，也不上传检测结果。初始化不是 API Key 硬性门禁：只有当当前任务确实需要调用深知搜索时，API Key 才是前置条件。

**素材检索与范文大纲一律走本 Skill 脚本通道**（`deep_query.py` / `dkag_search.py` / `outline_reference.py`），需要 API Key（3.7.5 起不再检测、不再走 MCP「深知可信工作台」通道——MCP 侧大结果落盘方案改造完成后另行加回）。素材检索按**两阶段执行（3.7.5 起）**：首轮用 `deep_query.py` 做**深度搜索广度召回**（3 路按素材类型，query 用「对象+关注方向」句式），返回 JSON 落盘后运行 `python3 <skillDir>/scripts/deep_convert.py` 转换；补搜用 `dkag_search.py` 做**可信搜索精准补强**（深度搜索含快照/段落标题/可信度，但缺独立"文号"字段，政策依据型必补搜匹配文号，数据/案例按缺口补）。范文大纲用 `outline_reference.py`。深度搜索与可信搜索的返回都**立即完整原样落盘**并 `json.load` 校验后再转换，研究资料、溯源 JSON 整理与核验报告全部按现有流程执行（深度产物含快照/段落标题/可信度、缺独立文号字段；补搜产物四字段完整）。搜索与大纲失败时先串行重试该路一次（鉴权竞争多为瞬态）；任一路额度用尽（`quota_exhausted=true`）整批停止、禁止任何重试、引导 MaaS 平台；重试仍失败才如实告知用户并暂停等待确认，不得擅自改用 Web 搜索或跳过检索。

### 不需要搜索的任务

简单通知、内部事务通知、改写、润色、审查、基于用户材料写作、只生成 Word 或红头文件等不涉及政策、数据、案例检索的任务，只要 `python3`、`python_docx`、`requests` 就绪即可继续写作，不要求配置 API Key，也不必引导用户注册 MaaS。初始化结果显示 `api_key_configured=false` 或 `search_ready=false` 时，不阻断这类任务，直接按原任务流程继续。

### 需要搜索的任务

只有任务确实需要深知搜索（需要政策依据、数据支撑、案例参考，或用户明确要求查最新政策、最新情况、权威数据）时，API Key 才是前置条件。初始化结果显示 `api_key_configured=false`、`search_ready=false` 或 `search_blocking_issues` 包含 `api_key_missing` 时，暂停原任务，按引导规则向用户说明并引导开通。

引导与注册各环节的固定话术（S1 引导开通 / 索要手机号 / 验证码错误 / 开通成功含积分 / 报错 / FAQ）统一见 `reference/onboarding_scripts.md`，按场景取用、要素不可删改。脚本输出含 `user_message` 字段时**必须原样转述**。

硬规则：

- **引导前禁示**：在用户确认开通或明确拒绝之前，不得输出任何"已核实 / 已查到 / 均为官网原文"类政策内容。需要搜索的材料，政策依据只能来自真实深知检索或"待补"标注，禁止用模型自身知识冒充检索结果。
- 先价值、后验证：先让用户理解搜索对当前材料的价值与开通权益（注册赠送 10 万积分 + 实名认证再送 10 万积分，在 S1 一并告知），再提手机号；不得开口就要手机号。引导时机后置：优先在搜索方案确认后再引导。
- 退路只有"标待补继续写"一种，禁止承诺"用联网检索替代、同样可溯源"。
- 不向用户暴露内部术语（MaaS、API Key、环境变量名、脚本名、渠道码）；用户侧只说"开通搜索功能"。
- 样例悬念式出示：引导后用户未立即同意或提出疑问 → 立即出示 `reference/sample_trace_report.html` 示例（示例数据仅供展示，不得作为写作素材）。
- 用户拒绝后不纠缠；交付后轻提示每个任务最多一次。
- 手机号全程脱敏显示。

**MCP 取 Key 优先（dsh 不适用）**：该路径依赖宿主「深知可信工作台」连接器的 OAuth `create_api_key` 工具——dsh 捆绑 MCP 为 Bearer API Key 认证、无 OAuth 通道，**dsh 场景直接走手机号验证码注册**（流程见「需要搜索的任务」）。`save-key` 子命令保留（可配合其他宿主取到的密钥落盘）。

- **调用成功**：返回顶层 JSON `{"apiKey": "<密钥>"}`（无 content 包裹、无说明文字，`sk-` 开头）。立即把密钥交给脚本落盘，**不再向用户索要手机号与验证码**，也不得再走 S1 开通话术：

  ```bash
  printf '%s' "<密钥>" | node <skillDir>/scripts/register.mjs save-key
  ```

  成功后转述脚本 `user_message`（固定话术见 `reference/onboarding_scripts.md` S0），再用已写入的 Key 重跑 `python3 <skillDir>/scripts/initialize.py` 确认 `api_key_configured=true`，继续原任务。密钥不得在对话正文中展示。
- **工具不存在，或调用返回"请先完成 MCP OAuth 授权"等错误**：视为该宿主未安装/未授权该 MCP，**直接回落到下面的手机号验证码注册流程**（流程不变），不向用户提及 MCP 内部细节、不反复重试取 Key。

MaaS 注册两步执行（初始化输出 `guide_message` 已含引导话术）：

```bash
node <skillDir>/scripts/register.mjs send --phone <手机号>
```

成功后转述脚本 `user_message`（含脱敏号码与"最新一条"提示），等待用户提供 6 位验证码，不得自行编造。

```bash
node <skillDir>/scripts/register.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

成功后转述脚本 `user_message`（额度到账轻确认；`existed=true` 时为老用户找回话术），并按 `envWriteSucceeded` 处理：**为 true** 时脚本已把 Key 写入本机专用配置文件（`~/.config/dknowc/api_key`），直接用返回的 Key 重跑初始化确认后继续原任务；**为 false** 时以脚本返回的 `apiKey` 临时注入环境变量（`DKNOWC_API_KEY=<key> python3 <skillDir>/scripts/initialize.py`）完成本次任务，不得据此判定注册失败、不得重复走手机号流程。不得向用户展示完整 Key。默认不重新生成 Key，仅用户明确要求时追加 `--new-key`。注册失败按脚本 `user_message` 处理；连续失败降级引导 `https://platform.dknowc.cn/auth/#/login`。

## 参考资料（渐进式读取）

按任务条件只加载命中的参考资料，不一次性读取全部文件。每个文件只在对应阶段读取，未命中条件不预读。

| 文件 | 阶段 | 加载条件 |
| --- | --- | --- |
| `reference/task_router.md` | 任务开始 | 判断任务类型与复杂度，所有任务先读 |
| `reference/revision_workflow.md` | 改稿轮 | 用户基于已交付 Word 提修改意见的连续改稿 |
| `reference/local_memory_guide.md` | 素材/偏好管理时 | 素材库或偏好数量大于 0，或用户要求保存/查看/删除素材与偏好时 |
| `reference/fact_discipline.md` | 起草/改稿前 | 所有正式写作任务，约束事实边界 |
| `reference/anti_ai_patterns.md` | 定稿前/审查 | 正式正文语言复核、去 AI 味、审查模式 |
| `scripts/prose_lint.py` | 定稿前 | 检查草稿语言、格式、重复风险（可选） |
| `scripts/local_memory.py` | 写作前/写作后 | 素材库或偏好数量大于 0 时检索素材、应用偏好；用户确认保存时写入 |
| `reference/search_policy.md` | 搜索前 | 需要政策/数据/案例检索时 |
| `reference/search_guide.md` | 执行搜索后 | 生成溯源核验报告 HTML 时；参考范文召回时（第四节流程） |
| `scripts/extract_reference.py` | 参考范文召回时 | 用户同意取全文后，从 `--full` 召回结果中按标题提取**目标范文单篇**全文并落盘 |
| `reference/material_usage_guidance.md` | 执行搜索后 | 召回素材如何进入正文 |
| `reference/research_notes.md` | 素材确认后 | 研究型与综合长篇文种（调研报告、政策/产业研究、综合总结）动笔前生成研究资料 |
| `scripts/deep_query.py` | 首轮检索前 | 深度搜索脚本（deep-query/v3，需 API Key） |
| `scripts/deep_convert.py` | 执行深度搜索后 | 深度搜索返回转成与 `--clean` 同构的形态（含快照/段落标题/可信度；缺独立文号字段） |
| `reference/output_guide.md` | 生成 Word 前 | 正文 Markdown 格式、Word 交付 |
| `reference/review_checklist.md` | 生成前后 | 按任务风险执行审查时 |
| `reference/onboarding_scripts.md` | 引导开通/注册/报错时 | 需要引导开通搜索、注册流程任一步、或注册与搜索接口报错沟通时 |
| `reference/search_intro.md` | 引导用户时 | 需要向用户说明搜索功能时 |
| `reference/sample_search_result.md` | 引导用户时 | 用户对检索效果有疑问或犹豫，需展示检索结果形态 |
| `reference/sample_trace_report.html` | 引导用户时 | 需要向用户展示溯源核验报告效果 |
| `reference/standards/*.md` | 按文种 | 命中对应文种时读取（见"写作规则"） |

## 个人素材库与写作偏好

本 Skill 在本机维护个人素材库 `knowledge-base/` 与写作偏好 `config/writing_preferences.json`，均只对当前用户生效、不随公开包分发、不上传。初始化结果 `local_memory` 字段返回二者数量；数量大于 0 时，写作任务应先检索素材库并应用偏好。

- 保存或删除素材/偏好必须先经用户确认；一次性使用的内容不保存。
- 素材库命中的材料按用户提供的材料对待（与当轮材料同优先级，高于搜索素材），仍须遵守 `reference/fact_discipline.md` 事实边界。
- 用户明示的写作偏好优先于文种标准和默认排版（红头国标强制项除外，冲突时向用户说明）；与当轮要求冲突时当轮优先。

命令与完整规则（六类分类、沉淀时机、应用范围）见 `reference/local_memory_guide.md`。

## 工作原则

**环境与初始化**

- Python 和 `python-docx`、`requests` 是基础前置：无法运行 `python3` 或初始化显示 `python_docx=false`、`requests=false` 时，暂停写作、搜索、Word、红头和溯源报告能力；初始化细节与 Key 按需原则见"启动初始化"节。
- 依赖缺失且 `dependency_install_prompt_needed=true` 时（initialize 同时输出 `env_message`），按 `reference/onboarding_scripts.md` S6 说明——不出现组件名，就绪时不提环境话题；征得同意后 `python3 -m pip install python-docx requests`，装后重跑初始化确认 `ready=true`；不同意则 `--decline-dependency-install` 记录并不再询问。缺少 Python 或无权限安装时，提示切换到具备 Python 的运行环境。
- 字体不阻断、不检测、不引导安装；交付时提醒"打开端缺字体 Word/WPS 可能自动替换，以本机显示为准"。
- 仅在用户明确同意时用 `--save` 写入 `config/user_profile.json`；不得主动索取与当前公文无关的信息。
- 未配置发文机关、文号前缀或地域时仍可生成：用 `XX单位`、`XX〔年份〕XX号` 等醒目占位符，交付时提醒核对；不得根据示例、历史文档或搜索地域猜测用户单位，不得把具体客户名称作默认值。

**流程主干**

- 简单短文本直接完成，不强制大纲、搜索、素材确认环节。
- 正式写作需求先取范文大纲和搜索建议，调用 `scripts/outline_reference.py`（需 API Key）。工具/接口失败或 `outline_available=false` 时不中断、不自行生成替代大纲、不进大纲确认，直接按原流程继续。大纲接口只提供结构参考，不提供事实依据；返回可用结果时先展示"建议大纲 + 搜索建议"等用户确认后再进搜索流程。
- 只有在政策、数据、案例、文号、标准等支撑材料必要时才搜索；搜索逻辑遵循 `reference/search_policy.md`，素材四分类和来源限制不得改变；召回材料进入正文遵循 `reference/material_usage_guidance.md`，材料服务于观点，不得拼贴成正文。
- 本 Skill 所有素材检索只能走深知脚本通道（`deep_query.py` / `dkag_search.py`，3.7.5 起不再走 MCP），**两阶段（3.7.5 起）**：首轮用深度搜索做广度召回（`scripts/deep_query.py`，返回经 `scripts/deep_convert.py` 转换），补搜用可信搜索做精准补强（`scripts/dkag_search.py`）；不得用 Web Search、Web Fetch、浏览器搜索或公开网页抓取替代。准备调用深知搜索必须先给方案等用户确认，不得同一轮边给方案边执行。
- 任一关键步骤异常时暂停并向用户确认下一步；不得自行跳过搜索、改用 Web 搜索、改写任务目标或继续生成正式结果。生成前后按任务风险调用 `reference/review_checklist.md`。

**交付纪律**

- 所有正式写作任务默认交付 `.docx` Word（即使没明确说"生成 Word"），执行过搜索另附 HTML 溯源核验报告；只有用户明确说"直接在对话里给正文""不要生成 Word""先看文字草稿"时才在对话输出正文。不得先发"正文初稿/压缩版/预览版"，直接生成 Word 并只给简短说明和路径。
- 正式公文 Word 保持纯净：正文不带来源角标、`【素材使用情况】`、`【知识专库链接】`或长 URL；可信溯源信息单独生成 HTML。Word 正文与元数据均不写 AI 生成提示，AI 标识仅由交付话术承担（本稿由 AI 辅助生成、依据已经过可信核验，建议按单位审签流程核批后正式行文）；排版脚本自动过滤误带的提示行。
- Markdown 草稿只是生成 Word 的内部临时文件，不得展示、链接、发送或要求用户审阅。
- 生成 Word 时，正文超过一行必须先写入临时 `.txt`/`.md` 文件，再把文件路径传给 `scripts/format_document.py`；不得把多行正文塞进 `--text`，也不得用临时脚本手写 `python-docx` 生成正式交付文件。
- 默认只生成普通 Word；仅用户明确说"红头文件/红头版/套红头/生成红头"时生成红头。
- 当前版本不支持自动生成 PDF，不主动提及；用户要求 PDF 时只生成 Word 并说明建议在 Word/WPS 中自行导出。不得用 LibreOffice、ReportLab、pypdf、浏览器打印等降级方案生成正式公文 PDF。
- 版记：普通 Word 不自动生成（自动分页不可控）；用户要求版记时建议手工补充或改用红头（红头脚本生成国标版记），"抄送：××机关。"行按普通正文排版。
- 落款与联系人：落款单位右空两字、成文日期首字在单位首字右移两字处，脚本自动处理；联系人电话写入正文相关事项段、不独立成结尾段（上行文必须、平行文可选、下行文不强制，详见各文种标准）。
- 字体表述：交付时不主动说明字体；仅在用户问到或质疑时回答，一律写全称"仿宋_GB2312（公文标准字体）"，禁止简写"仿宋"——两者是不同字体，简写会误导。

## 任务路由

开始工作前先判断任务类型和复杂度。具体规则见 `reference/task_router.md`。

常见路由：

- 简单会议通知、内部事务通知：读取对应标准，直接生成 Word 文档；只有用户明确说“直接在对话里给正文”“不要生成 Word”“先看文字草稿”时，才在对话中输出正文。
- 普通通知、函、短报告：必要时追问少量关键信息，然后生成。
- 请示、复函、政策依据型报告：通常需要搜索，按搜索规则执行。
- 管理办法、实施方案、调研报告、工作总结、产业研究总结：通常先确认大纲或搜索方案，再生成 Word。
- 用户基于已交付 Word 提修改意见（"第二段太长""落款改一下""再加一节"等）：进入改稿轮，按 `reference/revision_workflow.md` 执行——以最新版 Word 为唯一底稿，逐条落实并汇报，默认不重复已完成搜索，交付 `_v1`/`_v2` 新版本。
- 用户要求“看看有什么问题”：进入 Reviewer 模式，优先输出问题清单。
- 用户要求“生成 Word”：只生成普通 Word。
- 用户明确要求“红头文件/红头版/套红头/生成红头”：先生成普通 Word，再使用代码化红头脚本生成红头文件。
- 用户明确要求“PDF”：仍只生成对应 Word 作为正式公文主产物；如同时要求红头 PDF，先生成红头 Word；然后说明当前版本暂不支持自动生成 PDF，建议用户用 Word/WPS 自行导出。

## 范文大纲规则

正式写作需求进入搜索或正文生成前，先取范文大纲。统一调用脚本接口（需 API Key）：

```bash
python3 <skillDir>/scripts/outline_reference.py "用户写作需求" --output outline_任务名.json
```

`用户写作需求` 必须尽量使用用户原始需求的完整表述，保留文种、主题、地域、用途、重点内容和交付要求；不得只传入压缩后的标题或文件名。例如用户要求“关于深圳市人工智能赋能基层治理应用情况的调研报告，重点包括发展背景、主要做法、典型应用场景、存在问题和下一步建议”，不得压缩成“深圳市人工智能赋能基层治理应用情况调研报告”后调用。

未指定目录的范文大纲结果保存到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/outline-results/`。接口使用环境变量/配置文件 `DKNOWC_API_KEY`；不得向用户展示 API Key、接口参数或内部保存路径。脚本输出中 `request_success` 只表示接口请求成功，是否有可用大纲必须看 `outline_available`；`outline_available=false` 时，直接忽略范文大纲能力，不向用户确认大纲，也不要让模型自行生成替代大纲。

触发范围：起草、撰写正式公文或事务文书（报告、总结、计划、方案、汇报材料、讲话稿、调研分析、政策研究等长篇材料），以及用户明确要求"先给大纲""参考范文结构"。可跳过：简单会议通知、时间地点变更、短告知短提醒、用户提供完整大纲要求严格照写、或明确要求直接输出短正文。

大纲接口使用 `DKNOWC_API_KEY`（环境变量或配置文件）。任务不需要搜索且未配置 Key 时，直接跳过范文大纲，按文种标准写作，不引导用户配置 Key；任务需要搜索时，需确保 API Key 已配置后调用脚本接口。

大纲接口返回可用结果时，向用户展示：

- 建议标题和文种
- 建议大纲，每个一级标题附简短写作目的和要点
- 后续搜索建议，只展示检索方向和用途，不展示脚本参数

用户可见确认内容必须使用清晰的 Markdown 分节和列表，不得压缩成一个长段落；展示格式与确认话术模板见 `reference/search_guide.md` 第一节。

用户确认或修改后，再进入深知搜索方案设计。大纲接口返回的 `search_suggestions` 只能作为搜索方案设计输入，必须转化为用户可理解的搜索项后再次确认；不得直接当作已经检索到的素材。

大纲接口未返回可用结果、超时、权限异常或服务异常时：

- 不阻断写作流程。
- 不向用户展示“未获取到可用范文大纲”之类的中间状态，除非用户明确询问。
- 不让模型自行生成替代大纲，也不进入“大纲确认”环节。
- 直接按原流程继续：需要搜索时设计搜索方案并等待用户确认；不需要搜索时按文种标准直接写作或生成 Word。

## 搜索规则

需要搜索时，严格遵循 `reference/search_policy.md`：

1. 设计搜索方案，覆盖政策依据、数据支撑、参考案例等必要维度；不要把"表述参考型"设计为独立搜索项。**写法参考不作为方案阶段的独立检索项**——统一放到检索完成后的素材分类阶段处理（见第 5 条"参考范文"）：优先从**已召回的官方成文**里找同类范文取全文（参考范文召回）；确无同类成文时，再以"**文风体例参考**"（webSearch 全网搜写法）兜底。
2. query 从任务对象出发构造（句式「对象（含地域、时间限定）的关注方向」），**不列举具体信息需求（不写括号清单）**、禁止类目关键词堆砌——列举会把检索面收窄到几个词上、牺牲广度与召回质量；分路保留、各路只是关注方向不同（政策路写「…政策」、数据路写「…发展情况」、案例路写「…做法」）。方案向用户展示每条 query 原文，确认即执行（详见 `reference/search_policy.md` Query 生成原则）。
3. 向用户展示搜索方案并停止，等待用户确认或调整。
4. 用户确认搜索方案后执行检索，**两阶段（3.7.5 起）——首轮深度搜索广度召回，补搜可信搜索精准补强**：
   - **阶段一·首轮深度搜索召回（3 路按素材类型）**：每路调用 `python3 <skillDir>/scripts/deep_query.py "<query>" --area <地域> --json-only --output deep_<路名>.json`（需 API Key）。query 用第 2 条句式（对象+关注方向，**不限定到具体文件名/文号**），areas 默认单地域（多地比较场景可逗号分隔传多地域，服务端自动拆子查询）。每路返回**立即完整落盘**并 `json.load` 校验，再运行 `python3 <skillDir>/scripts/deep_convert.py <文件> --area 地域 --purpose "<搜索目的>"` 转换为与 `--clean` 同构产物（`result_deep_<路名>.json`）。3 路默认并行（单批 ≤4 路）。
   - **阶段二·可信搜索补搜（缺口驱动）**：深度搜索**缺独立"文号"字段**（政策文号在段落内容中）——政策依据型**必补搜**（补搜产出 policyFiles，正文引用政策文号靠其匹配）；数据/案例按研究资料口径表缺口（未给出/未确认/多口径未裁决）决定是否补搜。补搜走 `python3 <skillDir>/scripts/dkag_search.py`（参数见搜索命令节）。补搜产物与深度搜索产物合并（`merge_search_results.py`）后进入素材分类。补搜失败单独串行重试一次，不整批重发。
   - **即时落盘（并行前提）**：每路返回后立即把完整 JSON 原样落盘并校验通过才发下一路；禁止"先攒在对话里、整批完成后统一落盘"——宿主对工具结果有清理机制，延迟落盘会"过期"丢失，路数越多越容易整批拿不到结果。
   - **深度搜索失败回退（3.7.5 修复）**：阶段一某一路深度搜索失败（接口报错/超时/返回 0 篇/JSON 非法，已串行重试一次仍失败）时，**仅该路回退用可信搜索 `dkag_search.py` 重新搜索该路素材类型**（query 仍按该路关注方向构造，产出视为该路召回进入合并），**其他路不受影响、不整批回退**。回退后该路产物与未回退路产物一并 `merge_search_results.py` 合并，进入素材分类。所有路都失败才如实告知用户并暂停等待确认。
   - 任一路额度用尽（`quota_exhausted=true`）整批停止，按额度规则处理；平台或接口明显限流（多路同时报错）时回退为逐路串行执行。
   - **参考范文召回（执行时机：第 5 条素材分类时逐篇判断；取全文须先经用户同意）**：判断时发现有文章**与用户要写的材料高度相似**（同文种、同场景、体例接近）、对其结构或论述逻辑有明显参考价值时，按 `reference/search_guide.md` 第四节先向用户推荐并**取得明确同意**——**用户未回复、未同意或拒绝时，不得调用 `--full`**，按无参考范文继续写作。同意后用 `python3 <skillDir>/scripts/dkag_search.py "<目标范文完整标题>" --full --output ref_full_<任务>.json` 召回，再用 `python3 <skillDir>/scripts/extract_reference.py` 按标题匹配**只提取目标那一篇**全文落盘为 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/参考范文_<任务>.md`（`--full` 全量返回含全部命中篇，不得作为参考范文留存）。**它与范文大纲并存、互不替代**：大纲给通用结构建议，参考范文给同类成文的实际写法。参考范文只学结构与表达、不照搬内容，**不进溯源核验报告**。`--full` 仅用于此场景，不得用于补全政策全文。**注意其覆盖边界（2026-09-29 实测）**：`--full` 只是在可信搜索**命中集内**返回全文，**不扩大召回集**，而该接口对**地方人大公报、地方政府公报类站点**覆盖有限（上海实测：来源上海人大的目标范文，以完整标题召回 31 篇命中集里 0 篇来自该站，同一篇在深度搜索里却可召回）——**地方公文类范文取不到全文属接口覆盖问题，不是标题没写对**；此时按无参考范文继续写作——**能搜到就用、搜不到就跳过，不要重试**（换 query 也扩大不了命中集）。
5. 将召回素材分为四类：政策依据型、数据支撑型、参考案例型、表述参考型；表述参考型只能从已召回材料中归纳，不单独搜索。**写法参考（素材分类时必做判断，主备两级）**：逐篇归类时**必须**检查是否有**与目标材料同文种、同场景、体例接近**的成文（尤其同地域、同主题的报告/总结/调研），并在素材分类输出中**写明结论**（见 `reference/search_guide.md` 第二节分类模板的"写法参考"必填项）：

- **有 → 参考范文召回（首选）**：列出标题与推荐理由，按第 4 条子项与 `reference/search_guide.md` 第四节向用户推荐（**须经用户同意**方可取全文），取该篇**全文**作写法参考。
- **无 → 文风体例参考兜底**：明写"未发现高度相似的成文范文"，再按 `reference/search_guide.md` 第六节以 **webSearch 搜同类文种的结构写法**兜底（须经用户确认后执行）——只学写法、不作依据、不进溯源报告，搜到什么算什么，不追求全文。

两者是**同一目的的主备关系**（都只为学"怎么写"），不是并列的两种搜索：**先查官方库有没有同类成文，没有再用全网兜底**。2026-09-28 两次实测均因把二者当成并列/互斥关系而未触发（一次跳过 webSearch 未做、一次开了 webSearch 也未做）。**素材清单先行（3.7.5 修复，强制顺序）**：素材分类必须基于两阶段合并产物 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/merged_all.json`（或等价合并文件）的**全量 articles 逐篇归类**，分类结果与合并产物一一对应、不得遗漏。**分类完成后必须把“选中的素材清单”落盘为 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/materials_<任务>.json`**——顶层结构固定为 `{"task": "<任务名>", "doc_type": "<文种>", "selected": [ {…}, … ]}`（**选中数组必须挂在顶层 `selected` 键下**，`build_trace_json.py` 按它读取，写成别的键会报"素材清单 selected 为空"；完整示例可运行 `python3 <skillDir>/scripts/build_trace_json.py --sample <合并产物JSON>` 查看），每篇含 `type`/`标题`/`源网址`/`段落`/`发布日期可信度`/`快照链接` 标准字段，该清单是后续写作与溯源 JSON 的唯一材料依据。**禁止手工挑拣后直接写正文、禁止写完正文再反查用了哪些素材、禁止手写脚本/手写 JSON 定义 materials**（2026-09-24 WorkBuddy 实测：模型写完正文才反查材料、手写 543 行脚本挑拣，写作时引用情况无保障，溯源核验沦为"事后圆场"）。按 `reference/material_usage_guidance.md` 逐篇映射标准字段，字段缺失的如实留空并在核验报告中标注，不得凭记忆补造。
6. 按 `reference/material_usage_guidance.md` 判断清单内各类材料的正文用途，区分依据、数据、案例和表述参考。
7. 严禁将外省政策作为本省政策依据；政策依据与数据信息严禁使用自由搜索（webSearch）召回的非官方材料，非官方范文与本地 `standards/` 文种标准冲突时以本地标准为准。
8. 对政策依据、数据支撑、参考案例做充分性自检；研究资料的口径表/纠错记录出现信息缺口（未给出、未确认、多口径未裁决）必须触发补搜，补搜以关键事实闭环为目标、不设次数上限，在已确认方案边界内自动执行并记入研究资料；越界（新地域、换通道）或仍未闭环时停下向用户确认。
9. **用户确认素材清单后，再基于该清单写作正文**（3.7.5 修复，强制顺序）：正文按 `material_usage_guidance.md` 逐条引用清单材料，**写作时每处引用即标注 `[n]` 角标，n 对应素材清单序号**（先确认清单、边写边标，**禁止写完正文再反查/补标角标**）。正式写作任务不得把正文初稿作为聊天消息发出，直接生成 Word（执行过搜索时另附 HTML 溯源核验报告）。
10. 执行过搜索时，正式公文正文不再内嵌来源角标、知识专库链接或溯源卡片；必须另行生成 `标题_溯源核验报告.html`，将完整正文写入 HTML，并把正文中的 `[1]`/`【1】`角标变成可点击的来源跳转。报告首屏展示核验报告单（依据溯源、引用对应、材料新旧、材料构成、交付前检查）与过程回顾条；正文中每处依据在句后挂引文胶囊（同段同一材料只保留一次），点击胶囊可展开标题链（文章 › 章 › 节面包屑）、原文摘录与查看全文链接；来源文章按段落分块、各段带自己的标题链，政策文件显示发文字号（接口 policyFiles 匹配）；全部召回材料在知识专库视图按检索分组展示。生成时脚本自动检测原文链接可达性（含软 404 嗅探），失效链接改用接口存档快照（screenShotPath）回看。凡通过深知可信搜索召回并写入正文的依据，默认按已完成可信检索和可溯源处理，不得使用“建议核对”“需人工核验”等削弱可信度的措辞。
11. 溯源核验报告必须按 `reference/search_guide.md` 的固定流程生成：**用 `scripts/build_trace_json.py` 从"素材清单 + 正文（带角标）"装配溯源 JSON 到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/标题_溯源核验报告.json`**（3.7.5 修复：materials 按正文角标序对应素材清单、recalled_materials 自动取清单未引用部分 + 合并产物未选部分、self_check 骨架待填），再调用 `python3 <skillDir>/scripts/source_note_html.py ...` 输出 HTML。**字段契约（3.7.5 修复）**：溯源 JSON 必须包含 `document_content`（带 `[n]` 角标）、`materials`（全量引用材料，含标准字段）、`recalled_materials`（全部未引用召回材料，不得留空）、`self_check`（五项检查结果如实写入，**每项值写 `"通过：<说明>"` 或 `"未通过：<说明>"` 字符串**——渲染器按字符串解析，写成 dict 会导致核验单五项"未记录"，2026-09-24 实测）；生成 HTML 前必须运行 `python3 <skillDir>/scripts/check_materials.py <溯源JSON> <合并产物JSON>` 校验（材料来源可回溯、字段完整、角标一一对应、recalled 非空），**校验通过后才允许调用渲染脚本**。`document_content` 必须在关键结论后标注 `[1]`、`[2]` 等角标并逐条对应 `materials`——脚本会校验，正文无角标时拒绝生成并报错，必须修正 JSON 后重跑，不得省略角标直接交付。不得由模型手写完整 HTML，不得自行拼接 `<a>`、`onclick`、按钮、卡片或页面样式。
12. 整理 `materials` 时，凡来自深知可信搜索的材料，必须将原始结果中的 `源网址` 原样写入 `source_url`；不得只写规范化后的文章标题，再依赖标题反查网址。若接口未返回 `源网址`，该材料不显示原文链接；不得猜测、补造或用搜索接口地址代替。

搜索异常处理：

- 如搜索脚本返回 `error=true`、接口异常、网络异常、权限异常，或关键搜索项返回空结果，立即停止后续写作。
- **额度或余额用尽（`quota_exhausted=true`）：禁止任何形式的重试**——不得重发同一搜索、不得换 query 再试、不得当作普通网络异常反复调用。立即向用户说明：积分或账户余额已用完，可到 MaaS 管理平台 `https://platform.dknowc.cn/auth/#/login` 完成实名认证再领 10 万积分或充值，处理后说一声即可继续。在用户确认已处理前，不得再次调用深知搜索；可按用户意愿改为基于已有材料继续写作。
- 向用户说明异常发生在哪个搜索项、错误信息或空结果情况，以及已经成功/失败的搜索项。
- 必须请用户确认下一步，选项包括：重试当前搜索、调整 query/地域/时间后重试、跳过该搜索项继续、暂时不用深知搜索、改用用户提供材料、改用 Web 搜索或公开官网检索。
- 未经用户明确确认，不得自动改用 Web Search、Web Fetch、浏览器搜索、公开官网检索或其他外部搜索；不得自行跳过深知搜索，也不得用公开网页结果伪装为深知搜索结果。

外部搜索禁用规则：本 Skill 不得主动调用 Web Search/Web Fetch/浏览器搜索；仅当用户明确说"改用 Web 搜索""用公开官网检索"时才允许，且使用前必须说明这些材料不是深知搜索结果、不能作为深知搜索素材来源；从深知搜索返回链接取全文也必须先经用户确认。外部搜索结果不得伪装为深知搜索结果。


搜索方案要素与展示边界（地域/内容/素材类型/使用边界，禁止出现脚本参数）见 `reference/search_policy.md` 与 `reference/search_guide.md` 第三节。


搜索方案确认话术：

```text
我建议先按下面方案检索，请确认是否执行，或告诉我需要增删哪些搜索项。
```

搜索命令（**统一走脚本通道**，需 API Key）：

**首轮深度搜索召回（3 路按素材类型）：**

```bash
python3 <skillDir>/scripts/deep_query.py "搜索词" --area 地域 --json-only --output deep_路名.json
python3 <skillDir>/scripts/deep_convert.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/deep_路名.json --area 地域 --purpose "搜索目的"
```

**补搜可信搜索（缺口驱动，政策依据型必补搜）：**

```bash
python3 <skillDir>/scripts/dkag_search.py "搜索词" --area 地域 --time 时间 --purpose "搜索目的" --clean --output result_地域.json
```

宿主环境（WorkBuddy、豆包等）当前目录不在 skill 安装目录时，以上脚本一律改用 skill 安装目录的绝对路径调用（`cd` 不跨调用持久化，不要依赖相对路径）。

未指定目录的搜索结果文件会保存到 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/`；合并搜索结果时也只能读取和写入本 Skill 的 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/`、`dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`、`dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/` 工作目录。

`--time` 只用于 `2025年`、`2025年08月`、`2025年08月15日` 这类单个明确时间点；不要传 `2023-2025` 这类范围。没有明确时间点时省略 `--time`。

本 skill 的搜索脚本固定使用 `segmentCount=2`，每篇材料最多返回 2 个相关段落；同时固定 `simplified=false`，避免写作场景下过度剔除材料。调用时不要额外传段落数量或精简参数。

合并命令：

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
- 方案与总结类：`reference/standards/25_plan.md`（方案/实施方案/建设方案）、`reference/standards/26_summary.md`（工作总结/工作要点）
- 讲话与致辞：`reference/standards/27_speech.md`（讲话稿/致辞/述职）
- 制度与办法：`reference/standards/28_rules.md`（管理办法/制度/规定）
- 研究类长篇：`reference/standards/29_research.md`（调研报告）、`reference/standards/30_feasibility.md`（可研报告）、`reference/standards/31_review_material.md`（审查材料）、`reference/standards/32_ai_compute.md`
- 文种未在以上清单中明确时，先读 `reference/standards/00_index.md` 按索引定位；全部文种标准共 34 个，索引与文件一一对应。

写作时正文不加引用标记。执行过搜索时，正文只写正式内容，不在文末追加素材使用情况或知识专库链接；素材溯源说明作为单独 HTML 辅助文件生成，格式见 `reference/search_guide.md`。

正文一律使用中文全角标点；引号必须使用中文全角引号——双引号用 U+201C “ 与 U+201D ”，单引号用 U+2018 ‘ 与 U+2019 ’；禁止英文半角引号 U+0022 与 U+0027。生成正文时直接写全角引号，不依赖排版脚本转换；定稿检查时按 `reference/anti_ai_patterns.md` 核对。

所有正式写作、改写、润色、压缩任务，生成正文前必须按 `reference/fact_discipline.md` 约束事实边界：材料已给事实保持原状态强度，材料未谈事项省略，占位符不得残留，改稿以最新版底稿为主线，不得为显得完整而补写责任、时限、下一步等材料没有的内容。

对工作总结、工作要点、实施方案、专项整治方案、会议讲话、研讨发言、汇报材料等长篇材料，生成正文前还应读取 `reference/standards/99_expressions.md`，内部完成结构选择、小标题策略和段落功能分配。该文件只提供通用写作方法，不得机械套用参考句式，也不得用表达增强替代事实、措施和责任。长篇材料定稿前按 `reference/anti_ai_patterns.md` 做语言复核，排查旁白句、思考泄露、二元包装、口号收尾、空泛词和格式噪点。

执行过搜索时，生成正文前必须读取 `reference/material_usage_guidance.md`。它只提供材料使用原则，不强制套用固定结构；写作时应优先满足用户任务和文种要求，再把政策、数据、案例材料转化为支撑观点的内容。

研究型与综合长篇文种（调研报告、政策/产业研究、综合性总结与汇报材料），素材确认后、动笔前必须按 `reference/research_notes.md` 生成研究资料（素材消化为带角标的事实底稿，保存 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/标题_研究资料.md`，角标与溯源 JSON 的 materials 编号一致），正文基于研究资料写作；短公文不启用。写作以深度思考、深度推理组织"事实—问题—原因—对策"链，按素材充分度展开、分析密度优先、禁止注水。

执行过搜索时，全部召回材料（含未引用）进入溯源核验报告材料面板，不在报告中生成知识专库链接区。

高风险事实处理：

- 政策名称、文号、发布日期、精确数字、排名、占比、金额、全国首个/领先/唯一等表述，只有来源明确且口径一致时才写成确定结论。
- 超出用户题目时间范围的信息，只能作为背景、延续动态或趋势参考，不得混作当期政策、当期成效或已经完成事项。
- 无法通过深知可信搜索确认的具体数据和文号，不写入正文；如确有参考价值，只能改用概括表述。溯源核验报告只展示已通过深知可信搜索完成召回、来源定位和溯源核验的材料，不再列“需人工核验信息”。
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

成稿快速自检（每次生成 Word 前默认执行，逐项过、不合格先自查修正再交付，不向用户输出自检过程）：

1. **事实有据**：政策名、文号、数字、日期要么来自用户材料或素材库，要么来自深知搜索结果；凭印象写的高风险表述（全国首个/领先/唯一等）删除或降级为概括表述。
2. **结构完整**：文种必需要素齐全（标题、主送、正文、结语、落款、成文日期；请示有请批事项和请批语，报告不带请批），无缺失章节；联系人电话须写入正文相关事项段，结尾不得出现独立的联系人电话段（上行文必须写明、平行文可选、下行文不强制，见各文种标准）。
3. **无占位残留**：正文无 XX单位、XXXX万元、〔待补充〕、YYYY年MM月DD日 等未处理占位（用户明确要求模板稿除外）。
4. **无 AI 味**：无旁白句（"本文将…"）、思考泄露（"作为AI…"）、口号式收尾（"提供有力支撑"）、Markdown 残留（**加粗**/###/代码块）；引号一律中文全角。可选运行 `python3 <skillDir>/scripts/prose_lint.py <草稿> --format` 辅助确认，命中项结合上下文判断处理，不作机械清洗。
5. **格式合规**：表格有表题且连续编号、表题非标题语法；落款日期格式正确；字数符合用户要求（有明确上限时先自检字数）。

自检在生成 Word 的临时正文文件上完成，修正后重新写入再调用排版脚本；不得跳过自检直接交付，也不得把自检结果当作长篇审稿报告发给用户。

## 审查规则

以下情况必须执行审查：

- 执行过搜索
- 请示、复函、政策依据型报告
- 管理办法、实施方案、调研报告
- 工作总结、工作要点、专项整治方案、会议讲话、研讨发言、汇报材料等长篇材料
- 用户要求正式 Word 或红头文件
- 用户明确要求检查、审核、把关

审查清单见 `reference/review_checklist.md`。发现问题时先列问题，再说明修改建议。用户上传已有 Word 时，格式审查和内容审查可以分别执行，也可以组合执行；执行内容审查并使用搜索时，必须生成溯源核验报告 HTML。

语言与格式审查时，可按 `reference/anti_ai_patterns.md` 检查旁白句、思考泄露、二元包装、口号收尾、空泛词和格式噪点；需要时可选运行 `python3 <skillDir>/scripts/prose_lint.py <草稿文件> --format --structure` 做语言质检。脚本只提示语言、格式和重复风险，不检查文种要素完整性，不自动改写；不得把脚本结果作为不加判断的硬性清洗命令。

## Word 输出

首次使用或用户要求检查环境时：

```bash
python3 <skillDir>/scripts/initialize.py
```

如果 `python3` 不可运行，或初始化结果显示 `ready=false`、`python_docx=false`、`requests=false`，必须先暂停（依赖缺失处理见"工作原则"）。API Key 按需前置：不需要搜索的任务即使未配置 Key 也可正常生成 Word；需要搜索的任务按"启动初始化"的注册流程处理。

用户明确授权保存常用设置时，才执行：

```bash
python3 <skillDir>/scripts/initialize.py --organization "用户提供的单位" --doc-prefix "用户提供的前缀" --region "用户提供的地域" --save
```

需要生成 Word 时，正文必须使用 `reference/output_guide.md` 支持的 Markdown 格式。

普通 Word：

```bash
python3 <skillDir>/scripts/format_document.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/official_doc_content.txt
```

调用前先把正文写入本 Skill 工作目录下的 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/` 临时正文文件。默认保存到 `config/format.json` 的 `output.dir`，且输出只能位于 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`；脚本默认从正文标题生成正式文件名，并在同名文件已存在时追加 `_v1`、`_v2`。如用户明确要求保存文件名，可传入 `--output 文件名.docx`。只有一句话以内的极短文本才允许使用 `--text`；多行正文不得直接通过命令行参数传入，避免换行被破坏后整篇文档变成一个段落。

红头 Word：

```bash
python3 <skillDir>/scripts/template_generator.py 通知 --input 普通Word文件路径 --org "发文机关" --doc-number "发文字号"
```

红头脚本只能在用户明确要求红头时调用。用户只要求“生成 Word”“正式 Word”“排版文件”时，不调用红头脚本。

当前版本不支持自动生成 PDF，也不提供 PDF 转换命令。用户明确要求 PDF 时，生成正式 `.docx` 或红头 `.docx` 后，提示用户使用本机 Word/WPS 的“另存为 PDF”或“导出 PDF”功能完成转换；不得声称已生成 PDF。

生成成功后，优先返回正式 `.docx` 文件路径和一句简短说明。执行过搜索并生成溯源核验报告 HTML 时，可同时返回辅助文件路径，但必须明确主文件是正式成稿、溯源核验报告不是正文附件。不要发送 Markdown 草稿、正文初稿、完整正文或中间文件路径。

**宿主环境交付（WorkBuddy、豆包）：** 产出物默认落在 skill 安装目录，宿主通常只展示其工作区文件。**每次交付前一律执行 `（dsh：无需交付复制） <产出物路径...>`**（不要自行判断是否宿主环境，判断不可靠），按返回 JSON 处理：`copied=true` 向用户展示 delivered 路径（`skipped=identical` 表示目标已有同一份文件；`renamed=true` 表示目标已有同名不同内容的文件，本次另存为"名字 (2)"）；`need_dest=true` 必须补 `--dest <宿主工作区>` 重跑，此前不得把 skill 内部路径当交付路径发给用户。脚本按宿主身份选择对应工作区：**WorkBuddy → `~/WorkBuddy/<时间戳工作区>/outputs/`，豆包 → `~/DoubaoWork/chats/<日期>/<会话>/`（3.7.5 简化决策：仅这两个宿主有明确工作区才复制，其余宿主不做猜测）**。**宿主未识别（非 WorkBuddy / 豆包）时不复制，交付物保留在 skill 输出目录**，向用户展示 skill output 路径。不得为省事手工把产物复制到 `~/WorkBuddy` 等工作区：2026-09-21 豆包任务曾因按"最新 WorkBuddy 工作区"兜底交付，把产物写进用户当天在 WorkBuddy 的测试工作区并同名覆盖其交付物。

如需先把正文落为临时 Markdown 文件供脚本读取，必须在同一工作流中继续生成 `.docx`；不得停在 Markdown 草稿，也不得把 Markdown 文件作为阶段性成果发给用户。只有用户明确要求“先看草稿”“先发 Markdown”“不要生成 Word”时，才可以交付 Markdown 或正文预览。

对“写一份/起草/生成/整理/形成/润色/改写……”等所有正式写作任务，默认理解为需要 Word 正式文件交付（执行过搜索时另附 HTML 溯源核验报告）；不得因为用户未写“Word”就先把正文粘贴到聊天窗口。简单会议通知、内部事务通知、短改写等任务同样默认交付 Word。
