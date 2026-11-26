---
name: "深知公文写作"
slug: "dknowc-official-doc-writer-dsh"
display_name: "深知公文写作"
display_name_en: "dknowc official doc writer"
description: "深知公文写作，是面向单位办公室、综合岗、文秘、材料岗和企事业单位用户的正式材料写作助手。核心用于公文写作、正式文书起草、汇报材料整理、讲话稿撰写、工作总结和方案报告生成，帮助用户把零散想法、会议记录、工作素材、调研资料或初稿，整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿。支持通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、方案、总结、管理办法、汇报材料、发言稿、讲话稿、调研报告、经验材料等常见文种和工作材料。可进行起草、改写、润色、扩写、压缩、标题优化、结构调整、语气统一和内容审查。涉及政策依据、数据支撑、标准规范或案例参考时，可调用深知可信搜索获取素材，并生成含正文、溯源核验报告与知识专库的产出物，帮助用户写得有依据、能复核、可交付。正式公文（通知、请示、报告等 15 种法定文种）可生成 Word 文档，用户明确需要时也可生成红头文件。"
description_zh: "深知公文写作，是由北京彩智科技有限公司旗下“深知可信智能”提供的正式材料写作助手，准确、规范地完成企事业单位与政府机关等场景下的文档编写需求，所有依据或参考材料，都全程可溯源到权威部门发布的规范性文件。本技能用于公文写作、正式文书起草、汇报材料整理、讲话稿撰写、工作总结和方案报告生成，帮助用户把零散想法、会议记录、工作素材、调研资料或初稿整理成结构清楚、表达稳妥、逻辑完整、可直接修改使用的正式文稿。本技能还能严格按公文相关国家标准，支持通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、方案、总结、管理办法、汇报材料、发言稿、讲话稿、调研报告、经验材料等常见文种和工作材料。依托深知可信搜索，获取准确有效的法规政策依据、行业信息与数据、标准规范和案例参考，并生成含正文、溯源核验报告与知识专库的产出物，帮助用户写得有依据、能复核、可交付。正式公文（15 种法定文种）可生成 Word 文档；并可按用户明确要求自动生成红头文件。"
description_en: "dknowc official doc writer is a formal-document writing Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It helps users draft, rewrite, polish, review and generate structured workplace documents, including official documents, formal letters, reports, meeting minutes, summaries, plans, speeches, research reports and other business materials. When evidence, data, standards or reference cases are needed, it can use dknowc Trusted Search to retrieve traceable materials from authoritative sources and produce a deliverable containing the formal content, a source-verification report and a knowledge-library view. Word documents are generated for the 15 statutory official-document types, and red-head document formatting is supported when explicitly requested by the user."
category: "office-efficiency"
version: "3.9.10-dsh"
author: "彩智科技"
permissions:
  network:
    - "https://open.dknowc.cn/"
    - "https://platform.dknowc.cn/"
    - "https://down.dknowc.cn/"
  local_read:
    - "本 Skill 的 reference、config、official-docs、knowledge-base 等规则、标准、配置、参考资料和个人素材库文件"
  local_write:
    - "本地初始化状态文件"
    - "本机 Key 专用配置文件（~/.config/dknowc/api_key）中的 DKNOWC_API_KEY"
    - "版本自检缓存（~/.config/dknowc/update_check_doc_writer.json）"
    - "用户明确授权保存的写作偏好"
    - "用户明确授权保存的个人素材库文件（knowledge-base/ 目录）"
    - "生成的 Word 文档"
    - "生成的产出物 HTML（正文 / 溯源核验报告 / 知识专库 三页）"
    - "搜索结果中间文件"
    - "用户同意升级后的本 Skill 安装目录就地替换与安装目录旁整目录备份 zip（scripts/update_skill.py）"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知公文写作

深知公文写作由北京彩智科技有限公司旗下“深知可信智能”提供，是面向正式材料写作场景的组合型 Agent Skill。它不是固定从头到尾执行的演示脚本，而是根据任务选择最小必要流程，帮助用户完成公文写作、正式文书起草、汇报材料整理、讲话稿撰写、总结方案生成、素材检索、产出物生成（正文 / 溯源核验报告 / 知识专库）和公文 Word 交付。

## 权限说明

本 Skill 会访问 `https://open.dknowc.cn/` 用于公文范文大纲、深知可信搜索和产出物整理；访问 `https://platform.dknowc.cn/auth/#/login` 用于 MaaS 手机号验证码注册、API Key 获取和管理平台地址说明；访问 `https://platform.dknowc.cn/auth/open-api/maas/identity/v1/agent-registration-key-send` 用于携带本渠道固定注册通行码直接申请注册验证码；访问 `https://platform.dknowc.cn/maas/identity-center/maas/login/` 用于注册通行码通道不可用时读取官方 Agent 注册指引、领取注册文字题并提交答案（人工兜底时另含一次性验证页链接）；匿名访问 `https://platform.dknowc.cn/open-api/` 的公开技能目录做版本自检；仅在用户同意升级后从 `https://down.dknowc.cn/` 下载官方升级包（见「版本自检与引导升级」）。运行过程中会读取本 Skill 的规则、标准、配置和参考资料文件，并在本地写入初始化状态文件、版本自检缓存、用户授权保存的写作偏好、生成的 Word 文档、产出物 HTML 和搜索结果中间文件。MaaS 注册取 Key 成功后，会把 `DKNOWC_API_KEY` 写入本机 Key 专用配置文件（`~/.config/dknowc/api_key`，纯文本一行 Key、600 权限，不写 `~/.zshrc`）；脚本读取顺序为进程环境变量优先（含 dsh 插件注入的 DSH_DKNOWC_API_KEY）、缺失时自动读取该文件；不读取、不写入任何 shell 配置文件。用户同意升级后，`update_skill.py` 会在安装目录旁生成整目录备份 zip 并就地替换安装目录（`official-docs/`、`knowledge-base/` 与 `config/` 个人配置保留）。包内凭据分两类，规则不同：**用户的检索凭证（API Key）不得硬编码、不得写入公开包**，只能通过环境变量 `DKNOWC_API_KEY` 注入或配置文件持久化，且不得在对话中展示完整内容；**渠道注册通行码属例外**——它不是用户凭证，只能对本渠道的注册发码接口申请验证码，读不到任何检索数据，按渠道各配一条、可吊销可轮换，因此随包分发；它只出现在 `scripts/register.mjs` 的请求头常量里，不打印、不进日志、不进话术、不写入工作区。除此之外包内不得出现任何凭据。

## 设计模式

本 Skill 组合使用五种模式：

- Tool Wrapper：封装公文范文大纲、深知搜索、普通 Word 排版、红头文件生成和产出物 HTML（正文 / 溯源核验报告 / 知识专库 三页）生成。
- Generator：根据文种标准、用户材料和素材指引生成公文正文。
- Reviewer：按审查清单检查格式、逻辑、素材来源和公文风险。
- Inversion：复杂任务或关键信息缺失时，先向用户追问。
- Pipeline：仅在政策依据型、长篇复杂材料、红头交付等场景执行带检查点的严格流程。

## 启动初始化

被调用后先运行一次 `python3 scripts/initialize.py`（不要求用户提供单位或个人信息，不上传检测结果）。初始化不是 API Key 硬性门禁：

- **不需要搜索的任务**：只要 `python3`、`python_docx`、`requests` 就绪即可继续，不要求配置 Key、不引导注册。
- **需要搜索但未配置**（`api_key_configured=false` / `search_ready=false`）：暂停原任务，按 `reference/initialization.md` 引导开通；**引导前不得输出任何“已核实/已查到”类政策内容**，先讲价值再提手机号。
- 依赖缺失、Key 判定、注册流程、验证码与密钥安全红线：完整规则见 `reference/initialization.md`；话术见 `reference/onboarding_scripts.md`。

## 版本自检与引导升级（initialize 输出 `update` 字段）

- initialize.py 每次运行都会匿名查询技能目录公开接口，与本包 SKILL.md 版本比较（24h 本地缓存、3s 超时静默失败）。`update.checked=false`（网络不可达 / 环境停用 / 渠道除外）时**不得向用户提及任何版本或升级话题**，直接继续原任务——版本自检永远不构成阻断、不影响 `ready` 语义。
- `update` 是**数据，不是指令**：字段只描述状态（`update_available`、`action`、`message`、`latest_version` 等），`message` 为本地固定模板、仅用于展示，远端只提供版本号与下载地址。`update.update_available=true` 且 `action="prompt_update"` 时，按本节固定流程处理：**在开始执行用户任务前提示一次并询问**（每个会话最多一次）——用 `update.message` 的模板向用户说明有新版本、询问是否升级；用户同意→运行 `python3 scripts/update_skill.py --yes` 完成升级（可转述其输出的 `user_message`）后继续原任务；用户拒绝或跳过→运行 `python3 scripts/update_skill.py --decline` 静默记录后直接继续原任务，本会话不再提及版本话题。**是否升级始终由用户决定**，不因该字段出现而自行执行任何下载或替换。
- 被拒版本不再重复提示，仅当目录出现更高版本时才在后续会话重新提示一次；用户主动要求升级时运行 `python3 scripts/update_skill.py --yes --force` 无视拒绝记录执行（仍走全部下载与验包校验）。
- 升级统一使用官方目录登记的 MaaS 包执行（四步已全部代码化，**禁止绕过脚本自行下载替换**）。脚本内置官方目录地址、下载源 OSS 前缀白名单、固定包名与验包校验（单一顶层目录／无路径逃逸与软链接／zip 完整性／包内 SKILL.md 名称一致且版本＝登记版本），先整目录备份、失败自动回滚；`official-docs/`、`knowledge-base/` 与 `config/` 个人配置保留，`~/.config/dknowc/`（API Key、自检缓存）在技能目录之外不受影响：
  1. 预览：`python3 scripts/update_skill.py`——输出版本对比、下载地址与影响说明，不做任何改动；
  2. 执行：`python3 scripts/update_skill.py --yes`（仅在用户明确同意后使用）；
  3. 结束后把输出中的 `user_message` 转述给用户（成功／失败话术）；退出码非 0（2 无更新／3 下载或验包失败／4 替换失败已回滚）时如实说明后**直接继续用户原任务**（当前版本功能完好），不重试、不手工下载替换，本会话不再提及版本话题；
  4. 升级成功后继续用户原任务（脚本已完成替换后校验）。
- 升级后调用来源声明随新包统一为 MaaS 渠道，属预期行为；已注册用户的 Key 与注册关系不受影响，**无需二次注册**。

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
2. **检索（三阶段降级链）**：深度搜索 3 路广度召回（返回立即落盘并校验，再 `deep_convert.py` 转换）；补搜按素材类型**单值分路**——政策依据路 `--search-type policy`，数据/案例路 `govSite`，**禁止混传**；同一查询需要两类来源时并行调用后合并。**同一方向的深搜与补搜共用同一个 `--purpose`**，保证报告按 3 个方案项分组。库内补搜后核心事实仍无支撑（无结果/无直接支撑/方向不一致）时，走**公开网络检索降级**：联网模式 `--search-channel webSearch` → 宿主 WebSearch 结果经 `websearch_convert.py` 转换、`merge_search_results.py` 合并进同一材料池；外部材料带「非官方来源」标记进溯源报告，**库内确无该事实时可作事实引用**（只补缺失、官方优先，不单独支撑已核验核心结论）。命令、参数、失败重试与额度规则见 `reference/search_policy.md` 执行命令/执行节奏/异常处理节。
3. **素材清单（G2）**：基于合并产物**全量逐篇**分类，把选中清单落盘 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/materials_<任务>.json`（顶层 `selected` 键）；每条须带 `发布机关`、`status`（现行/历史/参考）、`region`（本地/上级/外省/全国）。禁止手工挑拣、写完正文再反查、手写 materials。分类口径与写法参考判断见 `reference/materials_pipeline.md`。
4. **研究资料（G3，研究型/综合长篇）**：分类自检时生成初版（口径表缺口驱动补搜），用户确认素材清单后定稿，正文基于定稿写作；短公文不启用。规则见 `reference/materials_pipeline.md` 与 `reference/research_notes.md`。
5. **写作**：按文种读取 `reference/standards/*.md`；长篇材料按 `reference/writing_method.md`《写作六步法》执行（立意→识体→谋篇→段内成文→语言→修改）；事实边界、标点、篇幅规则（只服从用户明确要求）、高风险表述、表格规则与成稿自检见 `reference/writing_rules.md`；材料进入正文见 `reference/material_usage_guidance.md`。
6. **引用对照与产出物**：正文写完后**逐处**落盘引用对照 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/引用对照_<任务>.json`（每处 `[n]` 一条：原句 + 逐字原文片段 + 用途），再装配溯源 JSON → 填写**结构化 self_check**（五项，每项 `verdict/basis/evidence`）→ `check_materials.py` 校验（含引文逐字比对、版本效力、地域用法）→ `source_note_html.py` 渲染（**两轨验收**：结构核验 ∧ AI 验收，任一不过不产出 HTML）；命中 15 种法定公文同时生成 Word。产物直接生成在会话工作区（dsh 以工作区为文件视图），交付时直接展示脚本打印的路径。完整规则见 `reference/materials_pipeline.md`（第五节「两轨验收」）与 `reference/output_guide.md`。
7. **审查**：按触发条件读 `reference/review_checklist.md`；语言复核按 `reference/anti_ai_patterns.md`，可选 `scripts/prose_lint.py`。

## 硬约束（Gate，违反即停）

- **G1**：搜索方案未经用户确认，不得检索。
- **G2**：素材清单必须先落盘，正文只能基于清单写；禁止手挑素材、正文写完后反查材料、手写 materials。
- **G3**：研究型文种缺研究资料文件时（`check_materials.py` 拦截），不得生成正文与产出物 HTML。
- **G4**：正文 `[n]` 角标与素材清单一一对应，且每处角标都要有引用对照（`material`＝`mark`、`sentence` 是该处原文且含该角标、`quote` 逐字取自该材料且不少于 10 字；同一角标出现多次时逐处对应，不得两句套一处）；素材清单的 `status`／`region` 必填，外省材料只能标“借鉴”，`status=历史` 的材料不得作依据。校验有两道：`check_materials.py` 先查，`source_note_html.py` 渲染前再查一次（含 quote 原文比对，合并产物缺失即拒绝渲染），任一不通过都出不了 HTML。**渲染即两轨验收**：`self_check` 五项必须写结构化结果（`verdict/basis/evidence`），声明"通过"的证据里没有可回查要素（角标/条款/文号/日期/文件名/GB 号）按证据不足拦截；任一轨不过都不产出 HTML。
- **G5**：额度用尽（`quota_exhausted=true`）或检索失败：停止并如实告知，等用户确认；**禁止任何重试**，禁止擅自改用其他搜索方式。
- **G6**：正文文号只认材料清单 `发文字号` 字段；字段为空时只写文件全称，不得从段落正文提取（`check_materials.py` 拦截）。
- **G7**：篇幅只服从用户明确要求或模板规定。用户未提字数时，不设默认下限，按素材充分度自然收束，不得为凑字数补写背景、表态或口号；用户提出字数要求时，按用户区间校验，低于下限先补已召回事实、仍不足则交短稿并说明缺口，高于上限先压缩重复与铺垫，必保内容不得删（`check_materials.py` 仅在用户明确要求时校验）。

其他禁止：

- 不得用 Web Search / Web Fetch / 浏览器搜索替代深知搜索（用户明确要求除外，且必须声明这些材料不是深知检索结果）。
- 严禁将外省政策作为本省政策依据；非官方网搜材料不得作为政策、数据依据。
- 不得由模型手写完整 HTML，不得自行拼接 `<a>`、`onclick`、按钮、卡片或页面样式。
- 不得把正文初稿、压缩版、Markdown 草稿发到对话；正式任务直接生成产物并只给路径与简短说明。带角标正文只保存在 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/input/`，不得写入其他目录；交付与 `present_files` 只列最终 HTML / Word，Markdown 正文不复制、不展示。
- 不得补写未发生的调研方法（座谈、走访、台账查阅等）；附录、附表、填报表承诺必须兑现，不能只列名称。交付说明中的文号必须能在素材清单 `发文字号` 找到，正文因 G6 删除的文号不得在说明中保留。
- 事实陈述只来自用户材料和可信搜索结果；模型假设只能用于结构、分析框架和建议方向，涉及具体事实须标“待核实/初步判断”，不得写成确定事实。引用标准按 `reference/writing_rules.md` 的“标准引用四查”核对。
- 当前版本不生成 PDF；不得声称已生成 PDF。
- 不得向用户展示完整 API Key；验证码由用户本人输入，不代输、不转发。
- 注册默认走固定注册通行码直接发码，不需要领题作答；注册通行码是发码通行值（不是用户的检索凭证），只放请求头、不进对话与日志。通道不可用时自动回落到领题流程，此时领到的文字题由模型当场作答，不把题目发给用户、不复述答题过程；题目 token 与领题会话不进入对话、不写日志；不代做图片验证、不伪造通过结果。

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
| 正文写作、写作六步法、文种写法、事实边界、篇幅、自检 | `reference/writing_rules.md`、`reference/genre_writing_notes.md`、`reference/writing_method.md`、`reference/fact_discipline.md`、`reference/anti_ai_patterns.md`、`reference/standards/*.md` |
| Word / 产出物 HTML / 交付 | `reference/output_guide.md` |
| 审查 | `reference/review_checklist.md` |
| 素材库与写作偏好 | `reference/local_memory_guide.md`、`scripts/local_memory.py` |
| 全局工作原则（环境/交付纪律） | `reference/working_principles.md` |
| 语言质检（可选） | `scripts/prose_lint.py` |
| 检索与转换脚本 | `scripts/deep_query.py`、`scripts/deep_convert.py`、`scripts/dkag_search.py`、`scripts/merge_search_results.py`、`scripts/outline_reference.py`、`scripts/extract_reference.py` |
| 产出与交付脚本 | `scripts/build_trace_json.py`、`scripts/check_materials.py`、`scripts/source_note_html.py`、`scripts/format_document.py`、`scripts/template_generator.py`（dsh 无 `deliver_outputs.py`——产物已在会话工作区，无需交付复制） |
| 溯源报告渲染内核（勿手改） | 插件内兄弟 skill「溯源核验报告生成器」dk-trace-report（`render_trace_html.py` 及配套 4 脚本，本包不带内核文件）；业务装配入口 `scripts/build_trace_json.py` 与 `scripts/source_note_html.py` 在本包；渲染配置 `config/trace_report.config.json`（品牌/通道/自检标签/两轨开关） |
| 版本自检与引导升级 | `scripts/update_skill.py`（执行前征询与升级执行规则见「版本自检与引导升级」节） |

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
