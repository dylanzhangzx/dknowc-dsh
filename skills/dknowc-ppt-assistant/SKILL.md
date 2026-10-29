---
name: "深知可信PPT"
slug: "dknowc-ppt-assistant-dsh"
display_name: "深知可信PPT"
display_name_en: "dknowc PPT assistant"
description: "当用户要求制作 PPT、演示文稿、汇报 PPT、工作总结汇报、课件、宣讲材料、把材料转成 PPT、做幻灯片，或要求可编辑原生 PPT、多版式（16:9/4:3/小红书/朋友圈/竖版/A4）输出时，使用深知可信PPT。生成侧采用约束 SVG → 原生 DrawingML 编译路线：主 Agent 逐页手写约束 SVG，确定性编译器导出真实可编辑的 PowerPoint（原生形状/文本/图表/表格，非整页图片）；内容侧完全使用深知可信智能 API：通过深知可信搜索检索权威政策、数据与案例素材，全程可溯源。内置党政简洁、数据图表、商务汇报、庄重典雅、培训课件等风格预设，默认交付 .pptx 与溯源核验报告。"
description_zh: "深知可信PPT，是由北京彩智科技有限公司旗下“深知可信智能”提供的演示文稿制作助手，高效、专业地完成企事业单位与政府机关等场景下的汇报演示制作、课件宣讲和材料转化需求，所有事实素材与数据依据，都全程可溯源到权威部门发布的规范性文件。本技能用于工作汇报PPT、专题汇报、总结汇报、述职汇报、政策宣讲、培训课件、数据汇报等演示文稿制作，也支持把用户上传的 Word 文稿、会议记录、调研报告等工作材料直接转为 PPT，帮助用户把零散想法、汇报要点、工作素材转化为逻辑清楚、重点突出、风格得体、可直接修改使用的演示文稿。内置党政简洁、数据图表、商务汇报、庄重典雅、培训课件等风格预设，支持 16:9、4:3、小红书、朋友圈、竖版故事、A4 等多画布规格。依托深知可信搜索，获取准确有效的法规政策依据、行业信息与数据、标准规范和案例参考，并单独生成可交互的溯源核验报告，帮助用户讲得有依据、能复核、可交付。演示文稿支持生成真实可编辑的 PowerPoint 文档（.pptx），原生形状、文本、图表与表格均可在 PowerPoint/WPS 中继续修改，并配套交付可点击核验的溯源核验报告。"
description_en: "dknowc PPT assistant is a presentation-generation Skill provided by dknowc Trusted Intelligence under Beijing Caizhi Technology Co., Ltd. It combines reasoning-first presentation methodology with a trusted content layer: authoritative materials with sources are gathered through dknowc Trusted Search, confirmed as a content pack, then hand-authored page by page as constrained SVG and compiled by a deterministic converter into a genuinely editable native PowerPoint (real shapes, text, charts and tables). Built-in party/government-compliant style presets; multi-canvas support (16:9, 4:3, RED, square, story, A4); delivers .pptx plus a clickable provenance HTML."
category: "通用办公"
version: "1.5.2-dsh"
author: "彩智科技"
permissions:
  network:
    - "https://open.dknowc.cn/"
    - "https://platform.dknowc.cn/"
  local_read:
    - "本 Skill 的 workflows、references 规则与契约文件"
    - "scripts 下自研脚本与第三方开源（MIT）抽取的编译器组件"
    - "dknowc-projects/ 项目工作区中的内容包、SVG 与素材"
  local_write:
    - "本地初始化状态文件"
    - "dknowc-projects/ 项目目录（内容包、SVG、图片、质检报告、导出产物）"
    - "dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/ 检索结果与溯源中间文件"
    - "会话工作区产物目录（脚本按会话自动锚定，无需交付复制）"
    - "本机 DKNOWC_API_KEY 专用配置文件（~/.config/dknowc/api_key，注册成功后写入）；历史 ~/.zshrc 配置块仅作读取兜底，脚本默认不修改该文件（显式 --clean-zshrc 时才清理历史块）"
secrets:
  - "DKNOWC_API_KEY"
---

# 深知可信PPT

深知可信PPT由北京彩智科技有限公司旗下“深知可信智能”提供，是把**原生生成架构**（约束 SVG → DrawingML 编译）与**深知可信内容层**（可信搜索 + 全程溯源）结合的演示文稿 Skill。

定位一句话：**内容可信是我们的，排版专业是编译器的**。生成侧主 Agent 逐页手写约束 SVG、确定性编译器导出真实可编辑的原生 PowerPoint；内容侧所有事实素材来自深知可信搜索的权威文件库，每个数据、每条政策可溯源。

> **dsh Key 机制**：dsh 清理名字含 KEY 的隐式环境变量，但**专用配置文件读取不受影响**——注册成功后 Key 写入 `~/.config/dknowc/api_key`，本会话检索脚本立即可用（无需重启 dsh）。仅 dsh 捆绑的 MCP 兜底工具需重启后加载新 Key。
>
> **dsh 检索通道**：正式素材检索一律走脚本直连（全量结构化返回，含文号/快照/标题链/可信度）；dsh 捆绑的 MCP 工具返回为精简视图，仅作应急，不据此生成核验报告。

## 权限说明

本 Skill 访问 `https://open.dknowc.cn/` 用于深知可信搜索素材检索；访问 `https://platform.dknowc.cn/` 用于 MaaS 手机号验证码注册与 API Key 获取说明。运行中读取本 Skill 的规则、契约与项目文件，写入 `dknowc-projects/` 项目工作区（内容包、SVG、图片、导出产物，工作区级、跨会话延续）和 `dknowc-output/<会话ID前8位>/official-docs/` 中间文件（按会话隔离）。API Key 只通过环境变量 `DKNOWC_API_KEY` 注入，不硬编码、不写入公开包、不在对话中展示完整内容。

## 启动初始化

被调用后先运行 `python3 {skillDir}/scripts/initialize.py`。三类前置：**基础**（python3；requests 可选、不影响功能）、**检索**（Key 已配置；未配置按「统一 API Key 管理」引导，不得改用外部搜索；用户只要排版/明确说「不用查」时可无 Key 继续——材料模式免检索）、**编译**（python-pptx/XlsxWriter，仅导出需要，缺失时 `uv run --with python-pptx --with XlsxWriter ...` 隔离提供）。Key 读取顺序：环境变量 → `~/.config/dknowc/api_key` → 历史 `~/.zshrc` 兜底。**素材检索统一走 `trusted_search.py` 脚本通道**。前置明细与初始化输出字段见 [`references/initialization.md`](references/initialization.md)。初始化不要求用户提供单位或个人信息，不上传检测结果。

## 统一 API Key 管理

dsh 版不内置 API Key。需检索且本机无 Key 时走手机号验证码注册三步（`challenge` 领题 → `answer` 作答 → `register` 取 Key，固定 `type=11`、dsh 专属渠道码 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`、body `source="agent"` 合同标记）——dsh 捆绑 MCP 为 Bearer API Key 认证、无 OAuth 取 Key 通道，不经 `create_api_key` 取 Key；`save-key` 子命令保留（可配合其他宿主取到的密钥落盘）。**文字题由 Agent 当场计算，不把题目发给用户、token 与会话不进对话不写日志**。**脚本各分支输出的 `user_message` 必须原样转述**；手机号全程脱敏；Key 自动落盘本机配置文件；不在对话回显完整密钥。注册全流程（challenge/answer 退出码、`pending:true`、`--new-key`、降级地址、legacy 兜底；dsh 无 MCP 取 Key 路径）见 [`references/initialization.md`](references/initialization.md)。

### 开通引导规则（需要检索的任务）

只有任务确实需要深知检索（政策依据/数据支撑/案例参考，或用户明确要求权威数据）且无有效 Key 时才引导；用户只要排版、明确说「不用查」时不引导。四条硬规则：

1. **先价值、后验证**：先让用户理解权威检索对这份演示文稿的价值，再提手机号；不得开口就要手机号；时机尽量后置（检索方案确认门之后）。
2. **引导前禁示**：用户确认开通或明确拒绝前，不得输出任何「已核实/已查到/均为官网原文」类内容——政策数据只能来自真实检索或「数据待核验」标注，禁止用模型知识冒充检索结果。
3. **退路唯一化**：不开通只走「材料模式＋待核验标注」，禁止承诺用联网检索替代；拒绝后不纠缠，交付后轻提示每任务最多一次。
4. **固定话术原样转述**：话术库与报错表见 [`references/onboarding_scripts.md`](references/onboarding_scripts.md)，检索能力说明见 [`references/search_intro.md`](references/search_intro.md)；`user_message`/`guide_message`/`env_message` 必须原样转述。

引导话术要点、样例出示（`sample_trace_report.html` 等）、安全边界说明等完整规则见 [`references/initialization.md`](references/initialization.md)。


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

1. **检索方案确认门**：主题模式下先展示检索方案（地域、每条 query 原文与信息需求、素材类型、使用边界），用户确认后执行 `scripts/trusted_search.py`——同方案内多路**默认并行**（每路独立 `--output`，单批不超过 4 路，后台并行、全部结束后逐路检查结果）；失败路单独串行重试一次；任意一路额度用尽整批即停；平台明显限流（多路同时报错）回退逐路串行。
2. **结构方案确认门**：内容包（核心信息/叙事/页面规划/素材清单）+ 风格预设一起确认后，才创建项目、写 SVG。
3. **主 Agent 逐页手写 SVG**：遵循 [`references/svg-authoring.md`](references/svg-authoring.md) 的元素契约与排版纪律；禁止脚本批量生成页面。
4. **质检判据与循环纪律**：通过判据＝`svg_quality_checker.py` 退出码 0 且 **errors=0**（`passed-with-warnings` 即通过，warnings 一律不阻断导出与交付）；质检→修复循环**最多 3 轮**、每轮只修 errors 与明显事实性错误；**导出后不回头**（不再质检/不再截图自检/不再微调重导，重跑仅限用户明确要求修改）。导出用 `svg_to_pptx.py`（quick 无锁模式），产物是**原生可编辑** .pptx，不得降级为整页图片。
5. **双报告全程可溯源**：执行过检索的任务，结构方案确认门前生成**提纲版**溯源核验报告（事前核验，用户确认提纲即可逐条点开原文），交付时生成**成稿版**（事后溯源）；两版同脚本同形式——核验报告单（五项真实计算指标）+ 过程回顾条 + 正文文档流（句后引文胶囊，点击原地展开溯源卡，含多段分块与标题链）+ 知识专库独立视图（搜索/热词/检索分组筛选）；接口返回的原文链接**原样进报告**（不做连通性检测、不隐藏），接口提供存档快照时作为附加回看入口；素材无角标对应时脚本拒绝生成（[`references/material_usage.md`](references/material_usage.md)）；与 .pptx 三件套一并交付并说明其为辅助核验文件。

## 参考资料索引

| 文件 | 内容 | 加载时机 |
| --- | --- | --- |
| `workflows/routing.md` | 入口判断与模式选择 | 任务开始 |
| `workflows/generate-pptx.md` | Generate 主线运行时权威 | 路由选定后 |
| `references/initialization.md` | 初始化前置、API Key 注册全流程（dsh 无 MCP 取 Key 路径）、开通引导完整规则 | 初始化缺 Key、需引导开通、注册出错时 |
| `references/svg-authoring.md` | 约束 SVG 方言契约 | 手写 SVG 前 |
| `references/style-presets.md` | 风格预设（5 党政 + 通用） | 结构方案确认门前 |
| `references/content-pack.md` | 内容包规范 | 编制内容包时 |
| `references/material_usage.md` | 素材使用与溯源规则 | 检索后、交付前 |
| `references/search_intro.md` | 检索能力说明与开通引导话术 | 引导用户开通检索前 |
| `references/onboarding_scripts.md` | 开通引导与报错固定话术库（S1-S6/报错表/FAQ/禁则） | 引导开通、注册链路、检索出错时 |
| `references/sample_search_result.md` | 检索结果示例（展示用） | 用户犹豫或询问检索效果时 |
| `references/sample_effect.html` | 含权威数据引用的演示页效果示例（展示用） | 用户犹豫或询问检索效果时 |
| `references/sample_trace_report.html` | 溯源核验报告全要素示例（展示用） | 用户犹豫或询问核验效果时 |
| `references/upstream-example/` | 上游示例（cover/内容页 SVG、design_spec、spec_lock） | 手写 SVG 需要参照时 |

## 交付规范

- 主交付物：`dknowc-projects/<项目名>/exports/<演示名>.pptx` + 一句简短说明；执行过检索时按**三件套**交付（另加提纲版/成稿版核验报告两份 HTML，均为辅助核验文件）。**交付清单只有这三件、每个产物只交付一份、逐个显式列路径交付**——中转报告与检索 JSON/答案文件/内容包/SVG/质检报告等中间产物一律不交付。
- **dsh 交付**：产物直接生成在会话工作区——`.pptx` 与两份核验报告在 `dknowc-projects/<项目名>/exports/`，渲染中转件在 `dknowc-output/<会话ID前8位>/official-docs/output/`。dsh 以工作区为文件视图、访达也可直达，直接向用户展示脚本打印的路径即可，无需交付复制。
- **交付干净原则**：报告须「核验完成」状态，可修复问题先修复重渲；不可抗力缺口温和提醒并说明原因。
- 修改走闭环：内容包 → SVG → 重新质检导出；不直接改 .pptx。完整交付纪律（三条命令纪律、清单规则、事故背景）见 [`workflows/generate-pptx.md`](workflows/generate-pptx.md) Step 9。

## 路线图（未实现，不主动承诺）

- Create Template：从素材提炼可复用 Brand/Style/Layout/Deck 模板工作区。
- Fill Native PPTX：用单位现成 .pptx 模板壳填充内容（OOXML 补丁路线）。
- Enhance Native PPTX：对成品稿追加备注/转场/动画。
- 演讲备注转语音旁白与 MP4 导出。

## 第三方组件

SVG→PPTX 编译器及配套工具抽取自第三方开源项目（MIT 许可），按依赖闭包抽取所需子集；完整来源与许可声明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
