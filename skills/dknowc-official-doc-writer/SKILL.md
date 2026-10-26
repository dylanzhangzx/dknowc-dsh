---
name: "深知公文写作"
slug: "dknowc-official-doc-writer-dsh"
display_name: "深知公文写作"
display_name_en: "dknowc official doc writer"
description: "深知公文写作，是面向单位办公室、综合岗、文秘、材料岗和企事业单位用户的正式材料写作助手。核心用于公文写作、正式文书起草、汇报材料整理、讲话稿撰写、工作总结和方案报告生成，帮助用户把零散想法、会议记录、工作素材、调研资料或初稿，整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿。支持通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、方案、总结、管理办法、汇报材料、发言稿、讲话稿、调研报告、经验材料等常见文种和工作材料。可进行起草、改写、润色、扩写、压缩、标题优化、结构调整、语气统一和内容审查。涉及政策依据、数据支撑、标准规范或案例参考时，可调用深知可信搜索获取素材，并生成含正文、溯源核验报告与知识专库的产出物，帮助用户写得有依据、能复核、可交付。正式公文（通知、请示、报告等 15 种法定文种）可生成 Word 文档，用户明确需要时也可生成红头文件。"
description_zh: "深知公文写作，是由北京彩智科技有限公司旗下“深知可信智能”提供的正式材料写作助手，准确、规范地完成企事业单位与政府机关等场景下的文档编写需求，所有依据或参考材料，都全程可溯源到权威部门发布的规范性文件。本技能用于公文写作、正式文书起草、汇报材料整理、讲话稿撰写、工作总结和方案报告生成，帮助用户把零散想法、会议记录、工作素材、调研资料或初稿整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿。本技能还能严格按公文相关国家标准，支持通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、方案、总结、管理办法、汇报材料、发言稿、讲话稿、调研报告、经验材料等常见文种和工作材料。依托深知可信搜索，获取准确有效的法规政策依据、行业信息与数据、标准规范和案例参考，并生成含正文、溯源核验报告与知识专库的产出物，帮助用户写得有依据、能复核、可交付。正式公文（15 种法定文种）可生成 Word 文档；并可按用户明确要求自动生成红头文件。"
description_en: "dknowc official doc writer is a formal-document writing Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It helps users draft, rewrite, polish, review and generate structured workplace documents, including official documents, formal letters, reports, meeting minutes, summaries, plans, speeches, research reports and other business materials. When evidence, data, standards or reference cases are needed, it can use dknowc Trusted Search to retrieve traceable materials from authoritative sources and produce a deliverable containing the formal content, a source-verification report and a knowledge-library view. Word documents are generated for the 15 statutory official-document types, and red-head document formatting is supported when explicitly requested by the user."
category: "office-efficiency"
version: "3.9.2-dsh"
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
    - "生成的产出物 HTML（正文 / 溯源核验报告 / 知识专库 三页）"
    - "搜索结果中间文件"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知公文写作

深知公文写作由北京彩智科技有限公司旗下“深知可信智能”提供，是面向正式材料写作场景的组合型 Agent Skill。它不是固定从头到尾执行的演示脚本，而是根据任务选择最小必要流程，帮助用户完成公文写作、正式文书起草、汇报材料整理、讲话稿撰写、总结方案生成、素材检索、产出物生成（正文 / 溯源核验报告 / 知识专库）和公文 Word 交付。

> **dsh Key 机制**：dsh 清理名字含 KEY 的隐式环境变量，但**专用配置文件读取不受影响**——注册成功后 Key 写入 `~/.config/dknowc/api_key`，本会话检索/大纲脚本立即可用（无需重启 dsh）。仅 dsh 捆绑的 MCP 兜底工具需重启后加载新 Key。
>
> **dsh 检索通道**：检索与范文大纲一律走脚本直连（全量结构化返回）；dsh 捆绑的 MCP 工具（trusted_search / deep_query / doc_outline）返回为精简视图，仅作应急兜底（经 `mcp_direct.py` + `adapt_mcp_result.py`，含 outline 模式），不据此生成正式溯源核验报告。

## 权限说明

本 Skill 会访问 `https://open.dknowc.cn/` 用于公文范文大纲、深知可信搜索和产出物整理；访问 `https://platform.dknowc.cn/auth/#/login` 用于 MaaS 手机号验证码注册、API Key 获取和管理平台地址说明。运行过程中会读取本 Skill 的规则、标准、配置和参考资料文件，并在本地写入初始化状态文件、用户授权保存的写作偏好、生成的 Word 文档、产出物 HTML 和搜索结果中间文件。MaaS 注册取 Key 成功后，会把 `DKNOWC_API_KEY` 写入本机 Key 专用配置文件（`~/.config/dknowc/api_key`，纯文本一行 Key、600 权限，不写 `~/.zshrc`）；脚本读取顺序为进程环境变量优先、缺失时自动读取该文件，历史 `~/.zshrc` 中的 Key 块仅作迁移期兜底。Skill 包内不包含真实 API Key，API Key 必须通过环境变量 `DKNOWC_API_KEY` 注入或配置文件持久化，不得硬编码，不得写入公开包，不得在对话中展示完整内容。

## 设计模式

本 Skill 组合使用五种模式：

- Tool Wrapper：封装公文范文大纲、深知搜索、普通 Word 排版、红头文件生成和产出物 HTML（正文 / 溯源核验报告 / 知识专库 三页）生成。
- Generator：根据文种标准、用户材料和素材指引生成公文正文。
- Reviewer：按审查清单检查格式、逻辑、素材来源和公文风险。
- Inversion：复杂任务或关键信息缺失时，先向用户追问。
- Pipeline：仅在政策依据型、长篇复杂材料、红头交付等场景执行带检查点的严格流程。

## 启动初始化

被调用后先运行一次 `python3 <skillDir>/scripts/initialize.py`（不要求用户提供单位或个人信息，不上传检测结果）。初始化不是 API Key 硬性门禁：

- **不需要搜索的任务**：只要 `python3`、`python_docx`、`requests` 就绪即可继续，不要求配置 Key、不引导注册。
- **需要搜索但未配置**（`api_key_configured=false` / `search_ready=false`）：暂停原任务，按 `reference/initialization.md` 引导开通；**引导前不得输出任何“已核实/已查到”类政策内容**，先讲价值再提手机号。
- 依赖缺失、Key 判定、注册流程、验证码与密钥安全红线：完整规则见 `reference/initialization.md`；话术见 `reference/onboarding_scripts.md`。

## 任务路由

先判断任务类型与复杂度；详细规则见 `reference/task_router.md`。

| 任务 | 路径 |
| --- | --- |
| 简单会议通知、内部事务通知 | 读对应标准直接完成；命中公文范式出 Word，执行过搜索另出产出物 HTML |
| 普通通知、函、短报告 | 必要时追问少量关键信息后完成 |
| 请示、复函、政策依据型报告 | 通常需要搜索，按工作流执行 |
| 管理办法、实施方案、调研报告、工作总结、产业研究 | 先大纲/搜索方案，再执行；多会出产出物 HTML |
| 基于已交付产物改稿 | 按 `reference/revision_workflow.md`，默认不重复搜索，出 `_v1`/`_v2` |
| 要求检查/审核/把关 | Reviewer 模式，先出问题清单（`reference/review_checklist.md`） |
| 明确要求红头 | 先生成普通 Word，再调用红头脚本（用户明确要求才调用） |
| 明确要求 PDF | 只出 Word，说明当前版本不自动转 PDF，建议用 Word/WPS 导出 |

## 工作流

按任务取最小必要流程。正式写作的完整顺序如下，每步标注的“必读”文件不可跳过。

0. **范文大纲**（正式写作，可跳过短通知等）：调用 `scripts/outline_reference.py`；返回可用则展示“建议大纲 + 搜索建议”等用户确认；失败静默降级、不臆造替代大纲。规则见 `reference/outline_rules.md`。
1. **搜索方案（G1）**：固定 3 个方向——政策依据 / 数据支撑 / 参考案例，每个方向 **1 条启动 query**（地域层级写在 query 内，不拆成独立方案项）；向用户展示 3 条 query 原文并停止等待确认；确认前不得检索。补搜不预先列方案，按缺口自动执行。规则见 `reference/search_policy.md`。
2. **检索（两阶段）**：深度搜索 3 路广度召回（返回立即落盘并校验，再 `deep_convert.py` 转换）；补搜按素材类型**单值分路**——政策依据路 `--search-type policy`，数据/案例路 `govSite`，**禁止混传**；同一查询需要两类来源时并行调用后合并。**同一方向的深搜与补搜共用同一个 `--purpose`**，保证报告按 3 个方案项分组。命令、参数、失败重试与额度规则见 `reference/search_policy.md` 执行命令/执行节奏/异常处理节。
3. **素材清单（G2）**：基于合并产物**全量逐篇**分类，把选中清单落盘 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/materials_<任务>.json`（顶层 `selected` 键）；禁止手工挑拣、写完正文再反查、手写 materials。分类口径与写法参考判断见 `reference/materials_pipeline.md`。
4. **研究资料（G3，研究型/综合长篇）**：分类自检时生成初版（口径表缺口驱动补搜），用户确认素材清单后定稿，正文基于定稿写作；短公文不启用。规则见 `reference/materials_pipeline.md` 与 `reference/research_notes.md`。
5. **写作**：按文种读取 `reference/standards/*.md`；事实边界、标点、篇幅规则（只服从用户明确要求）、高风险表述、表格规则与成稿自检见 `reference/writing_rules.md`；材料进入正文见 `reference/material_usage_guidance.md`。
6. **产出物与交付**：命中 15 种法定公文 → 生成 Word；执行过搜索 → 生成产出物 HTML（溯源 JSON 装配 → `check_materials.py` 校验 → `source_note_html.py` 渲染）；产物直接生成在会话工作区（dsh 以工作区为文件视图），交付时直接展示脚本打印的路径。完整规则见 `reference/output_guide.md`。
7. **审查**：按触发条件读 `reference/review_checklist.md`；语言复核按 `reference/anti_ai_patterns.md`，可选 `scripts/prose_lint.py`。

## 硬约束（Gate，违反即停）

- **G1**：搜索方案未经用户确认，不得检索。
- **G2**：素材清单必须先落盘，正文只能基于清单写；禁止手挑素材、正文写完后反查材料、手写 materials。
- **G3**：研究型文种缺研究资料文件时（`check_materials.py` 拦截），不得生成正文与产出物 HTML。
- **G4**：正文 `[n]` 角标与素材清单一一对应；`check_materials.py` 通过后才允许渲染 HTML。
- **G5**：额度用尽（`quota_exhausted=true`）或检索失败：停止并如实告知，等用户确认；**禁止任何重试**，禁止擅自改用其他搜索方式。
- **G6**：正文文号只认材料清单 `发文字号` 字段；字段为空时只写文件全称，不得从段落正文提取（`check_materials.py` 拦截）。
- **G7**：篇幅只服从用户明确要求或模板规定。用户未提字数时，不设默认下限，按素材充分度自然收束，不得为凑字数补写背景、表态或口号；用户提出字数要求时，按用户区间校验，低于下限先补已召回事实、仍不足则交短稿并说明缺口，高于上限先压缩重复与铺垫，必保内容不得删（`check_materials.py` 仅在用户明确要求时校验）。

其他禁止：

- 不得用 Web Search / Web Fetch / 浏览器搜索替代深知搜索（用户明确要求除外，且必须声明这些材料不是深知检索结果）。
- 严禁将外省政策作为本省政策依据；非官方网搜材料不得作为政策、数据依据。
- 不得由模型手写完整 HTML，不得自行拼接 `<a>`、`onclick`、按钮、卡片或页面样式。
- 不得把正文初稿、压缩版、Markdown 草稿发到对话；正式任务直接生成产物并只给路径与简短说明。带角标正文只保存在会话工作区产物目录 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/`，不得写入其他目录；交付与 `present_files` 只列最终 HTML / Word，Markdown 正文不复制、不展示。
- 不得补写未发生的调研方法（座谈、走访、台账查阅等）；附录、附表、填报表承诺必须兑现，不能只列名称。交付说明中的文号必须能在素材清单 `发文字号` 找到，正文因 G6 删除的文号不得在说明中保留。
- 事实陈述只来自用户材料和可信搜索结果；模型假设只能用于结构、分析框架和建议方向，涉及具体事实须标“待核实/初步判断”，不得写成确定事实。引用标准按 `reference/writing_rules.md` 的“标准引用四查”核对。
- 当前版本不生成 PDF；不得声称已生成 PDF。
- 不得向用户展示完整 API Key；验证码由用户本人输入，不代输、不转发。

## 参考资料索引

按任务条件只读命中文件，不预读全部。

| 场景 | 必读文件 |
| --- | --- |
| 启动、开通、注册、报错话术 | `reference/initialization.md`、`reference/onboarding_scripts.md` |
| 向用户说明搜索/展示样例 | `reference/search_intro.md`、`reference/sample_search_result.md`、`reference/sample_trace_report.html` |
| 任务路由、改稿轮 | `reference/task_router.md`、`reference/revision_workflow.md` |
| 范文大纲 | `reference/outline_rules.md` |
| 搜索方案、参数、命令、失败处理 | `reference/search_policy.md` |
| 素材分类模板、参考范文流程、产出物页面格式 | `reference/search_guide.md` |
| 素材分类、研究资料、溯源 JSON 契约 | `reference/materials_pipeline.md`、`reference/research_notes.md`、`reference/material_usage_guidance.md` |
| 正文写作、文种写法、事实边界、篇幅、自检 | `reference/writing_rules.md`、`reference/genre_writing_notes.md`、`reference/fact_discipline.md`、`reference/anti_ai_patterns.md`、`reference/standards/*.md` |
| Word / 产出物 HTML / 交付 | `reference/output_guide.md` |
| 审查 | `reference/review_checklist.md` |
| 素材库与写作偏好 | `reference/local_memory_guide.md`、`scripts/local_memory.py` |
| 全局工作原则（环境/交付纪律） | `reference/working_principles.md` |
| 语言质检（可选） | `scripts/prose_lint.py` |
| 检索与转换脚本 | `scripts/deep_query.py`、`scripts/deep_convert.py`、`scripts/dkag_search.py`、`scripts/merge_search_results.py`、`scripts/outline_reference.py`、`scripts/extract_reference.py` |
| 产出与交付脚本 | `scripts/build_trace_json.py`、`scripts/check_materials.py`、`scripts/source_note_html.py`、`scripts/format_document.py`、`scripts/template_generator.py`（dsh 无 `deliver_outputs.py`——产物已在会话工作区，无需交付复制） |

## 个人素材库与写作偏好

本 Skill 在本机维护个人素材库 `knowledge-base/` 与写作偏好 `config/writing_preferences.json`，只对当前用户生效、不上传；初始化结果 `local_memory` 返回数量，大于 0 时写作前先检索并应用。

- 保存或删除素材/偏好必须先经用户确认；一次性内容不保存。
- 素材库命中的材料按用户提供的材料对待：与当轮材料同优先级、高于搜索素材，仍须遵守 `reference/fact_discipline.md` 事实边界。
- 用户明示偏好优先于文种标准和默认排版（红头国标强制项除外，冲突时向用户说明）；与当轮要求冲突时当轮优先。
- 命令与完整规则（六类分类、沉淀时机、应用范围）见 `reference/local_memory_guide.md`。

## 工作原则（摘要）

- 简单短文本直接完成，不强制大纲、搜索、素材确认环节。
- 正式写作先大纲、再搜索；大纲失败不阻断、不臆造替代大纲。
- 任一关键步骤异常时暂停并向用户确认，不自行跳过搜索、改目标或继续出正式结果。
- 交付形态两个独立开关：命中 15 种法定公文 → Word；执行过搜索 → 产出物 HTML，可同时成立。只有用户明确要求“直接在对话里给正文 / 不要生成文件”时才在对话输出正文。
- 环境依赖、Word 排版、红头、版记、字体、PDF 与宿主交付细节见 `reference/working_principles.md` 与 `reference/output_guide.md`；启动与开通细节见 `reference/initialization.md`。
