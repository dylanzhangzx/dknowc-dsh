# 深知可信PPT（SkillHub Public 版）

深知可信PPT由北京彩智科技有限公司旗下“深知可信智能”提供，是“原生 PPT 生成 + 可信内容层”的演示文稿 Skill：生成侧采用约束 SVG → 原生 DrawingML 编译架构，内容侧完全使用深知可信搜索获取权威、可溯源的素材。

## 核心特性

- **原生可编辑**：主 Agent 逐页手写约束 SVG，确定性编译器导出真实的 PowerPoint 原生对象（形状/文本/图表/表格），可在 PowerPoint/WPS 中继续修改——不是整页图片，不是模板填空。
- **内容可信**：所有事实素材来自深知可信搜索的权威文件库；每个数据、每条政策有来源。双版溯源核验报告：提纲确认前（事前核验）与交付时（事后溯源）各一份——核验报告单（五项真实计算指标）+ 过程回顾条 + 正文文档流（句后引文胶囊点击原地展开溯源卡）+ 材料专库（搜索/热词/检索分组）+ 链接活性检测与存档快照兜底 + 打印归档（只打正文/完整归档），随 .pptx 三件套交付。
- **先推理再设计**：深知检索 → 内容包（叙事+页面规划）→ 用户确认 → 逐页设计，结构与证据先于版式。
- **风格预设**：党政简洁（默认）、数据图表、商务汇报、庄重典雅、培训课件 + 通用风格；多画布规格：16:9 / 4:3 / 小红书 3:4 / 1:1 / 竖版 9:16 / A4。
- **质量门**：SVG 质检（errors 必须修复）、双用户确认门（检索方案、结构方案）、检索异常不静默降级。

## 架构

```
dknowc-ppt-assistant/
├── SKILL.md                     # 主入口：路由 + Generate 主线 + 硬规则
├── attribution.json             # 调用来源声明（kind/source/channel，打包期按渠道改此文件）
├── THIRD_PARTY_NOTICES.md       # 第三方开源（MIT）抽取声明
├── workflows/                   # routing.md + generate-pptx.md（运行时权威）
├── references/                  # SVG契约 / 风格预设 / 内容包规范 / 素材规则 / 开通话术库 / 上游示例
├── scripts/
│   ├── initialize.py            # 环境与 Key 检查
│   ├── register_key.mjs         # MaaS 注册取 Key / save-key（MCP 授权路径落盘）
│   ├── attribution.py           # 来源声明头构造（X-Dknowc-Attribution）
│   ├── check_release.py         # 发布检查
│   ├── trusted_search.py        # 深知可信搜索（内容层，未连接 MCP 时）
│   ├── mcp_convert.py           # MCP trusted_search 返回 → REST 形态转换
│   ├── render_trace_html.py     # 溯源核验报告（提纲版/成稿版）
│   ├── deliver_outputs.py       # 宿主环境交付复制（WorkBuddy 等）
│   ├── preview_slide_html.py    # SVG 页面 HTML 预览页（首页确认/进度查看）
│   └── svg_to_pptx 等           # 第三方开源（MIT）抽取的编译器组件
├── projects/                    # 项目工作区（内容包/SVG/导出产物）
└── official-docs/               # 检索结果与溯源中间文件
```

## 依赖

基础：`python3`、`requests`。编译导出另需 `python-pptx`、`XlsxWriter`（缺失时可用 `uv run --with python-pptx --with XlsxWriter` 隔离提供）。可选增强：`skia-pathops`（布尔形状）、`uharfbuzz`（文字轮廓），缺失不影响主线。

素材检索需要环境变量 `DKNOWC_API_KEY`（通过 `scripts/register_key.mjs` 或 MaaS 平台 `https://platform.dknowc.cn/` 获取）；用户只要排版、材料齐全时无需 Key。

## 快速使用

1. 初始化：`python3 <skillDir>/scripts/initialize.py`
2. 主题模式检索：`python3 <skillDir>/scripts/trusted_search.py "问题" --service-area 地域 --json-only --output official-docs/search-results/xx.json`
3. 提纲版报告：`python3 <skillDir>/scripts/render_trace_html.py official-docs/search-results/xx.json --answer-file official-docs/search-results/<项目短名>_outline.md --title "<标题> 提纲 · 溯源核验报告"`
4. 质检：`python3 <skillDir>/scripts/svg_quality_checker.py projects/<项目> --quick-generate`
5. 导出：`uv run --with python-pptx --with XlsxWriter python3 <skillDir>/scripts/svg_to_pptx.py projects/<项目> --quick-generate`

完整流程（内容包、确认门、溯源）见 `SKILL.md` 与 `workflows/generate-pptx.md`。

## 版本说明

当前 SkillHub Public 版基于 `1.3.4`（内容同 1.3.3，仅修正 SKILL.md 中与代码不一致的一处 source 说明）：①**调用来源追踪声明**（`X-Dknowc-Attribution`，包根 `attribution.json` + `scripts/attribution.py`，检索与注册请求统一带头，version 从 SKILL.md 动态解析）；②**MCP 取 Key 优先路径**（宿主「深知可信工作台」已 OAuth 授权时经 `create_api_key` 免手机号验证码直接开通，`register_key.mjs save-key` 密钥经 stdin 落盘；无 MCP 或未授权回落手机号注册）。`1.3.2`（2026-09-29 同号）（对齐公文写作 3.7.3~3.7.6 + 可信搜索 1.4.0）：检索统一走**纯脚本通道**（MCP「深知可信工作台」通道经实测大结果落盘不可靠已回退，`mcp_convert.py` 保留待恢复）；**API Key 落盘迁移**到 `~/.config/dknowc/api_key`（600 权限，自动清理 ~/.zshrc 历史块）；**交付链路重写**（宿主识别 + 仅 WorkBuddy/豆包复制 + 宿主未知保留 skill 输出 + 绝不覆盖改 `_v2`）；报告 UI（**知识专库**/**来源文章**术语、章节目录三项修复、连续角标换位、统计口径修正、输出版本化）；检索链路（每路即时落地、Query 句式修订、业务码校验、角标契约写实）。`1.3.1`（2026-09-20）：公文写作 3.7.1+3.7.2 对齐——「现行效力」提示行移除、搜索串行改默认并行（知识专库存档 kb_zone 随之移除）、初始化 MCP「深知可信工作台」检测与场景分流、标题链降级（无章节不显示）、Query 构造原则（对象+信息需求句式）、deliver_outputs 多会话串目录三级保护、同指标口径冲突检测、选材优先发文版与文号回填。`1.3.0`（2026-09-16）：溯源核验报告整体重构（对齐公文写作 3.7.0 同源方案，参考深知晓可信深度溯源报告原型）——正文文档流 + 句后引文胶囊（点击原地展开溯源卡、同段同材料去重）、章节引用徽章、材料专库独立视图（大搜索/热词真实计算/检索分组 tabs）、顶栏工具（只看正文/复制全文/打印归档下拉）、原文链接活性检测（404/410+软 404 嗅探）与存档快照兜底（screenShotPath）、多段分块面包屑链、文号关键性行、紫色系视觉；PPT 特有口径全部保留（提醒制/双版 stage/位置兜底/双形态 JSON/双向硬校验/未引用双通道/知识专库存档）。`1.2.2`（2026-09-11）：安全扫描措辞透明化（腾讯安全威胁情报中心扫描反馈）——话术库新增透明度说明、S2 话术写明平台与注册本质、「通俗表达但不隐瞒」取代「不暴露内部术语」类措辞，语义与功能不变。`1.2.1`（2026-09-11）：注册漏斗话术固化（移植公文写作 3.6.1）——固定话术库（S1-S6/报错表/FAQ）、三脚本 user_message 原样转述、额度用尽禁重试、新建 Key 失败沿用原密钥、核验报告全要素示例。`1.2.0`（2026-09-09）：溯源核验报告 0907 会议八项改版（移植公文写作 3.6.0 同源方案）——报告名统一「溯源核验报告」+ 身份章、五项指标拟人化、原文原段标注、标题链、高可信徽标、recalled_materials 未引用召回、检索分组筛选、移动端对照弹层；`1.1.0`（2026-09-02）：溯源核验报告核验式改版（移植公文写作 3.5.0 同源方案）——首屏核验报告单（五项真实计算指标）、报告式分节卡片布局、素材四分类色系与筛选、打印归档模式、生成前硬校验，`--stage outline|final` 双版适配，数据层修复全部保留；含宿主环境交付（`deliver_outputs.py`，WorkBuddy 等宿主中自动把提纲版报告与三件套复制到宿主工作区并展示可见路径）与移动端适配（680px 断点、查看核验材料双向锚点、角标/证据 chips 底部弹层就地查看）。`1.0.3`：对外文档表述优化——不再点名上游开源项目，第三方来源与 MIT 许可统一收敛到 THIRD_PARTY_NOTICES.md。`1.0.2`：产品更名为「深知可信PPT」；报告统一命名「溯源核验报告」；新增提纲版报告，交付三件套。`1.0.1`：优化开通检索的注册引导（价值前置、时机后移、可退路），新增引导参考与效果示例文件，补齐注册请求渠道埋点。

## 路线图

Create Template（可复用模板工作区）、Fill Native PPTX（单位模板填充）、Enhance Native PPTX（成品增强）、语音旁白与 MP4。见 `SKILL.md` 路线图一节。
