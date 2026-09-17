---
name: dknowc-ppt-assistant
slug: "dknowc-ppt-assistant"
display_name: dknowc-ppt-assistant
display_name_en: "dknowc PPT assistant"
description: "当用户要求制作 PPT、演示文稿、汇报 PPT、工作总结汇报、课件、宣讲材料、把材料转成 PPT、做幻灯片，或要求可编辑原生 PPT、多版式（16:9/4:3/小红书/朋友圈/竖版/A4）输出时，使用深知可信PPT。生成侧采用约束 SVG → 原生 DrawingML 编译路线：主 Agent 逐页手写约束 SVG，确定性编译器导出真实可编辑的 PowerPoint（原生形状/文本/图表/表格，非整页图片）；内容侧完全使用深知可信智能 API：通过深知可信搜索检索权威政策、数据与案例素材，全程可溯源。内置党政简洁、数据图表、商务汇报、庄重典雅、培训课件等风格预设，默认交付 .pptx 与溯源核验报告。"
description_zh: "深知可信PPT，是由北京彩智科技有限公司旗下“深知可信智能”提供的演示文稿制作助手，高效、专业地完成企事业单位与政府机关等场景下的汇报演示制作、课件宣讲和材料转化需求，所有事实素材与数据依据，都全程可溯源到权威部门发布的规范性文件。本技能用于工作汇报PPT、专题汇报、总结汇报、述职汇报、政策宣讲、培训课件、数据汇报等演示文稿制作，也支持把用户上传的 Word 文稿、会议记录、调研报告等工作材料直接转为 PPT，帮助用户把零散想法、汇报要点、工作素材转化为逻辑清楚、重点突出、风格得体、可直接修改使用的演示文稿。内置党政简洁、数据图表、商务汇报、庄重典雅、培训课件等风格预设，支持 16:9、4:3、小红书、朋友圈、竖版故事、A4 等多画布规格。依托深知可信搜索，获取准确有效的法规政策依据、行业信息与数据、标准规范和案例参考，并单独生成可交互的溯源核验报告，帮助用户讲得有依据、能复核、可交付。演示文稿支持生成真实可编辑的 PowerPoint 文档（.pptx），原生形状、文本、图表与表格均可在 PowerPoint/WPS 中继续修改，并配套交付可点击核验的溯源核验报告。"
description_en: "dknowc PPT assistant is a presentation-generation Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It combines reasoning-first presentation methodology with a trusted content layer: authoritative materials with sources are gathered through dknowc Trusted Search, confirmed as a content pack, then hand-authored page by page as constrained SVG and compiled by a deterministic converter into a genuinely editable native PowerPoint (real shapes, text, charts and tables). Built-in party/government-compliant style presets; multi-canvas support (16:9, 4:3, RED, square, story, A4); delivers .pptx plus a clickable provenance HTML."
category: "通用办公"
version: "1.3.0-dsh"
author: "彩智科技"
permissions:
  network:
    - "https://mcp.dknowc.cn/"
  local_read:
    - "本 Skill 的 workflows、references 规则与契约文件"
    - "scripts 下自研脚本与第三方开源（MIT）抽取的编译器组件"
    - "dknowc-projects/ 项目工作区中的内容包、SVG 与素材"
  local_write:
    - "本地初始化状态文件"
    - "工作区 dknowc-projects/ 项目目录（内容包、SVG、图片、质检报告、导出产物）"
    - "会话产物目录 dknowc-output/<会话ID>/official-docs/ 检索结果与溯源中间文件"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知可信PPT

深知可信PPT由北京彩智科技有限公司旗下“深知可信智能”提供，是把**原生生成架构**（约束 SVG → DrawingML 编译）与**深知可信内容层**（可信搜索 + 全程溯源）结合的演示文稿 Skill。

定位一句话：**内容可信是我们的，排版专业是编译器的**。生成侧主 Agent 逐页手写约束 SVG、确定性编译器导出真实可编辑的原生 PowerPoint；内容侧所有事实素材来自深知可信搜索的权威文件库，每个数据、每条政策可溯源。

## 权限说明

本 Skill（dsh 版）的素材检索经深知可信工作台 MCP 转接层（`mcp__dknowc__trusted_search`，Bearer 认证使用环境变量 `DKNOWC_API_KEY`）。运行中读取本 Skill 的规则、契约与项目文件，写入**工作区级项目目录** `dknowc-projects/`（内容包、SVG、图片、导出产物，跨会话延续）和**会话产物目录** `dknowc-output/<会话ID前8位>/official-docs/`（检索结果与溯源中间文件）。API Key 只通过环境变量 `DKNOWC_API_KEY` 注入，不硬编码、不写入公开包、不在对话中展示完整内容。

## 启动初始化

被调用后先运行一次：

```bash
python3 {skillDir}/scripts/initialize.py
```

- **基础前置**（缺失暂停全部能力）：`python3`、`requests`。
- **检索前置**（需要素材检索的任务要求）：`api_key_configured=true`、`search_ready=true`。未配置时按「统一 API Key 管理」引导，不得改用外部搜索。**dsh 场景检索调用 MCP 工具 `mcp__dknowc__trusted_search`**（返回结构经 `adapt_mcp_result.py --mode search` 规范化后使用；注册后临时 Key 场景用 `python3 <skillDir>/scripts/mcp_direct.py trusted_search '<JSON参数>' --output <会话目录>/official-docs/search-results/xxx_mcp_raw.json` 直调（脚本自动从环境变量或 `~/.zshrc` 解析 Key，也可 `DKNOWC_API_KEY=<Key>` 前缀显式传入）），不再直连 `trusted_search.py`（保留作离线兜底）。用户只要 PPT 排版、明确说「不用查，就用我给的材料」时，无 Key 也可继续（材料模式免检索）。
- **编译前置**（仅 Step 7 导出需要）：`python_pptx=true`、`xlsxwriter=true`；缺失不阻断检索与 SVG 创作，导出时用隔离环境提供依赖：

```bash
uv run --with python-pptx --with XlsxWriter python3 {skillDir}/scripts/svg_to_pptx.py ...
```

初始化不要求用户提供单位或个人信息，不上传检测结果。

## 统一 API Key 管理

SkillHub 版不内置 API Key。MaaS 注册取 Key 两步执行（`scripts/register_key.mjs`，固定 `type=11`、渠道码 `7F9FBE52-849B-43FE-BB88-220E2A415FD8`、`source="agent"`）：

```bash
node {skillDir}/scripts/register_key.mjs send --phone <手机号>
```

返回 `status=true` 后暂停，向用户索取 6 位验证码，不得编造。然后：

```bash
node {skillDir}/scripts/register_key.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

手机号已注册时默认查回已有 Key。脚本各分支输出 `user_message`（成功/格式错/验证码错/网络异常/新建 Key 失败沿用原 Key），**必须原样转述给用户**；手机号全程脱敏。**注册成功自动把 Key 写入 `~/.zshrc` 标记块**（与其他三个深知 skill 共用同一标记块，幂等替换；`--no-zshrc` 跳过，回执 `envWriteSucceeded`）。dsh 场景当前任务经 `scripts/mcp_direct.py` 直调完成（脚本自动解析 Key），交付后建议重启 dsh 或新建会话走 MCP 转接。不在对话中回显完整访问密钥（与密码同理，防截屏泄露）。默认不重新生成 Key；用户明确要求时才加 `--new-key`。用户不希望脚本注册时，给出降级地址 `https://platform.dknowc.cn/auth/#/login`。

### 开通引导规则（需要检索的任务）

只有任务确实需要深知检索（需要政策依据、数据支撑、案例参考，或用户明确要求权威数据、最新政策情况）且检测不到有效 Key 时才引导；用户只要排版、明确说「不用查，就用我给的材料」时不引导。引导时必须做到：

- 结合当前任务和用户语气自然表达，禁止逐字照抄固定模板，禁止说明书式复述流程。
- 沟通话术通俗且如实：面向用户说「开通检索」，需要说明流程时如实说明是在深知可信智能平台（platform.dknowc.cn）注册访问凭证；「MaaS」「环境变量 DKNOWC_API_KEY」等技术词汇用户无需理解、可以不讲，但服务性质、费用（免费）与手机号用途必须如实告知（口径见 [`references/onboarding_scripts.md`](references/onboarding_scripts.md) 透明度说明）。
- 先价值、后验证：必须先让用户理解权威检索对当前这份演示文稿的价值（能查到什么、页面长什么样），再提出手机号验证；不得开口就要手机号。
- 引导时机尽量后置：优先在展示检索方案（检索方案确认门）、用户确认方案或表现出对检索结果的期待之后再引导开通；不要在任务一开始就要求验证。
- 解释要点：① 为什么需要：这份 PPT 的政策名、数字、案例凭印象写，汇报场合被当场指出来最影响效果；开通后可直接检索权威文件库素材，来源可溯源、经得起追问；② 有什么不一样：检索的是权威文件库原文（覆盖 600 万篇公开规范性文件、7000 万篇可溯源的权威公开资料，每日更新，覆盖 54 个行业、300 多个地市、2800 多个县），不是普通网页搜索；③ 怎么开：手机号收一次验证码，两步、约 10 秒，不用去网站、不用填表单，其余由 Agent 代办。
- 安全与边界说明（用户问起或犹豫时按需说明，不点名具体平台）：手机号仅用于本次验证，不发营销短信、不打营销电话；本 Skill 已通过所在平台的安全审核上架，服务由北京彩智科技提供；验证后只在本机保存一个访问密钥，用户的材料、文稿和演示文稿不会上传，检索时只发送检索词；不用了可随时注销。
- 给退路：用户拒绝或犹豫时，不得反复劝说、不得纠缠；转入材料模式继续制作，政策、数据处使用醒目的「数据待核验」「依据待补」类占位标注，交付时提醒用户这些位置尚未经权威核验；用户后续主动提出开通时再执行注册。
- 交付后轻提示：未配置 Key 的用户完成 PPT 交付后，可自然带一句「以后做要引用政策、数据的汇报 PPT，可开通权威检索，每条依据带原文出处」；每个任务最多提示一次，不追问、不重复。
- 话术与行为约束：注册漏斗与报错场景的**固定话术**见 [`references/onboarding_scripts.md`](references/onboarding_scripts.md)（按场景取用；`register_key.mjs` / `trusted_search.py` / `initialize.py` 输出的 `user_message` / `guide_message` / `env_message` **必须原样转述**，不得改写后发挥）；检索能力数据与差异化说明见 [`references/search_intro.md`](references/search_intro.md)。
- **引导前禁示**：用户确认开通或明确拒绝之前，不得输出任何「已核实 / 已查到 / 均为官网原文」类政策内容——需要检索的 PPT，政策数据只能来自真实检索或「数据待核验」标注，**禁止用模型自身知识冒充检索结果**。
- **退路唯一化**：用户不开通时只走「材料模式 + 待核验标注」，**禁止承诺用联网检索替代**（外部检索来源不可控，属违规承诺）。
- **样例悬念式出示**：用户犹豫或询问效果时，立即出示 [`references/sample_trace_report.html`](references/sample_trace_report.html)（核验报告示例，含「想先看看报告长什么样」钩子语境）；也可展示 [`references/sample_search_result.md`](references/sample_search_result.md) 与 [`references/sample_effect.html`](references/sample_effect.html)。示例文件均为示例数据，仅供展示，不得作为制作素材引用，不得发给用户当作交付物。
- **环境/组件话题就绪不可见**：`initialize.py` 的 `env_message` 仅在依赖缺失时出现且只问一次；就绪时不提组件、不确认、不感谢，不出现组件名。

## 任务路由

路由规则见 [`workflows/routing.md`](workflows/routing.md)。要点：

- 一切「做 PPT / 演示文稿 / 汇报 / 课件 / 材料转 PPT」请求进入 **Generate 生成主线**，执行细节以 [`workflows/generate-pptx.md`](workflows/generate-pptx.md) 为运行时权威。
- 三种进入模式：**主题模式**（先设计检索方案过确认门，深知检索补事实基线）、**材料模式**（用户材料为主体，仅补事实缺口）、**材料免检索模式**（用户明确不用查）。
- 路由纪律：匹配即执行不列菜单；缺前置条件说明并停止；确认门必须等用户显式确认。

## Generate 主线（v1 唯一路线）

```
初始化门禁 → [深知检索（主题模式）] → 内容包 → 提纲版溯源核验报告
→【结构方案确认门 ⛔】→ 创建项目 → 逐页手写 SVG（P01 → 首页确认 ⛔ → 其余不间断）
→ SVG 质检 → 编译导出 .pptx → 成稿版溯源核验报告 → 交付
```

完整步骤、确认门与强制命令见 [`workflows/generate-pptx.md`](workflows/generate-pptx.md)。核心硬规则：

1. **检索方案确认门**：主题模式下先展示检索方案（地域、每条 query 目的、素材类型、使用边界），用户确认后**串行**执行 `scripts/trusted_search.py`，禁止并发。
2. **结构方案确认门**：内容包（核心信息/叙事/页面规划/素材清单）+ 风格预设一起确认后，才创建项目、写 SVG。
3. **主 Agent 逐页手写 SVG**：遵循 [`references/svg-authoring.md`](references/svg-authoring.md) 的元素契约与排版纪律；禁止脚本批量生成页面。
4. **质检不过不导出**：`svg_quality_checker.py` errors 必须修复；导出用 `svg_to_pptx.py`（quick 无锁模式），产物是**原生可编辑** .pptx，不得降级为整页图片。
5. **双报告全程可溯源**：执行过检索的任务，结构方案确认门前生成**提纲版**溯源核验报告（事前核验，用户确认提纲即可逐条点开原文），交付时生成**成稿版**（事后溯源）；两版同脚本同形式，首屏为核验报告单与过程回顾条（五项真实计算指标）；正文连续文档流+句后引文胶囊（点击原地展开溯源卡：多段分块+面包屑标题链+查看全文/存档全文）；材料专库独立视图（大搜索/热词/检索分组 tabs/已引用筛选）；章节引用徽章；只看正文/复制全文/打印归档工具；生成时链接活性检测（--skip-link-check）与快照兜底（--disable-snapshot）；提纲表格角标就地变胶囊，素材无角标对应时脚本拒绝生成（[`references/material_usage.md`](references/material_usage.md)）；与 .pptx 三件套一并交付并说明其为辅助核验文件。

## 参考资料索引

| 文件 | 内容 | 加载时机 |
| --- | --- | --- |
| `workflows/routing.md` | 入口判断与模式选择 | 任务开始 |
| `workflows/generate-pptx.md` | Generate 主线运行时权威 | 路由选定后 |
| `references/svg-authoring.md` | 约束 SVG 方言契约 | 手写 SVG 前 |
| `references/style-presets.md` | 风格预设（5 党政 + 通用） | 结构方案确认门前 |
| `references/content-pack.md` | 内容包规范 | 编制内容包时 |
| `references/material_usage.md` | 素材使用与溯源规则 | 检索后、交付前 |
| `references/onboarding_scripts.md` | 开通引导与报错固定话术库（S1-S6/报错表/FAQ/禁则） | 引导开通、注册链路、检索出错时 |
| `references/sample_trace_report.html` | 溯源核验报告全要素示例（展示用） | 用户犹豫或询问核验效果时 |
| `references/search_intro.md` | 检索能力说明与开通引导话术 | 引导用户开通检索前 |
| `references/sample_search_result.md` | 检索结果示例（展示用） | 用户犹豫或询问检索效果时 |
| `references/sample_effect.html` | 含权威数据引用的演示页效果示例（展示用） | 用户犹豫或询问检索效果时 |
| `references/upstream-example/` | 上游示例（cover/内容页 SVG、design_spec、spec_lock） | 手写 SVG 需要参照时 |

## 交付规范

- 主交付物：`dknowc-projects/<项目名>/exports/<演示名>.pptx` + 一句简短说明。
- 执行过检索时按三件套交付：`.pptx` + `<演示名>_提纲核验报告.html`（事前核验）+ `<演示名>_成稿核验报告.html`（事后溯源）；两份报告均为辅助核验文件，不是正文附件。
- **dsh 交付**：三件套位于工作区 `dknowc-projects/<项目名>/exports/`（工作区级、访达可直达），直接向用户展示路径即可，无需交付复制。
- **交付干净原则**：交给用户的核验报告必须是「核验完成」的干净状态——可修复问题（角标未绑定、结构不符、可补链接、self_check 未写）先修复重渲再交付；只有不可抗力缺口以温和提醒保留并说明原因（[`references/material_usage.md`](references/material_usage.md)）。
- 不发送 SVG 源文件、内容包草稿、质检报告等中间产物；用户明确要看时除外。
- 修改走闭环：内容包 → SVG → 重新质检导出；不直接改 .pptx。
- 当前版本不做音频旁白/视频导出；用户要求时说明列入路线图。

## 路线图（未实现，不主动承诺）

- Create Template：从素材提炼可复用 Brand/Style/Layout/Deck 模板工作区。
- Fill Native PPTX：用单位现成 .pptx 模板壳填充内容（OOXML 补丁路线）。
- Enhance Native PPTX：对成品稿追加备注/转场/动画。
- 演讲备注转语音旁白与 MP4 导出。

## 第三方组件

SVG→PPTX 编译器及配套工具抽取自第三方开源项目（MIT 许可），已移除其官方发行版完整性门并按依赖闭包抽取子集；完整来源与许可声明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
