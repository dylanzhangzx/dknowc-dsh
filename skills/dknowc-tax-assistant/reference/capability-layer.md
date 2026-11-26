# 能力层：问题画像 → 材料画像 → 结论图 → 通用校验

这条链路不是"再加一条针对错题的规则"，而是把答案拆成可校验的对象。顺序固定：

```text
问题
  ↓
tax_question_profile.json     问题画像（地域/时点/税种/纳税人身份/优惠/申报期/用户要什么）
  ↓
tax_source_cards.json         材料画像（地域/机关/文件类型/来源性质/抓取状态）
  ↓
tax_claims.json               结论图（每条结论挂来源、地域、时点、税种、类型）
  ↓
tax_verify.json               通用校验（地域/税种/时点/来源/引文/计算/否定/推断）
  ↓
tax_answer.txt → HTML
```

四个产物都写在会话工作区的运行目录：首次用 `--out ./runs/<任务>-<时间>` 建目录，后续用 `--run` 打开同一目录；`--output` 只接裸文件名，同名不覆盖。输出指向 Skill 安装目录（含 `official-docs/`）直接拒绝。

## 1. 问题画像

```bash
python3 {baseDir}/scripts/question_profile.py \
  --question "2026年北京市大兴区小规模纳税人月销售额10万元以下还免征增值税吗？" \
  --as_of 2026-11-10 \
  --out ./runs/20261120-B01-1 --output tax_question_profile.json
```

输出字段：

- `jurisdiction`：问题地域。省级问题写到省；区县问题写省市县；全国问题写"全国"（税务问题默认全国口径）。
- `as_of`：截至日期。
- `domain`：`税务` / `社会保险`（可同时）。
- `tax_types`：税种（增值税、企业所得税、个人所得税、房产税、社会保险费……）。
- `taxpayer_types`：纳税人身份（小规模纳税人、一般纳税人、小型微利企业、个体工商户、自然人、灵活就业人员……）。
- `incentives`：优惠事项（免征、减征、加计扣除、留抵退税、困难减免……）。
- `filing`：申报/征期（按月、按季、年度汇算、预缴、申报期限……）。
- `policy_years`：问题里点名的年度。
- `doc_types`：法律/行政法规/部门规章/规范性文件/政策解读/新闻报道。
- `entities`：文件全称、引用短语、关键名词。
- `requested`：税率/标准、适用条件、申报期限、计算、政策依据、最新/现行、办理流程、优惠资格、逐项。
- `scope_notice` / `out_of_scope`：涉港澳台/外国税制时置位，答案只答内地一侧。

Agent 也可以手写 profile，再用 `--input` 校验；但 `jurisdiction` 和 `as_of` 不能空。同时把用户原话另存 `tax_question.txt`；`render_trace_html.py --question-file` 优先用它。若误传了 profile JSON，渲染器只取其中的 `question` 字段。

## 2. 材料画像

检索结果合并后运行：

```bash
python3 {baseDir}/scripts/source_cards.py \
  --input ./runs/20261120-B01-1/tax_merged.json \
  --profile ./runs/20261120-B01-1/tax_question_profile.json \
  --out ./runs/20261120-B01-1 --output tax_source_cards.json
```

每篇材料变成：

```json
{
  "id": "s1",
  "title": "财政部 税务总局关于增值税小规模纳税人减免增值税政策的公告",
  "issuer": "财政部 税务总局",
  "jurisdiction": "全国",
  "doc_type": "规范性文件",
  "source_grade": "官方库",
  "source_nature": "政府网站",
  "source_channel": "深知库内",
  "official": true,
  "published_at": "2023-08-01",
  "doc_number": "财政部 税务总局公告2023年第19号",
  "tax_types": ["增值税"],
  "fetch_status": "ok",
  "spans": ["……"]
}
```

硬规则：

- `fetch_status=failed` 的材料不能作为依据，也不能据此写"库内没有"；
- 省级/地方问题的材料地域必须是本地或"全国"；中央机关文件标题提到某省，仍归"全国"；
- 全国结论不得引用地方来源（河北的公告不能支撑全国口径）；地方结论也不得引用其他辖区来源；
- `source_grade`：库内=`官方库`；外部按 `source_nature` 取 `政府网站 / 官方媒体 / 次级媒体 / 未知`；
- `非官方来源=True` 只表示"不是深知库内材料"，**不等于网站本身不官方**：政府网站、官方媒体要如实区分，无法判断写"未知"，不要合并成"次级媒体/未知"；
- `source_nature` 只允许 `政府网站 / 官方媒体 / 次级媒体 / 未知`（内部画像字段，用于 verify_claims 判级与提醒；用户可见徽标按内核来源等级展示「公开网络·官方」／「非官方来源」）；`source_nature_status` 标明该值是接口显式给出（`explicit`）还是按机构/域名推断（`inferred`）；
- 外部材料 `data_authority` 一律为 `非权威`（不跟随接口 dataAuthority）；`library_material=false` 表示库外材料，`official` 仍按来源本身是否为政府网站/官方媒体判断；
- `issuer` 只取「发布或实施机构 → 发布机关」；不回退 `数据源`/站点名，缺失就留空，不从标题前缀推导；
- `doc_type` 区分政策原文、公告、解读、新闻报道，避免把新闻当条文；
- 一条 claim 同时引政府网站和媒体转引时，必须拆 claim 或写 `mixed_sources`（source_id → 来源性质），不能整体标成"政府网站"。

## 3. 结论图

`tax_claims.json` 的每条 claim 必须带 `id`、`type`、`text`。类型与必填字段：

| 类型 | 必填 |
|---|---|
| `direct` | `source_ids`、`quote`、`jurisdiction`；带数量时 `count`；建议 `tax_types` |
| `calculation` | `tool=calc_tax.py`（或 `calc_period.py`）、`mode`、计算输入与结果；滞纳金必须写 `convention=include-end/exclude-end`；必须写回工具结果：滞纳金 `days/amount`、不含税 `tax`、含税 `base/tax`、减免 `relief` |
| `negative` | `as_of`、`coverage`、`wording`（"截至……公开渠道未见……"） |
| `inference` | `wording`（通常/一般/以属地……认定为准） |
| `external` | `source_ids` 或 `url`、`source_nature`、`jurisdiction`、`question_jurisdiction`、`as_of`；次级媒体还要 `official_value` 或"待核验"措辞；混合来源写 `mixed_sources` |
| `interpretation` | `primary`、`alternative`、`selected_reason` |

税务 claim 示例：

```json
{
  "id": "c1",
  "type": "direct",
  "text": "2026年增值税小规模纳税人月销售额10万元以下（含本数）免征增值税",
  "source_ids": ["s1"],
  "jurisdiction": "全国",
  "tax_types": ["增值税"],
  "quote": "对月销售额10万元以下（含本数）的增值税小规模纳税人，免征增值税。",
  "count": 1,
  "answer_anchor": "月销售额10万元以下（含本数）"
}
```

```json
{
  "id": "c2",
  "type": "calculation",
  "text": "滞纳金=200000×0.05%×40天=4000元",
  "tool": "calc_tax.py",
  "mode": "late-fee",
  "convention": "include-end",
  "start": "2026-01-01",
  "end": "2026-02-09",
  "principal": "200000",
  "daily_rate": "0.0005",
  "days": 40,
  "amount": "4000.00",
  "answer_anchor": "滞纳金 4,000 元"
}
```

完整四类示例见 `reference/tax_claims.example.json`（直接/计算/否定/外部/推断/解释各一条）。没有 claim id 的规范性句子不允许写进答案。

## 4. 计算入口

```bash
# 滞纳金：本金 × 日率 × 天数
python3 {baseDir}/scripts/calc_tax.py --mode late-fee \
  --principal 200000 --daily-rate 0.05% \
  --start 2026-01-01 --end 2026-02-09 --day-count include-end

# 不含税基数算税
python3 {baseDir}/scripts/calc_tax.py --mode tax-exclusive --base 100000 --rate 1%

# 含税金额价税分离
python3 {baseDir}/scripts/calc_tax.py --mode tax-inclusive --amount 103000 --rate 1%

# 减免额
python3 {baseDir}/scripts/calc_tax.py --mode reduction --tax 10000 --reduction 50%
```

日期天数与利息仍可用 `calc_period.py`；税额、滞纳金、价税分离、减免额一律走 `calc_tax.py`，不心算。

## 5. 通用校验

```bash
python3 {baseDir}/scripts/verify_claims.py \
  --claims ./runs/20261120-B01-1/tax_claims.json \
  --sources ./runs/20261120-B01-1/tax_source_cards.json \
  --profile ./runs/20261120-B01-1/tax_question_profile.json \
  --answer ./runs/20261120-B01-1/tax_answer.txt \
  --out ./runs/20261120-B01-1 --output tax_verify.json
```

检查的是通用不变量，不是具体错题：

- claim / 来源 / 问题的地域是否一致（direct 也查来源地域：全国 claim 引用地方来源直接失败）；
- claim 税种是否与问题画像相交（都非空时）；
- 来源是否抓取失败；
- direct 的 quote 是否在 span 里、count 是否等于枚举数；
- calculation 是否等于 `calc_tax.py` / `calc_period.py` 的输出，滞纳金口径是否写明；
- negative 是否有截止日期和检索覆盖，wording 是否写成"截至……未见……"；
- inference 是否有"通常/一般/以属地……认定为准"；
- external 的来源性质是否够、次级媒体是否带官方口径/待核验；
- interpretation 是否同时给出 primary / alternative；
- 答案里的强断言（免征/免税/减半/不得享受/已经/属于……）是否有 `answer_anchor` 或引用角标。

`verdict` 非 `pass` 不得生成最终报告。

## 6. 报告核验状态（两轨验收，不合格不出报告）

渲染内核来自上游「溯源核验报告生成器」（整体继承，不改内核；配置走 `reference/trace_report.config.json`）。

**结论 = 结构核验（脚本）∧ AI 验收（Agent）；任一轨不过，渲染器退出 1 且不写 HTML**——未通过时应该解决问题，而不是输出问题报告；交付物只有“已核验”一种形态。

- **结构核验（脚本轨）**：角标全绑、每条正文依据有可展开摘录、不可引用材料不作依据、自检格式合法且“通过”带可回查证据、域内核验记录指纹有效（`tax_verify.json` 缺失/fail/失效即拦）。
- **AI 验收（Agent 轨）**：五项结构化 selfCheck（见 `answer-and-report.md`），`fail` 否决；声明“通过”但证据无可回查要素 → “证据不足”按结构违约拦截；`pending` 只待复核不否决。AI 轨不能翻案脚本轨。
- **来源等级**：外部官方信源（gov 域名/官方机构名，`is_official_external` 判定，白名单走 config `official_host_allow`）可作正文依据、标「公开网络·官方」；正文依据全部为第三方信源时出提醒。
- **脚本不做内容判断**：claim_audit 内容轨已随内核删除（无 hints）；数字/标准号/地域/金额对象/措辞等语义判断全部归 AI 验收。

**域内核验记录（`--verify-file`）**：`verify_claims.py` 落盘 `{verdict, issues, record:{answer_digest, evidence_digest, verdict}}`——`record` 由 `trust_digest.py` 计算（答案角标规范化摘要 + 证据 (编号,源网址) 集合摘要，证据侧复刻渲染器 renumber 后的编号），渲染时与当前答案/材料复算比对，不一致即“核验记录与当前答案/证据不一致”拦截；改了答案、补查换了材料必须重跑 `verify_claims.py` 再渲染，不允许拿旧记录出“已核验”。

## 7. 和 `check_answer.py` 的分工

- `verify_claims.py`：结论图校验，核心闸门。
- `check_answer.py`：措辞检查（绝对化、未注明假设、台账数量等），辅助闸门。

两个都过，才生成报告。画像/材料/结论/校验四个 JSON 与答案原文一并落盘，便于复核与问题复盘。
