# 深知可信PPT（SkillHub Public 版）

深知可信PPT由北京彩智科技有限公司旗下“深知可信智能”提供，是“原生 PPT 生成 + 可信内容层”的演示文稿 Skill：生成侧采用约束 SVG → 原生 DrawingML 编译架构，内容侧完全使用深知可信搜索获取权威、可溯源的素材。

## 核心特性

- **原生可编辑**：主 Agent 逐页手写约束 SVG，确定性编译器导出真实的 PowerPoint 原生对象（形状/文本/图表/表格），可在 PowerPoint/WPS 中继续修改——不是整页图片，不是模板填空。
- **内容可信**：所有事实素材来自深知可信搜索的权威文件库；每个数据、每条政策有来源。双版溯源核验报告：提纲确认前（事前核验）与交付时（事后溯源）各一份——首屏核验报告单（依据溯源/引用对应/材料新旧/材料构成/交付前检查五项真实计算指标；一篇材料一张卡、原文原段标注、标题链、高可信徽标、检索分组筛选、未引用召回分组、对照弹层）、正文分节卡片、素材四分类色卡、打印归档模式，随 .pptx 三件套交付。
- **先推理再设计**：深知检索 → 内容包（叙事+页面规划）→ 用户确认 → 逐页设计，结构与证据先于版式。
- **风格预设**：党政简洁（默认）、数据图表、商务汇报、庄重典雅、培训课件 + 通用风格；多画布规格：16:9 / 4:3 / 小红书 3:4 / 1:1 / 竖版 9:16 / A4。
- **质量门**：SVG 质检（errors 必须修复）、双用户确认门（检索方案、结构方案）、检索异常不静默降级。

## 架构

```
dknowc-ppt-assistant/
├── SKILL.md                     # 主入口：路由 + Generate 主线 + 硬规则
├── THIRD_PARTY_NOTICES.md       # 第三方开源（MIT）抽取声明
├── workflows/                   # routing.md + generate-pptx.md（运行时权威）
├── references/                  # SVG契约 / 风格预设 / 内容包规范 / 素材规则 / 开通引导 / 上游示例
├── scripts/
│   ├── initialize.py            # 环境与 Key 检查
│   ├── register_key.mjs         # MaaS 注册取 Key
│   ├── check_release.py         # 发布检查
│   ├── trusted_search.py        # 深知可信搜索（内容层）
│   ├── render_trace_html.py     # 溯源核验报告（提纲版/成稿版）
│   ├── preview_slide_html.py    # SVG 页面 HTML 预览页（首页确认/进度查看）
│   └── svg_to_pptx 等           # 第三方开源（MIT）抽取的编译器组件
├── projects/                    # 项目工作区（内容包/SVG/导出产物）
└── official-docs/               # 检索结果与溯源中间文件
```

## 依赖

基础：`python3`、`requests`。编译导出另需 `python-pptx`、`XlsxWriter`（缺失时可用 `uv run --with python-pptx --with XlsxWriter` 隔离提供）。可选增强：`skia-pathops`（布尔形状）、`uharfbuzz`（文字轮廓），缺失不影响主线。

素材检索需要环境变量 `DKNOWC_API_KEY`（通过 `scripts/register_key.mjs` 或 MaaS 平台 `https://platform.dknowc.cn/` 获取）；用户只要排版、材料齐全时无需 Key。

## 快速使用

1. 初始化：`python3 scripts/initialize.py`
2. 主题模式检索：`python3 scripts/trusted_search.py "问题" --service-area 地域 --json-only --output official-docs/search-results/xx.json`
3. 提纲版报告：`python3 scripts/render_trace_html.py official-docs/search-results/xx.json --answer-file official-docs/search-results/<项目短名>_outline.md --title "<标题> 提纲 · 溯源核验报告"`
4. 质检：`python3 scripts/svg_quality_checker.py projects/<项目> --quick-generate`
5. 导出：`uv run --with python-pptx --with XlsxWriter python3 scripts/svg_to_pptx.py projects/<项目> --quick-generate`

完整流程（内容包、确认门、溯源）见 `SKILL.md` 与 `workflows/generate-pptx.md`。

## 版本说明

当前 dsh 版基于母版 `1.1.0`：溯源核验报告核验式改版——首屏核验报告单（五项真实计算指标）、报告式分节卡片布局、素材四分类色系与筛选、打印归档模式、生成前硬校验，`--stage outline|final` 双版适配；新增 SVG 页面 HTML 预览页（`preview_slide_html.py`，配合 dsh 首页确认门）；移动端适配。`1.0.3`：对外文档表述优化——不再点名上游开源项目。`1.0.2`：产品更名为「深知可信PPT」；报告统一命名「溯源核验报告」；新增提纲版报告，交付三件套。`1.0.1`：优化开通检索的注册引导（价值前置、时机后移、可退路），新增引导参考与效果示例文件，补齐注册请求渠道埋点。

## 路线图

Create Template（可复用模板工作区）、Fill Native PPTX（单位模板填充）、Enhance Native PPTX（成品增强）、语音旁白与 MP4。见 `SKILL.md` 路线图一节。
