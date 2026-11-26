---
name: 溯源核验报告生成器
slug: dk-trace-report
display_name: 溯源核验报告生成器
displayName: 溯源核验报告生成器
summary: 把检索材料与带角标的答案生成统一版式溯源核验报告（含核验单、引用依据弹窗、知识专库）
category: 通用办公
version: "1.0.2"
author: 彩智科技
description: "当用户或宿主 Agent 需要把一批来源材料与一份带角标的答案，生成统一版式的溯源核验报告 HTML（含引用依据弹窗、知识专库、核验单）时使用。输入为一份通用 JSON（材料清单 + 答案），不依赖任何特定接口产物；各业务 Skill 只需把检索/研究结果的要素映射到这份 JSON 即可。"
---

# 溯源核验报告生成器

把任何 Skill 的"检索/研究结果 + 带角标的答案"渲染为统一版式的单文件溯源核验报告 HTML。

报告定位：不止展示"材料从哪来"（溯源），更要传达"我们查过了，可以交付"（核验）。

## 何时用

- 你的 Skill 做了检索/调研，需要给用户一份可逐条点开核验的交付报告；
- 公司要求各 Skill 输出统一的自验收/溯源核验报告（SKILL 大赛培训口径）；
- 不需要调任何深知接口——内容来源完全由你决定，本 Skill 只负责渲染与核验。

## 工作流（严格单输入）

渲染器**只认通用 JSON**；接口/merge 产物必须先经过统一入口 `build_report_input.py` 转换。

### 路线 A：已有检索/merge 产物（推荐给业务 Skill）

```bash
# 1. 接口/merge 产物 + 答案 → 通用 JSON（adapter=merged）
python3 {baseDir}/scripts/build_report_input.py "$RUN/merged.json" \
  --adapter merged \
  --answer-file "$RUN/answer.txt" \
  --question-file "$RUN/question.txt" \
  --self-check-file "$RUN/selfcheck.json" \
  --verify-file "$RUN/verify.json" \
  [--policy-files] \
  --run "$RUN" --output input.json

# 2. 渲染（业务 Skill 传入自己的配置；--output 由 Agent 命名，见下）
python3 {baseDir}/scripts/render_trace_html.py "$RUN/input.json" \
  --run "$RUN" \
  --output "<简短文件名>.html" \
  --config "$RUN/trace_report.config.json" \
  [--charts-json "$RUN/charts.json"] \
  [--stage outline|final]
```

**文件命名规则（Agent 负责）**：交付文件名由 Agent 通过 `--output` 指定——取自答案标题的 8-20 字短名（如「成都重庆西安养老金对比.html」），不出现问号截断、不用 `_v2`/时间戳/长问句；重跑仍传同一名字（run 目录覆盖，交付层才按版本编号）。未传 `--output` 时渲染器回退"问题截断 32 字"的自动命名，仅作兜底、不推荐。

### 路线 B：直接整理通用 JSON

自己按下方契约写出 `$RUN/input.json`（或经 `assembly` adapter 转换），然后直接渲染。

### 交付

`outputs/` 里唯一 HTML；聊天回复正文给出去角标干净版（不带 [n]）。

## 统一入口 build_report_input.py

| adapter | 输入形态 | 说明 |
|---|---|---|
| `merged`（默认） | 检索接口/merge 产物：`content.data.检索文章[]` 或顶层 `检索文章[]` | 逐条映射为 `materials`：`文章标题→标题`、`发布或实施机构→发布机构`、`段落→段落`、`源网址`、`screenShotPath→快照链接`、`搜索条件→检索分组`、`检索通道`、`可引用`、`待核验`、`发布日期可信度→可信度`；`--policy-files` 用 `policyFiles.writtenText` 回填空缺发文字号 |
| `assembly` | 公文写作的溯源装配 JSON：`materials[] / recalled_materials[] / document_content / self_check` | `material_name→标题`、`support→原文`、`source→发布机构`、`source_url→源网址`、`snapshot_url→快照链接`、`doc_number→发文字号`、`search_key→检索分组`、`verification→核验`、`recalled_materials→已引用=false`、`document_content→answer`、`self_check→selfCheck` |

通用参数：`--answer-file`（文件优先）/`--answer`、`--question`/`--question-file`、`--self-check-file`、`--verify-file`（嵌入为 `verifyRecord`）、`--title`、`--stage`、`--run`、`--output`。输出可直接作为渲染器 `input_json`。

**接口调整时只改 adapter，渲染器不动。**

## 通用输入 JSON 契约

```json
{
  "question": "用户原始问题",
  "title": "报告标题（可选；缺省用问题）",
  "answer": "答案正文（关键结论带 [1][2] 角标；也可用 --answer-file 传文件）",
  "materials": [
    {
      "编号": 1,
      "标题": "材料标题",
      "原文": "用于核验的摘录（必填；1.0.2 起缺摘录=结构违约，该材料不可作正文依据）",
      "段落": [ {"id":1, "标题":"章 > 节", "内容":"原段全文"} ],
      "源网址": "https://...",
      "快照链接": "https://...",
      "发布机构": "发文机关",
      "发布日期": "2026-01-01",
      "发文字号": "X政发〔2026〕X号",
      "来源性质": "official",
      "可信度": 0.92,
      "检索分组": "本轮检索",
      "检索通道": "可选，业务检索通道标记"
    }
  ],
  "selfCheck": {
    "fact_basis": {
      "verdict": "pass",
      "basis": "逐条核对适用对象与条件条款",
      "evidence": ["[1] X政发〔2026〕X号：第三条认定条件", "[2] 实施指引：比例要求原文"]
    },
    "binding": {"verdict": "pass", "basis": "抽查角标", "evidence": ["[1]"]},
    "consistency": {"verdict": "pass", "basis": "同一文件口径", "evidence": ["[1]"]},
    "freshness": {"verdict": "pass", "basis": "2026 年发布", "evidence": ["材料1 2026-01-01"]},
    "no_gap": {"verdict": "pass", "basis": "无未核验断言", "evidence": ["[2]"]}
  },
  "verifyRecord": {
    "verdict": "pass",
    "issues": [],
    "record": {"answer_digest": "...", "evidence_digest": "...", "verdict": "pass"}
  }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `question` | 建议 | 用户原始问题；用于报告文头与文件名 |
| `title` | 可选 | 报告标题；缺省用 question |
| `answer` | 必填（或 --answer-file） | 答案正文，关键结论带 `[n]` 角标 |
| `materials` | 必填 | 材料清单；也可叫 `材料` / `sources`；顶层是数组也接受 |
| `materials[].编号` | 建议 | 与答案 `[n]` 一一对应；缺省按数组顺序 1-based；重复报错退出 |
| `materials[].标题` | 必填 | 材料标题；别名 `title/name/文章标题` |
| `materials[].原文` | 必填 | 核验用摘录；1.0.2 起缺摘录计为结构违约（依据溯源不过，不出报告），不是软提醒 |
| `materials[].段落` | 可选 | 多段分块；每段 `标题` 用 `>` 分层级做面包屑 |
| `materials[].源网址` | 建议 | 无则标"无原文链接"软提醒（不影响已核验） |
| `materials[].快照链接` | 可选 | 存档快照回看入口 |
| `materials[].发布机构` | 建议 | 发文机关；别名 `issuer/发布机关` |
| `materials[].发布日期` | 建议 | 用于材料新旧核验行 |
| `materials[].发文字号` | 可选 | 别名 `docNumber/文号` |
| `materials[].来源性质` | 可选 | `official`（默认）/ `unofficial`（非官方，打徽标）。1.0.2 起来源等级：gov 域名或官方机构名的非官方材料判为「公开网络·官方」不打非官方徽标（白名单 `official_host_allow` 可加法定机构域名）；脚本不再因"仅非官方"否决报告，内容是否可靠由 AI 验收判 |
| `materials[].可信度` | 可选 | 数字徽标 |
| `materials[].检索分组` | 可选 | 知识专库 tabs 分组标签；缺省"本轮检索" |
| `materials[].已引用` | 可选 | `false` 表示召回未采用，进"未进入正文的参考材料"折叠区；专库按检索分组筛选时折叠区同步过滤，标题显示"本组未进入正文的参考材料（N）" |
| `selfCheck` | 可选 | 五项自检；键集可由配置替换；不传则核验单显示"未记录"。1.0.2 起每项支持结构化 `{"verdict":"pass\|fail\|pending","basis","evidence":[…]}`（`agentCheck` 为别名，旧字符串兼容）；声明"通过"但证据无可回查要素按 `evidence_missing` 结构违约拦截 |
| `verifyRecord` | 可选 | 业务 Skill 的域内核验记录（见下）；也可用 `--verify-file` 注入 |

## 报告配置 trace_report.config.json（--config）

各业务 Skill 只维护一份配置，不改渲染代码（示例见 `config/examples/*.json`）：

```json
{
  "brand": {
    "product_name": "深知法律助手",
    "footer_body": "{product} · 正文 ｜ 内容由 AI 生成，仅供参考",
    "footer_report": "{product} · 溯源核验报告 ｜ 内容由 AI 生成，仅供参考",
    "argparse_desc": "生成溯源核验报告 HTML（{product}）",
    "lib_foot_source": "来源：{product} · 每段摘录均取自原文原段",
    "lib_foot_external": "来源：{product} · 部分材料来自公开网络，已标注非官方来源，请以官方口径复核",
    "source_fallback": "{product}",
    "source_fallback_external": "{product}（含公开网络材料）",
    "report_title_prefix": "溯源核验报告",
    "default_page_title": "溯源核验报告"
  },
  "channels": {
    "route_keywords": {"deep": ["深度"], "trusted": ["可信"]},
    "labels": {"deep": "深度搜索", "trusted": "可信搜索"},
    "summary": {"deep": "深度搜索 {deep} 路", "trusted": "可信补搜 {trusted} 次", "fallback": "深知检索 {n} 路"},
    "step1_fallback": "深知检索",
    "internal_token_filter": ["联网", "可信联网", "宿主 WebSearch"],
    "tokens": {"深知可信搜索·联网": "深知可信搜索"}
  },
  "selfcheck": {"labels": {"fact_basis": "事实有据", "binding": "角标绑定", "consistency": "答案一致", "freshness": "时效确认", "no_gap": "无未核验断言"}},
  "agent_track": {"enabled": true, "require_evidence": true},
  "official_host_allow": ["mpfa.org.hk"],
  "stage": {"enable": true, "labels": {"outline": "提纲版", "final": "成稿版"}},
  "charts": {"enable": true},
  "verify": {"enabled": true, "required": false}
}
```

- `brand`：产品名、页脚、来源行回退、报告标题前缀；模板支持 `{product}` 占位。
- `channels`：通道关键词（deep/trusted/web）、过程条标签与摘要模板、内部词过滤、token 映射、无分组时步骤一文案；可选 `user_facing_replacements`（`[[源词, 替换词], …]`）覆盖自检说明词表（替换为单遍执行，结果不参与二次匹配）。
- `selfcheck.labels`：自检键集与显示名（如公文的"事实有据/结构完整/无占位残留/无AI味/格式合规"）。
- `agent_track`：AI 验收轨开关与证据要求（默认开；`require_evidence=false` 退回 1.0.1 行为）。
- `official_host_allow`：官方外部信源白名单（法定机构自有域名，默认含 mpfa.org.hk；业务按属地增删）。
- `stage`：双版报告（PPT 提纲版/成稿版）；`--stage outline` 时标题追加显示名。
- `charts.enable`：图表能力开关（默认开，仍需 `--charts-json` 才画）。
- `verify.enabled/required/compare_digests`：域内核验记录是否必传（法律/税务设 required=true）；`compare_digests=false` 时只采信 verdict/issues、不比对记录指纹（业务侧 digest 口径未对齐时使用）。

`--config` 相对路径按调用时工作目录解析；配置值只作为文本经转义输出，不能注入 HTML/脚本。

## 域内核验 --verify-file

业务 Skill 用自有核验器（如 verify_claims）产出记录，渲染时并入核验单：

```json
{"verdict": "pass|fail", "issues": ["..."], "record": {"answer_digest": "...", "evidence_digest": "...", "verdict": "pass"}}
```

- `verdict=fail` → 判"核验未通过"；
- `record` 的 `answer_digest`/`evidence_digest` 由 `trust_digest.py` 计算并与当前答案/材料比对，不一致 → 核验记录失效（`required=true` 时判未通过，否则软提醒）；
- `issues` 全部并入"查看核验明细"。

**digest 口径**（业务侧核验器须与之一致，否则会"永远 stale"）：

- `answer_digest`：答案规范化（角标按首次出现重排为 1..N，其余原样）后取 SHA-256；
- `evidence_digest`：`materials` 全集中 `(编号, 源网址去尾斜杠)` 的有序集合 JSON 的 SHA-256（含未引用材料）；
- 口径暂无法对齐时，在配置中设 `verify.compare_digests=false`，只采信 `verdict`/`issues`。

## 图表 --charts-json（opt-in）

传入图表 JSON（run 目录内文件名或内联 JSON）后，图表并入本报告（ECharts 内联，单文件离线可开）；`metadata.section` 匹配章节标题则插进该章节，否则独立"数据可视化"章节。资源缺失或数据不足时整块略过，不阻断报告。

## 角标契约

- 答案 `[n]` 的 n = `materials[n-1]`（1-based）；必须边写边标，禁止写完再补标；
- 渲染器把展示编号按首次出现顺序重排为 [1][2][3]…，但绑定关系在写入时已定死；
- 答案有 `[n]` 但 `materials` 里没有对应编号 → **拒绝生成**（exit 1）；
- 来源非空但答案完全无角标 → **拒绝生成**（exit 1）；
- 聊天回复不得出现 `[n]` 角标——角标只存在于 HTML 内。

## 两轨验收（1.0.2）

报告合格 = **结构核验（脚本轨）∧ AI 验收（Agent 轨）**，任一轨不过渲染器 `SystemExit(1)` 不写 HTML——交付物只有"已核验"一种形态，发现问题就修复后重跑，不把问题报告交给用户。

### 分工

| 轨 | 谁判 | 判什么 | 不过的后果 |
|---|---|---|---|
| 结构核验 | 脚本 | 角标全部绑回来源文章、每条正文依据有可展开摘录、不可引用材料不作依据、自检格式合法且"通过"带可回查证据、域内核验记录指纹有效 | `exit 1`，不生成 HTML |
| AI 验收 | Agent | 内容是否被原文支持（数字/标准号/地域/金额对象/措辞等语义判断），按五项自检提交结论与证据 | 显式 `fail` 或证据缺失 → 拦在交付前 |

**脚本不做任何内容判断**（1.0.2 起 `claim_audit` 内容轨已移除，无 hints）；**AI 轨不能翻案脚本轨**——脚本判错必须修脚本或修输入，不能靠自检写"通过"掩盖。

### selfCheck 结构化契约

每项自检推荐写结构化对象（旧字符串写法兼容，但声明"通过"必须带可回查证据）：

```json
{
  "fact_basis": {
    "verdict": "pass",
    "basis": "逐条核对适用对象与条件条款（做了什么判断）",
    "evidence": ["[1] X政发〔2026〕X号：第三条认定条件", "[2] 实施指引：比例要求原文"]
  },
  "binding": {"verdict": "pass", "basis": "抽查角标", "evidence": ["[1]"]},
  "consistency": {"verdict": "pending", "basis": "待第二轮复核"}
}
```

- `verdict`：`pass` / `fail` / `pending`。`fail` 否决报告；`pending` 只计待复核、不否决；
- `evidence` 必须含**可回查要素**（任一即可）：`[n]` 材料编号、`第X条` 条款、`§`、`〔20xx〕X号` 文号、日期/年份、文件名、`GB` 标准号；
- 声明 `pass` 但证据为空话（无可回查要素）→ `evidence_missing`，按结构违约拦截并点名缺项；
- 旧写法 `"通过：说明（沪府规〔2025〕8号第五条）"` 兼容：文字里有可回查要素即算有据，没有则同样拦下——**裸写"通过"不再能过门禁**；
- `agentCheck` 是 `selfCheck` 的别名；自检键集由 `selfcheck.labels` 配置（公文/PPT/法律/税务各有自己的五项）。

### 报告呈现

核验单分两段：**结构核验**（依据溯源 / 引用对应 / 材料新旧）+ **AI 验收**（`AI 验收 N/5 有据`，缺项点名、明细折叠展示每项的 结论·依据·证据）。来源卡只保留有事实依据的徽标：高可信、公开网络·官方／非官方来源、✓ 可作为正文依据；材料类型标签与"材料构成"行自 1.0.2 起不再展示（接口类型字段与实际文体常年不符，界定成本高、对读者无决策价值）。

### 相关配置

```json
{
  "agent_track": {"enabled": true, "require_evidence": true},
  "official_host_allow": ["mpfa.org.hk"]
}
```

`agent_track.require_evidence=false` 退回 1.0.1 行为（只认通过/未通过、不查证据要素），供不需要留证的业务方；`official_host_allow` 为官方外部信源白名单（法定机构自有域名），业务 Skill 可按属地增删。

## 运行目录

所有产物写入 `$RUN`；`--run` 指向 Skill 安装目录会被拒绝。**中间产物不编号**：内部重跑覆盖 $RUN 内同名报告/JSON（被否掉的草稿不占版本号）；dsh 下产物直接在会话工作区交付（无独立交付复制环节），需保留多版本时由调用方在 `--output` 命名。绝对 `--output` 只拒绝 Skill 安装目录。

## 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功（两轨验收全部通过） |
| 1 | 两轨验收未通过，不生成 HTML：角标绑不上/无角标、正文依据缺摘录或不可引用、AI 验收有 `fail` 或声明通过但证据不可回查（`evidence_missing`）、域内核验未通过或记录失效 |
| 2 | 输入/参数/路径错误：非通用 JSON、文件不存在、编号重复、配置不可读、路径越界 |

## 调用方式

- 用普通 `python3 scripts/xxx.py` 调用（脚本依赖同目录相对导入）；不要用 `python3 -I`（隔离模式会移除脚本目录导致 import 失败）。
- 材料为空（0 条）时渲染器拒绝生成（exit 2）——无材料即无溯源对象，属明确设计，不产出"无来源报告"。

## 打包边界

本 skill 随 dknowc-dsh 插件分发，包含 `SKILL.md`、`scripts/`、`resources/`、`config/examples/`、`reference/`；发布检查与变更记录由维护仓库保存，不入插件包。

## 与其他 Skill 的关系

本 Skill 是**上游单源**：各业务 Skill 发布时把 `scripts/`（渲染内核 + 入口 + 核验底座）、`resources/` 与示例配置物理内置进自己的包；用户只装业务 Skill 一个包，运行时不依赖本 Skill。上游改样式/口径后，各业务 Skill 人工触发、按版本拉取适配（异步、不改代码、只换同步文件与配置）。
