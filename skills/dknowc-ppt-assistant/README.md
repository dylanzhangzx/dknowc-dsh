# 深知可信PPT（dsh 版）

深知可信PPT由北京彩智科技有限公司旗下“深知可信智能”提供，是“原生 PPT 生成 + 可信内容层”的演示文稿 Skill：生成侧采用约束 SVG → 原生 DrawingML 编译架构，内容侧完全使用深知可信搜索获取权威、可溯源的素材。

## 核心特性

- **原生可编辑**：主 Agent 逐页手写约束 SVG，确定性编译器导出真实的 PowerPoint 原生对象（形状/文本/图表/表格），可在 PowerPoint/WPS 中继续修改——不是整页图片，不是模板填空。
- **内容可信**：所有事实素材来自深知可信搜索的权威文件库；每个数据、每条政策有来源。双版溯源核验报告：提纲确认前（事前核验）与交付时（事后溯源）各一份——核验报告单（五项真实计算指标）+ 过程回顾条 + **原问题行** + 正文文档流（句后引文胶囊点击原地展开溯源卡）+ **知识专库**（搜索/热词/检索分组）+ 同文去重（同一篇文章只出一张卡，同文异号并列显示全部编号）+ 原文链接原样给出（不做连通性检测）与存档快照附加回看 + 打印归档（只打正文/完整归档），随 .pptx 三件套交付。
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
├── references/                  # 初始化与Key管理 / SVG契约 / 风格预设 / 内容包规范 / 素材规则 / 开通话术库 / 上游示例
├── scripts/
│   ├── initialize.py            # 环境与 Key 检查
│   ├── register_key.mjs         # MaaS 注册取 Key / save-key（MCP 授权路径落盘）
│   ├── attribution.py           # 来源声明头构造（X-Dknowc-Attribution）
│   ├── mcp_direct.py            # dsh：MCP 返回直调落盘（应急兜底通道）
│   ├── trusted_search.py        # 深知可信搜索（内容层，未连接 MCP 时）
│   ├── mcp_convert.py           # MCP trusted_search 返回 → REST 形态转换
│   ├── render_trace_html.py     # 溯源核验报告（提纲版/成稿版）
│   ├── preview_slide_html.py    # SVG 页面 HTML 预览页（首页确认/进度查看）
│   └── svg_to_pptx 等           # 第三方开源（MIT）抽取的编译器组件
└── …（运行时产物不落 skill 目录：项目工作区在会话工作区 `dknowc-projects/`，检索/报告中间文件在 `dknowc-output/<会话ID前8位>/official-docs/`）
```

## 依赖

基础：`python3`（3.10+）。素材检索与注册脚本另需 `node`（18+，仅 `scripts/register_key.mjs` 需要；已配置 Key 的纯检索任务不依赖 Node）。

编译导出：`python-pptx`、`XlsxWriter`（缺失时可用 `uv run --with python-pptx --with XlsxWriter` 隔离提供，需 `uv`）。`requests` 为可选依赖（检索走标准库 `urllib`，缺失不影响任何功能）。

可选增强（缺失不影响主线，相关功能自动降级）：
- `Pillow`：图片预览与位图处理（`pic_to_svg` 等工具）
- `cairosvg` / `svglib` + `reportlab`：SVG→PDF/位图渲染路径
- `PyYAML`：读取 YAML 配置的工具
- `openpyxl`：XLSX 数据处理（无 `XlsxWriter` 时的回退路径）
- `skia-pathops`：布尔形状运算
- `uharfbuzz`：文字轮廓
- 外部命令（仅对应工具需要）：`ffprobe`（媒体时长探测）、ImageMagick `magick`（位图转换）

依赖缺失时 `scripts/initialize.py` 会给出提示并区分「阻断」与「可选」——python3 缺失阻断全部；编译依赖缺失只影响导出（可用 uv 隔离补齐）。

素材检索需要环境变量 `DKNOWC_API_KEY`（通过 `scripts/register_key.mjs` 或 MaaS 平台 `https://platform.dknowc.cn/` 获取）；用户只要排版、材料齐全时无需 Key。

## 快速使用

1. 初始化：`python3 {skillDir}/scripts/initialize.py`
2. 主题模式检索：`python3 {skillDir}/scripts/trusted_search.py "问题" --service-area 地域 --json-only --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/xx.json`
3. 提纲版报告：`python3 {skillDir}/scripts/render_trace_html.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/xx.json --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/<项目短名>_outline.md --title "<标题> 提纲 · 溯源核验报告"`
4. 质检：`python3 {skillDir}/scripts/svg_quality_checker.py projects/<项目> --quick-generate`
5. 导出：`uv run --with python-pptx --with XlsxWriter python3 {skillDir}/scripts/svg_to_pptx.py projects/<项目> --quick-generate -o "projects/<项目>/exports/<演示名>.pptx"`

完整流程（内容包、确认门、溯源）见 `SKILL.md` 与 `workflows/generate-pptx.md`。

## 版本说明

当前版本 `1.5.2-dsh`（2026-10-29）。

版本历史与逐版变更详见 GitHub Releases：<https://github.com/dylanzhangzx/dknowc-dsh/releases>。

## 路线图

Create Template（可复用模板工作区）、Fill Native PPTX（单位模板填充）、Enhance Native PPTX（成品增强）、语音旁白与 MP4。见 `SKILL.md` 路线图一节。
