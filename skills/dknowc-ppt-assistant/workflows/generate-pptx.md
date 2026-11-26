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
- 需要检索的任务（主题模式、材料模式补检索）要求 `api_key_configured=true`；未配置时按 SKILL.md「统一 API Key 管理」引导，不得改用外部搜索（未开通检索就没有降级链，退路只有材料模式＋待核验标注）。

## Step 2 深知检索（主题模式；材料模式仅补缺口）

1. 设计检索方案：覆盖政策依据、数据支撑、参考案例必要维度（表述参考不单列）；写明搜索地域、每条 query 原文、素材类型、使用边界。**Query 构造原则**：句式「`<对象>`（含地域、时间限定）的 `<关注方向>`」——各路只是**关注方向**不同（政策路写「…政策」、数据路写「…发展情况」、案例路写「…做法」），同一路内不叠加多维限定、一个对象配一个关注方向；**禁止类目关键词堆砌**（如「新能源汽车 政策 补贴」散列）与**括号列举具体信息需求**（把「产业规模、重点企业、存在问题」列进括号会把检索面收窄、牺牲召回质量，具体内容交由深知搜索在对象范围内自行覆盖）——这两种都是坏例；已知目标文件名时直接用标题原文做 query。**补搜 query 与之区分**：补搜求精度不求广度，带时间+地域+对象/文件类型精确限定。方案向用户展示每条 query 原文（确认的=执行的）。面向用户展示时不得出现脚本参数名。
2. **【检索方案确认门 ⛔】** 展示方案，等待用户确认或调整。确认话术：「我建议先按下面方案检索权威素材，请确认是否执行，或告诉我需要增删哪些搜索项。」
3. 用户确认后执行，**统一走脚本通道**（`trusted_search.py`，MCP 通道已停用）：每路独立 `--output`，单批不超过 4 路，单次调用内后台并行、`wait` 全部结束后逐路检查结果；失败的路单独串行重试一次，不得整批反复重发；任意一路额度用尽即整批停止按额度规则处理；平台或接口明显限流〔多路同时报错〕时回退逐路串行。**每路结果即时落地是并行的前提**：每路返回后立即单独落盘并校验该 JSON（文件存在且业务码正常），未落盘校验通过前不得发起下一路；**禁止"先把结果攒在对话里、等整批完成后统一落盘"**——宿主对工具结果有清理机制，延迟落盘的结果会过期无法读取。"上一批完成"的定义＝每路 JSON 文件存在且校验通过，不以调用已返回为准；落盘失败当场重写，从执行轨迹恢复属最后手段、非常规路径。

```bash
python3 {skillDir}/scripts/trusted_search.py "检索问题" --search-type 单值 --service-area 单个地域 --eff-time 单个时间点 --json-only --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_语义名.json
```

**V2 检索通道（v1.4.0 起）**：端点为可信搜索 V2，`--search-type` **每次调用必填单值**——按素材类型映射：**政策依据路传 `policy`**（文章级发文字号基本只在 policy 路返回）、**数据支撑与参考案例路传 `govSite`**（`affair`/`qa` 实测 0 篇不用，`private` 未开通）；**混传报错**——需要多类来源就分路调用后合并（混传会共用结果名额、稀释政策文件与文号覆盖）。默认参数已定档 `segmentCount=4`、`MaterialLength=18000`（受控实测最优，一般不改）；成功判定 `ret==0 且 content.code==200`，业务错误（HTTP 200 + 中文 msg）不落盘直接按报错处理。

4. 检索结果按素材四分类整理（政策依据/数据支撑/参考案例/表述参考），每条记录标题、来源、可支撑的结论——这就是后续素材清单的雏形。
5. 检索异常/空结果：**先区分场景**——空结果/支撑不足的素材维度先按「联网检索降级链」降级（库内补搜 → 可信联网 → 宿主 WebSearch，外部材料统一标非官方来源进报告），降级后仍缺或方向不符才停下向用户说明并确认下一步（重试/调整 query/跳过/改用用户材料）；接口报错/额度用尽等异常按上一条错误码处理，不得自动联网绕过。

## Step 3 内容包

按 [`references/content-pack.md`](../references/content-pack.md) 编制 `content-pack.md`：核心信息、叙事模式、页面规划（每页类型/标题/要点/素材ID）、素材清单（带来源）、风格预设（按 [`references/style-presets.md`](../references/style-presets.md) 推荐默认+备选）。此时项目短名（拼音或英文）应已确定，后续文件命名沿用。

### 联网检索降级链（三阶段：库内 → 可信联网 → 宿主 WebSearch）

**默认只查深知库内**（上面各路 + 缺口驱动补搜）。某素材维度（政策依据/数据支撑/参考案例）**补搜后仍无结果、核心数据或政策依据无直接支撑、或结果与主题方向不一致**时，视为「搜不到」，逐级降级——**不得因"有返回条数"就停**：

1. **阶段二（可信联网）**：独立调用（不与库内路混传）：
   ```bash
   python3 {skillDir}/scripts/trusted_search.py "<用户主题相关的检索词>" --search-channel webSearch --json-only --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_web.json
   ```
   返回真实互联网网页正文段落＋源网址（可溯源到原段）；联网路材料自动标 `非官方来源`、带 `数据权威性`，报告自动打「非官方来源」徽标。
2. **阶段三（宿主 WebSearch）**：阶段二零结果、只覆盖相反方向、或核心事实仍无支撑时，用宿主自带 WebSearch 检索（用户主题＋定向变体），把原始结果按契约落 JSON（`{"query": "...", "results": [{"title","url","content","published_at","source"}]}`，无摘录的条目会被丢弃），然后转换合并：
   ```bash
   python3 {skillDir}/scripts/websearch_convert.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_websearch_raw.json -o dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_websearch.json
   python3 {skillDir}/scripts/merge_search_results.py      --input dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_政策.json --search-key "政策依据路"      --input dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_数据.json --search-key "数据支撑路"      --input dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_web.json --search-key "公开资料补充"      --input dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_websearch.json --search-key "公开资料补充"      --output dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/merged.json
   ```
   **阶段二产物 `NN_web.json` 必须一并传给 merge**（没有阶段三产物时只传库内路＋阶段二路）——漏传会导致联网路材料不进材料池与报告。
3. **使用纪律**：
   - 外部材料只补库内缺失的事实，**核心数据、政策依据仍以库内/官方材料为主**；外部材料不得单独支撑关键数据页结论；
   - **非官方来源的数据不进原生图表**——图表位优先用库内权威数据；确需提及外部数据时以文字引用＋「非官方来源」标注表达，图表位标「数据待核验」或改定性表述；
   - 引用联网材料前剥离网页模板文字（导航/客服电话/面包屑）；
   - **涉外主题专项**：深知库暂不支持外国制度——涉外素材维度如实说明库不覆盖，按降级链处理并明示来源性质；**不得以中国侧政策冒充境外制度依据**（如以「外国人来华免签」充当「赴外签证」素材）；境外/外方主题若阶段二只召回中国侧或相反方向材料，视为未命中，继续阶段三；
   - **禁止**：跳过库内直接联网；把 WebSearch 结果只写进对话不落 JSON 不进报告；把外部材料当"已核验"依据交付而不标注。

## Step 4 提纲版溯源核验报告（执行过检索时必做）

把提纲固化为**带角标的答案文件**并生成提纲版报告——与成稿版同一渲染内核（插件内兄弟 skill「溯源核验报告生成器」dk-trace-report 通用内核 + 本包 `config/trace_report.config.json`）、同一形式，让用户在确认结构方案的同时逐条核验事实依据。编制规范见 [`references/material_usage.md`](../references/material_usage.md) 第三节。

**运行目录（1.7.0 起）**：报告管线把中间产物与报告写在会话工作区的独立运行目录，**不得写进 skill 安装目录**（脚本会直接拒绝）：

```bash
RUN="dknowc-output/${DSH_SESSION_ID:0:8}/runs/$(date +%Y%m%d-%H%M%S)-<项目短名>"
mkdir -p "$RUN"
```

1. 编制提纲答案文件 `dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/<项目短名>_outline.md`，三部分：
   - **演示元信息**：受众与场合、叙事模式、风格预设、画布、页数；
   - **页面规划表**：页 | 类型 | 标题 | 事实要点（四列，不设单独「依据」列——依据由要点内 `[N]` 角标直接承载，单独罗列属冗余）。**每条事实性要点（政策名、数字、案例、时间点）后标 `[N]` 角标**，N 为素材清单检索编号；结构页/观点页要点写「无」；
   - **口径事项清单**：需用户留意的问题（统计口径差异、外省材料定位、待补检索项），逐条带角标——这是提纲版的核心价值，把「待确认」变成可点击核验的书面记录。
2. 生成（两步：统一入口 → 渲染；`--stage outline`，报告标题后缀由配置自动附加「（提纲版）」）：

```bash
# ① 检索/merge 产物 → 通用 JSON（build_trace_input = 统一入口 + 本产品透传）
python3 {skillDir}/scripts/build_trace_input.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_语义名.json \
  --run "$RUN" --output input_outline.json \
  --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/<项目短名>_outline.md \
  --question "<用户原始需求全文>" \
  --stage outline

# ② 渲染（配置固定用本包 config/trace_report.config.json）
python3 {skillDir}/../dk-trace-report/scripts/render_trace_html.py "$RUN/input_outline.json" \
  --run "$RUN" \
  --config "{skillDir}/config/trace_report.config.json" \
  --title "<演示标题>" \
  --stage outline \
  --output "<演示名>_提纲核验报告.html"
```

报告首屏为**核验报告单**：结构核验（依据溯源 / 引用对应 / 材料新旧，脚本真实计算）+ AI 验收（提纲自检四项：事实有据/素材清单齐/口径一致/无占位残留，缺项点名、明细可展开）+ 建议人工复核项；正文为连续文档流，句后引文胶囊点击原地展开溯源卡；接口返回的原文链接**原样给出**（不做连通性检测），接口提供存档快照时作为附加回看入口。**两轨验收门禁**：任一轨不过渲染器退出 1、不生成 HTML（退出 2 为参数/路径错误）——修正答案文件或补齐 `self_check` 后重跑，不得绕过。

3. **多轮检索**（多个 NN JSON）：**优先用 `scripts/merge_search_results.py` 程序化合并**（`--input` 逐路传入＋`--search-key` 分组名＋`--output`；自动去重合并段落、生成显式 `编号`、官方与外部同材料近似重复时官方整体胜出、联网/外部路自动带「非官方来源」标记）；仅单路检索或工具不可用时才按下述规则手工合并——**推荐顶层结构** `{"检索文章": [...], "self_check": {...}?, "verification_checks": [...]?, "检索记录": [...]?}`（统一入口同时兼容原始接口的 `content.data.检索文章` 嵌套形态，两种都认）。**执行过补搜的必须写 `检索记录`**：每条 `{purpose, query, 通道（主检索/补搜）, new_articles, added_paragraphs}`——`new_articles`/`added_paragraphs` 按**合并前后差值**如实计算（合并前先数一遍文章数与段落总数，合并后再数，差值即增量；不是估的）。`build_trace_input.py` 会把它归一为 `search_meta.calls` 传给渲染器，过程条明细行展示「新增 X 篇 · 补充 Y 段」——补搜有没有用一眼可见；不写则按无补搜渲染（历史 JSON 兼容）。把各 JSON 的 `检索文章` 数组按素材清单 `[M]` 编号顺序合并（数组合并顺序即角标顺序，答案文件角标按此顺序书写）、`角标` 字段重排为清单编号（材料「类型」字段已退出报告与统计，1.7.0 起不再需要为核验单标注类型）；**必须在顶层写 `self_check`（提纲口径四项：事实有据/素材清单齐/口径一致/无占位残留，每项写结构化对象 `{"verdict":"pass|fail|pending","basis":"…","evidence":["[n] 条款/文号/日期…"]}`，声明"通过"必须带可回查证据——无要素记「证据不足」，与显式 `fail` 一并拦在交付前）**与 `verification_checks`（需人工复核事项清单，逐条透传展示）。素材清单编号是角标唯一基准。**合并时同一篇文章只留一条**（按标题+源网址去重；多路召回常带重复片段，重复录入会让报告出现成批同名卡）；渲染器侧也按归一化「标题+来源网址」去重兜底——同一篇文章只出一张卡，若它在清单里占多个编号（同文异号），卡上会并列显示全部编号（如 `[8][13]`），正文引用任一编号都能定位。渲染器兜底：若合并 JSON 未带 `角标` 字段，渲染器按数组位置 1..N 自动编号，因此**合并顺序必须与素材清单编号顺序一致**。合并时逐条检查原文链接：接口偶有材料不带 `源网址`，**交付前必须先尝试人工补链**（经权威官方入口核实后把真实 URL 填入 `源网址` 或 `policyUrl` 字段）；确实无法补到的（材料下线、无公开 URL）才保留提醒交付，**禁止伪造链接**。
4. **编制纪律**：提纲中每个数字、政策名、案例必须能通过角标回溯到来源原文；挂不上角标的事实要点删除表述、降为概括表述、或列入口径事项清单标注「待补检索」，不得裸写。**角标要素分挂**：一句话里同时出现文号、发文日期、文件名、条款号时，各要素分别挂到**载有该要素**的材料上（文号挂在文号来源、数据挂在数据来源），不得把全部要素都挂到主题相关的第一篇材料。**角标只能指向合并 JSON 中真实存在的素材编号**——用户提供的不可核验素材禁止挂角标（幽灵角标会被核验报告单判为「未绑定」红色警示，导致核验不通过），以文字标注「用户提供 · 未经权威核验」并写入口径事项清单即可。
5. **模式差异**：材料模式下，检索覆盖部分正常角标，纯用户材料要点在口径事项清单标注「用户提供 · 未经权威核验」；免检索模式不生成本报告，Step 5 确认门如实说明「提纲未经权威核验」。
6. **dsh 交付**：报告生成后落在会话工作区 `$RUN/`（`dknowc-output/<会话ID前8位>/runs/<任务>/`，脚本打印绝对路径），dsh 以工作区为文件视图、访达也可直达——直接向用户展示该路径，请用户点开确认提纲即可，无需交付复制。

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
dknowc-projects/<项目名>/            # 项目名用主题短名（拼音或英文）
├── content-pack.md
├── sources/                  # 用户自带材料（如有）
├── images/                   # 页面引用的图片（如有）
├── svg_output/               # ★ 逐页手写的约束 SVG
├── validation/               # 质检报告（脚本自动写）
└── exports/                  # 最终 .pptx 与两版溯源核验报告
```

项目创建后，把 Step 4 生成的提纲版报告从 `$RUN` 复制归档到 `dknowc-projects/<项目名>/exports/<演示名>_提纲核验报告.html`。

SVG 创作严格遵循 [`references/svg-authoring.md`](../references/svg-authoring.md)（元素契约、排版纪律、图表画法、禁止清单）与已确认风格预设。

节奏：**P01 完成后即请用户确认首页**——宿主环境（WorkBuddy 等）或用户无法直接查看 SVG 时，用预览脚本生成 HTML 预览页并复制到宿主工作区，请用户在预览页确认：

```bash
python3 {skillDir}/scripts/preview_slide_html.py <项目名>
P01 预览页已落会话工作区（脚本打印绝对路径），需要时直接向用户展示该路径。
```

本地环境可让用户直接打开 SVG 或预览页；也可以先跑一次首页质检。确认后其余页不间断写完；全部页面完成后可用同一脚本重新生成全页预览（覆盖旧文件）供用户快速翻阅。写完顺手把页面引用的素材ID核对一遍。

## Step 7 质检与编译导出

> **命令基准目录**：本文件所有命令都在 **skill 根目录**下执行（`{skillDir}` 即该目录绝对路径）；`dknowc-projects/<项目名>` 为相对该目录的路径，跨目录调用时改用绝对路径。

```bash
# 质检（quick 无锁模式；--stage final --json 生成正式报告，导出的前置条件）
python3 {skillDir}/scripts/svg_quality_checker.py dknowc-projects/<项目名> --quick-generate --stage final --json

# 编译导出（原生 DrawingML）
uv run --with python-pptx --with XlsxWriter python3 {skillDir}/scripts/svg_to_pptx.py dknowc-projects/<项目名> --quick-generate -o "dknowc-projects/<项目名>/exports/<演示名>.pptx"
```

注意：导出脚本要求先存在**通过的 final 质检报告**（`validation/svg_quality_report.json`），所以质检必须带 `--stage final --json` 且退出码为 0，再执行导出。首页确认阶段用 `--stage first-page` 做单页快速检查（不带 `--stage` 时脚本默认按 `final` 全量处理）。

**质检判据与循环纪律（硬规则）**：

1. **通过判据＝退出码 0 且 `errors=0`**。报告状态 `passed-with-warnings` **就是通过**——warnings（样式偏好类提示）**一律不阻断**导出与交付，不得以「还有 warnings」「截图看着不够好」为由继续修改。
2. **质检→修复→再质检循环最多 3 轮**；每轮只修 `errors` 与**明显事实性错误**（错别字、数字错、张冠李戴）。3 轮后仍有 errors 才停下向用户说明阻塞项。样式偏好类 warning 一律不修，交付时如用户问起再按报告如实说明。
3. **导出后不回头**：final 质检通过并导出 `.pptx` 后，直接进入成稿报告与交付（后续步骤），**禁止**再跑质检、再看页面截图、再微调文字重导——截图视觉自检只在 P01 确认门使用。重跑仅限**用户明确提出修改**时（走内容包→SVG→重新质检导出的闭环）。
4. 导出产物使用固定目标文件名（如 `<演示名>.pptx`）：导出命令必须带 `-o "dknowc-projects/<项目名>/exports/<演示名>.pptx"`；不带 `-o` 时脚本按「项目名_时间戳」命名、交付路径与清单不符。导出脚本自动备份 `svg_output`，无需手动留多版本。

- 质检 exit 1（errors）：逐条修复 SVG 后重跑（计入 3 轮上限）。
- 导出成功后 `.pptx` 位于 `dknowc-projects/<项目名>/exports/`。
- 可选转场：`-t fade` 等参数仅用户明确要求动效时使用；默认不传。

## Step 8 成稿版溯源核验报告（执行过检索时必做）

把「最终演示的页面级结论文本」整理为答案文件（含 `[素材ID]` 角标对应关系说明），经统一入口生成成稿版报告（`--stage final`；自检项为**成稿口径五项**：事实有据/质检通过/无占位残留/图表有来源注/口径一致）：

```bash
# ① 检索/merge 产物 → 通用 JSON（成稿版）
python3 {skillDir}/scripts/build_trace_input.py dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/NN_xxx.json \
  --run "$RUN" --output input_final.json \
  --answer-file dknowc-output/${DSH_SESSION_ID:0:8}/official-docs/search-results/<项目短名>_answer.txt \
  --question "<用户原始需求全文>" \
  --stage final

# ② 渲染
python3 {skillDir}/../dk-trace-report/scripts/render_trace_html.py "$RUN/input_final.json" \
  --run "$RUN" \
  --config "{skillDir}/config/trace_report.config.json" \
  --title "<演示标题>" \
  --stage final \
  --output "<演示名>_成稿核验报告.html"
```

**两轨验收（不合格不出报告）**：渲染器先跑结构轨（依据溯源/引用绑定）与 AI 轨（`self_check`），**任一轨不过直接退出 1、不生成 HTML**——未通过就解决问题（修角标、补证据、修口径）后重渲，不得绕过或降级输出。`self_check` 写合并 JSON 顶层（或单独 JSON 经 `--self-check-file` 传入），**每项必须是结构化对象**：

```json
"self_check": {
  "事实有据": {"verdict": "pass", "basis": "关键结论逐条核对角标摘录支撑",
               "evidence": ["[1] 杭人常〔2024〕3号第二条", "[2] 2025-07-15 同比 5.3%"]},
  "质检通过": {"verdict": "pass", "basis": "质检退出码 0 且 errors=0",
               "evidence": ["质检报告 <日期> errors=0"]},
  "无占位残留": {"verdict": "pass", "basis": "全文无占位符", "evidence": ["成稿检查记录 <日期> final"]},
  "图表有来源注": {"verdict": "pass", "basis": "每个图表均标注来源角标", "evidence": ["[2] 图表来源注已核"]},
  "口径一致": {"verdict": "pass", "basis": "统计口径前后一致", "evidence": ["[2] 初步核算数口径"]}
}
```

- **声明"通过"必须带可回查证据**（材料编号 `[n]`/条款号/文号/日期/标准号任一），无要素记"证据不足"、按结构违约拦截；`"fail"` 否决整体；`"pending"` 只作待人工复核（不阻断）。旧的 `"通过：说明"` 字符串仍兼容，但无要素时同样记证据不足。
- **五项如实写全**：`self_check` 未写入时核验单显示「未记录」不阻断，但交付干净原则要求交付物不得处于未记录状态——有未闭环项先补齐再写自检，不得带着未通过交付。
- **角标要素分挂**：一句话里的文号、发文日期、文件名、条款号必须分别挂到**载有该要素**的材料上，不得全挂到主题相关材料——AI 轨「事实有据」的抽查必须覆盖文号/日期要素。

输出 HTML 归档到 `dknowc-projects/<项目名>/exports/<演示名>_成稿核验报告.html`（`$RUN` 生成后复制归档）。规则见 [`references/material_usage.md`](../references/material_usage.md)。

## Step 9 交付（三件套）

- **交付干净原则（先修后交）**：交付给用户的两份核验报告必须处于「核验完成」状态——可修复问题（角标未绑定、JSON 结构不符、可补的原文链接、`self_check` 未写入）一律先修复重渲再交付，不得带着可修复问题交给用户；只有不可抗力缺口（官方入口确实无法补链）允许保留提醒，且交付时说明原因。
- 主交付物：`dknowc-projects/<项目名>/exports/<演示名>.pptx` 路径 + 一句简短说明。
- 执行过检索时附两份报告路径并说明其为辅助核验文件、不是正文附件：
  - `<演示名>_提纲核验报告.html`（提纲阶段事前核验）；
  - `<演示名>_成稿核验报告.html`（交付阶段事后溯源）。
- **交付清单只含上面这三件**（`dknowc-projects/<项目名>/exports/` 下；P01 预览页按需可选）：
  - **每个产物只交付一份**——不得把 `$RUN` 内的运行时报告与 `exports/` 归档件同时交付（否则用户无法判断该看哪一份）；
  - **所有中间产物一律不交付**：检索 JSON、提纲/成稿答案文件、内容包、SVG 源文件、质检报告、`$RUN/` 内的 input JSON 与临时报告（统一口径：交付物只有最终产物）；
  - 交付清单**逐个显式列出文件绝对路径**，不用通配符、不整目录交付；交付前核对工作区里就是这几件、无多余同名文件。
- **dsh 交付**：产物直接生成在会话工作区——`.pptx` 与两份核验报告在 `dknowc-projects/<项目名>/exports/`，报告中转件在 `$RUN`（`dknowc-output/<会话ID前8位>/runs/<任务>/`）。dsh 以工作区为文件视图、访达也可直达，直接向用户展示上面三件的绝对路径即可，无需交付复制；交付前核对交付清单这三件齐全、无多余同名文件。

**补交规则**：用户在已交付三件套之后追加要求（如"再给我一份无角标的讲稿版 Word"），**只交付新要求的文件**——不重渲染已交付的核验报告、不重复复制已有产物；只交付新要求的文件路径，`.md`/JSON 等中间产物一律不交付（dsh 产物天然在工作区，无复制环节）。
- 不发送 SVG 源文件、内容包草稿、质检报告、`$RUN/` 内的临时报告与 input JSON 等中间产物，除非用户明确要看。
- 询问是否需要调整（改文字/换风格/调页序）：调整走内容包 → SVG → 重导出的闭环，不直接改 .pptx。
