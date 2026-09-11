# Generate 生成演示稿 · 运行时权威

> 由 [`routing.md`](./routing.md) 选定 Generate 路线后加载。本文件拥有 Step 1-9 的执行顺序、确认门与强制命令。

**主管线**：

```
初始化门禁 → [深知检索（主题模式）] → 内容包 → 提纲版溯源核验报告
→【结构方案确认门 ⛔】→ 创建项目 → 逐页手写 SVG（P01 → 首页确认 ⛔ → 其余不间断）
→ SVG 质检 → 编译导出 .pptx → 成稿版溯源核验报告 → 交付
```

**执行纪律**：

- 主 Agent 逐页手写每个 SVG；禁止用脚本批量生成 `svg_output/` 页面。
- SVG 节奏：P01 → 首页确认门 → 其余页不间断完成 → 终检。不分组批量、不中途插入检查。
- 每个确认门必须等用户显式确认；门未关闭不得跨阶段捆绑工作。
- 质检/编译失败时只报告阻塞项与修复路径，不静默降级（如改导出整页图片）。

---

## Step 1 初始化门禁

```bash
python3 {skillDir}/scripts/initialize.py
```

- 基础依赖（`python3`/`requests`）缺失：暂停全部能力，按提示处理。
- `python_pptx=false` 或 `xlsxwriter=false`：仅阻断 SVG 编译导出（Step 7），素材检索与 SVG 创作可先行；编译时用 `uv run --with python-pptx --with XlsxWriter` 提供依赖。
- 需要检索的任务（主题模式、材料模式补检索）要求 `api_key_configured=true`；未配置时按 SKILL.md「统一 API Key 管理」引导，不得改用外部搜索。

## Step 2 深知检索（主题模式；材料模式仅补缺口）

1. 设计检索方案：覆盖政策依据、数据支撑、参考案例必要维度（表述参考不单列）；写明搜索地域、每条 query 的目的、素材类型、使用边界。面向用户展示时不得出现脚本参数名。
2. **【检索方案确认门 ⛔】** 展示方案，等待用户确认或调整。确认话术：「我建议先按下面方案检索权威素材，请确认是否执行，或告诉我需要增删哪些搜索项。」
3. 用户确认后**串行**执行（禁止并发）：

```bash
# dsh 默认走 MCP 工具 mcp__dknowc__trusted_search（参数同义：query/service_area/eff_time），
# 返回保存为 dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_语义名_mcp_raw.json，再经适配脚本规范化：
python3 {skillDir}/scripts/adapt_mcp_result.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_语义名_mcp_raw.json \
  --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_语义名.json --mode search
# 无 MCP 或临时 Key 场景的直连兜底：
python3 {skillDir}/scripts/trusted_search.py "检索问题" --service-area 单个地域 --eff-time 单个时间点 --json-only --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_语义名.json
```

4. 检索结果按素材四分类整理（政策依据/数据支撑/参考案例/表述参考），每条记录标题、来源、可支撑的结论——这就是后续素材清单的雏形。
5. 检索异常/空结果：停止，向用户说明哪个搜索项出问题，请用户确认下一步（重试/调整query/跳过/改用用户材料/明确同意改用外部搜索）。

## Step 3 内容包

按 [`references/content-pack.md`](../references/content-pack.md) 编制 `content-pack.md`：核心信息、叙事模式、页面规划（每页类型/标题/要点/素材ID）、素材清单（带来源）、风格预设（按 [`references/style-presets.md`](../references/style-presets.md) 推荐默认+备选）。此时项目短名（拼音或英文）应已确定，后续文件命名沿用。

## Step 4 提纲版溯源核验报告（执行过检索时必做）

把提纲固化为**带角标的答案文件**并生成提纲版报告——与成稿版同一脚本（`render_trace_html.py`）、同一形式，让用户在确认结构方案的同时逐条核验事实依据。编制规范见 [`references/material_usage.md`](../references/material_usage.md) 第三节。

1. 编制提纲答案文件 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/<项目短名>_outline.md`，三部分：
   - **演示元信息**：受众与场合、叙事模式、风格预设、画布、页数；
   - **页面规划表**：页 | 类型 | 标题 | 事实要点（四列，不设单独「依据」列——依据由要点内 `[N]` 角标直接承载，单独罗列属冗余）。**每条事实性要点（政策名、数字、案例、时间点）后标 `[N]` 角标**，N 为素材清单检索编号；结构页/观点页要点写「无」；
   - **口径事项清单**：需用户留意的问题（统计口径差异、外省材料定位、待补检索项），逐条带角标——这是提纲版的核心价值，把「待确认」变成可点击核验的书面记录。
2. 生成（`--stage outline`，报告标题后缀由渲染器自动附加「溯源核验报告（提纲版）」）：

```bash
python3 {skillDir}/scripts/render_trace_html.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_语义名.json \
  --title "<演示标题>" \
  --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/<项目短名>_outline.md \
  --question "用户原始需求" \
  --stage outline
```

报告首屏为**核验报告单**：依据溯源、引用绑定、时效检查、类型覆盖、提纲自检五项指标 + 建议人工复核项，全部由脚本真实计算（缺链接显示待补、未绑定标红、自检未记录不装通过）。**生成前硬校验**：答案正文没有任何 `[N]` 角标时脚本拒绝生成并报错——修正答案文件后重跑，不得绕过。

3. **多轮检索**（多个 NN JSON）：先手工合并为一个 JSON 供本步与成稿版使用——**推荐顶层结构** `{"检索文章": [...], "knowledgeBase": "...", "self_check": {...}?, "verification_checks": [...]?}`（渲染器同时兼容原始接口的 `content.data.检索文章` 嵌套形态，两种都认）。把各 JSON 的 `检索文章` 数组按素材清单 `[M]` 编号顺序合并（数组合并顺序即角标顺序，答案文件角标按此顺序书写）、`角标` 字段重排为清单编号，并按素材清单给每条材料加 `类型` 字段（政策依据/数据支撑/参考案例/表述参考，供核验报告单「类型覆盖」指标与来源卡色系使用）；`knowledgeBase` 保留任一非空值；可选在顶层写 `self_check`（提纲自检 5 项如实结果，键可用中文，值支持 `pass`/`通过：说明`/`✓`）与 `verification_checks`（需人工复核事项清单，逐条透传展示）。素材清单编号是角标唯一基准。渲染器兜底：若合并 JSON 未带 `角标` 字段，`render_trace_html.py` 按数组位置 1..N 自动编号（一条材料一张来源卡），因此**合并顺序必须与素材清单编号顺序一致**。合并时逐条检查原文链接：接口偶有材料不带 `源网址`，**交付前必须先尝试人工补链**（经权威官方入口核实后把真实 URL 填入 `源网址` 或 `policyUrl` 字段）；确实无法补到的（材料下线、无公开 URL）才保留提醒交付，**禁止伪造链接**。
4. **编制纪律**：提纲中每个数字、政策名、案例必须能通过角标回溯到来源原文；挂不上角标的事实要点删除表述、降为概括表述、或列入口径事项清单标注「待补检索」，不得裸写。**角标只能指向合并 JSON 中真实存在的素材编号**——用户提供的不可核验素材禁止挂角标（幽灵角标会被核验报告单判为「未绑定」红色警示，导致核验不通过），以文字标注「用户提供 · 未经权威核验」并写入口径事项清单即可。
5. **模式差异**：材料模式下，检索覆盖部分正常角标，纯用户材料要点在口径事项清单标注「用户提供 · 未经权威核验」；免检索模式不生成本报告，Step 5 确认门如实说明「提纲未经权威核验」。
6. **dsh 交付说明**：报告落 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/`，已在会话工作区内、dsh 文件视图与访达均可见，直接向用户展示该路径即可，无需交付复制。

## Step 5 结构方案确认门 ⛔

向用户展示（Markdown 分节，不塞长段落）：

- 核心信息与叙事模式
- 页面规划总览（页序 + 每页标题 + 页类型）
- 关键素材及来源摘要
- 推荐风格预设 + 1-2 个备选 + 画布格式
- 提纲版溯源核验报告路径，并说明：「提纲中每条政策、数据和案例都已在报告中挂接权威来源，可点击逐条核对原文；另有 N 条口径事项需要你确认（见报告口径事项一节）。」

用户确认或调整后，方可创建项目。调整时先更新内容包与提纲答案文件、重新生成报告，再过本门。

## Step 6 创建项目与逐页手写 SVG

```bash
dknowc-projects/<项目名>/        # 工作区级项目目录（跨会话延续）；项目名用主题短名（拼音或英文）
├── content-pack.md
├── sources/                  # 用户自带材料（如有）
├── images/                   # 页面引用的图片（如有）
├── svg_output/               # ★ 逐页手写的约束 SVG
├── validation/               # 质检报告（脚本自动写）
└── exports/                  # 最终 .pptx 与两版溯源核验报告
```

项目创建后，把 Step 4 生成的提纲版报告从 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/` 复制归档到 `dknowc-projects/<项目名>/exports/<演示名>_提纲核验报告.html`。

SVG 创作严格遵循 [`references/svg-authoring.md`](../references/svg-authoring.md)（元素契约、排版纪律、图表画法、禁止清单）与已确认风格预设。

节奏：**P01 完成后即请用户确认首页**——dsh 的 Web 界面无法直接预览 .svg 文件，用预览脚本生成 HTML 预览页（落会话产物目录，工作区可见），请用户在浏览器打开预览页确认：

```bash
python3 {skillDir}/scripts/preview_slide_html.py <项目名>
```

预览页路径以脚本实际打印为准（`dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/output/<项目名>_pages_preview.html`）。也可以先跑一次首页质检。确认后其余页不间断写完；全部页面完成后可用同一脚本重新生成全页预览（覆盖旧文件）供用户快速翻阅。写完顺手把页面引用的素材ID核对一遍。

## Step 7 质检与编译导出

```bash
# 质检（quick 无锁模式；--stage final --json 生成正式报告，导出的前置条件）
python3 {skillDir}/scripts/svg_quality_checker.py dknowc-projects/<项目名> --quick-generate --stage final --json

# 编译导出（原生 DrawingML）
uv run --with python-pptx --with XlsxWriter python3 {skillDir}/scripts/svg_to_pptx.py dknowc-projects/<项目名> --quick-generate
```

注意：导出脚本要求先存在**通过的 final 质检报告**（`validation/svg_quality_report.json`），所以质检必须带 `--stage final --json` 且退出码为 0，再执行导出。首页确认阶段可用不带 `--stage final` 的快速检查。

- 质检 exit 1（errors）：逐条修复 SVG 后重跑；warnings 评估后可放行。
- 导出成功后 `.pptx` 位于 `dknowc-projects/<项目名>/exports/`。
- 可选转场：`-t fade` 等参数仅用户明确要求动效时使用；默认不传。

## Step 8 成稿版溯源核验报告（执行过检索时必做）

把「最终演示的页面级结论文本」整理为答案文件（含 `[素材ID]` 角标对应关系说明），连同检索 JSON 生成成稿版报告（`--stage final`；自检项改为成稿口径：事实有据/质检通过/无占位残留/图表有来源注/口径一致，可经合并 JSON 顶层 `self_check` 传入）：

```bash
python3 {skillDir}/scripts/render_trace_html.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_xxx.json \
  --title "<演示标题>" \
  --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/<项目短名>_answer.txt \
  --question "用户原始需求" \
  --stage final
```

输出 HTML 复制到 `dknowc-projects/<项目名>/exports/<演示名>_成稿核验报告.html`。规则见 [`references/material_usage.md`](../references/material_usage.md)。

## Step 9 交付（三件套）

- **交付干净原则（先修后交）**：交付给用户的两份核验报告必须处于「核验完成」状态——可修复问题（角标未绑定、JSON 结构不符、可补的原文链接、`self_check` 未写入）一律先修复重渲再交付，不得带着可修复问题交给用户；只有不可抗力缺口（官方入口确实无法补链）允许保留提醒，且交付时说明原因。
- 主交付物：`dknowc-projects/<项目名>/exports/<演示名>.pptx` 路径 + 一句简短说明。
- 执行过检索时附两份报告路径并说明其为辅助核验文件、不是正文附件：
  - `<演示名>_提纲核验报告.html`（提纲阶段事前核验）；
  - `<演示名>_成稿核验报告.html`（交付阶段事后溯源）。
- **dsh 交付**：三件套全部位于工作区（`dknowc-projects/<项目名>/exports/`，工作区级、访达可直达），直接向用户展示路径即可，无需交付复制。
- 不发送 SVG 源文件、内容包草稿、质检报告等中间产物，除非用户明确要看。
- 询问是否需要调整（改文字/换风格/调页序）：调整走内容包 → SVG → 重导出的闭环，不直接改 .pptx。
