# 底层能力层：问题画像 → 材料画像 → 结论图 → 通用校验

这条链路不是“再加一条针对错题的规则”，而是把答案拆成可校验的对象。顺序固定：

```text
问题
  ↓
legal_question_profile.json       问题画像（地域/时点/领域/实体/用户要什么）
  ↓
legal_source_cards.json           材料画像（地域/机关/文件类型/来源等级/抓取状态）
  ↓
legal_claims.json                 结论图（每条结论挂来源、地域、时点、类型）
  ↓
legal_verify.json                 通用校验（地域/时间/来源等级/引文/计算/冲突）
  ↓
legal_answer.txt → HTML
```

三个新脚本的 `--input/--profile/--answer` 读 skill 目录或会话 run 目录内文件；`--output` 只能写 `--run` 指定的会话 run 目录（或 `DKNOWC_RUN_DIR`）。**Skill 安装目录被直接拒绝**；不指定 run 目录时报错并给出用法，不落任何文件。

## 1. 问题画像

```bash
python3 {baseDir}/scripts/question_profile.py \
  --question "福建省泉州市安溪县2026年城乡居民基础养老金是多少？" \
  --as-of 2026-11-10 \
  --output legal_question_profile.json
```

输出字段：

- `jurisdiction`：问题地域。省级问题必须写到省；县级问题写省市县；全国问题写“全国”。
- `as_of`：截至日期。
- `domain`：劳动/借贷/消防/社保/税务等。
- `doc_types`：法律/行政法规/司法解释/地方政策/国家标准等。
- `entities`：法名、政策名、关键名词。
- `requested`：标准金额/依据文件/是否/计算/最新/逐项。

Agent 也可以手写 profile，再用 `--input` 校验；但 `jurisdiction` 和 `as_of` 不能空。

同时把用户原话另存 `legal_question.txt`；`render_trace_html.py --question-file` 优先用它。若误传了 `legal_question_profile.json`，渲染器现在只取其中的 `question` 字段，不会把整段 JSON 显示成“原问题”。

## 2. 材料画像

检索结果合并后运行：

```bash
python3 {baseDir}/scripts/source_cards.py \
  --input legal_merged.json \
  --profile legal_question_profile.json \
  --output legal_source_cards.json
```

每篇材料变成：

```json
{
  "id": "s1",
  "title": "……",
  "issuer": "河北日报",
  "jurisdiction": "河北省",
  "doc_type": "新闻报道",
  "source_grade": "次级媒体",
  "official": false,
  "published_at": "2026-11-08",
  "fetch_status": "ok",
  "spans": ["……"]
}
```

硬规则：

- `fetch_status=failed` 的材料不能作为依据，也不能据此写“库内没有”；
- 省级问题的材料地域必须是本省或“全国”；
- `source_grade` 为 `次级媒体` / `未知` 的，只能当线索，不能当法律条文结论；
- `source_nature` 只允许 `政府网站 / 官方媒体 / 次级媒体 / 未知`；无法判断写“未知”，不要合并成“次级媒体/未知”；
- `doc_type` 用来区分法律条文、政策文件、新闻报道，避免把新闻当条文；
- 一条 claim 同时引政府网站和媒体转引时，必须拆 claim 或写 `mixed_sources`（建议对象：source_id → 来源等级），不能整体标成“政府网站”。

## 3. 结论图

`legal_claims.json` 的每条 claim 必须带：

```json
{
  "id": "c1",
  "type": "external",
  "text": "有媒体报道称2026年福建省定基础养老金为208元（待核验）",
  "source_ids": ["s1"],
  "jurisdiction": "河北省",
  "question_jurisdiction": "福建省",
  "source_nature": "次级媒体",
  "as_of": "2026-11-10",
  "official_value": "福建省人社厅：2025-07-01起190元/月",
  "wording": "官方公开口径仍为190元/月；媒体报道208元，未见正式文件，待核验",
  "answer_anchor": "官方公开口径仍为190元/月"
}
```

类型：

| 类型 | 必填 |
|---|---|
| `direct` | `source_ids`、`quote`、`jurisdiction`；带数量时 `count` |
| `calculation` | 日期/利息：`tool=calc_period.py`、`convention`、`start/end/principal/annual_rate`，写回 `days/interest`，或 `aggregate_of` 指向其他 calculation claim；纯算术：`tool=calc_legal.py`、`mode`、`inputs`，写回 `amount/months_factor/total/additional/value` 至少一项 |
| `negative` | `as_of`、`coverage`、`wording` |
| `inference` | `wording`（通常/一般/以属地……认定为准） |
| `external` | `source_ids` 或 `url`、`source_nature`、`jurisdiction`、`question_jurisdiction`、`as_of`；次级媒体还要 `official_value` 或“待核验”措辞；混合来源写 `mixed_sources` |
| `interpretation` | `primary`、`alternative`、`selected_reason` |

没有 claim id 的规范性句子不允许写进答案。

## 4. 通用校验

```bash
python3 {baseDir}/scripts/verify_claims.py \
  --claims legal_claims.json \
  --sources legal_source_cards.json \
  --profile legal_question_profile.json \
  --answer legal_answer.txt \
  --output legal_verify.json
```

检查的是通用不变量，不是具体错题：

- claim / 来源 / 问题的地域是否一致；
- 来源是否抓取失败；
- direct 的 quote 是否在 span 里、count 是否等于枚举数；
- calculation 是否等于 `calc_period.py`（日期/利息）或 `calc_legal.py`（纯算术）的输出；
- negative 是否有截止日期和检索覆盖；
- inference 是否有“通常/以属地……认定为准”；
- external 的来源等级是否够、次级媒体是否带官方口径/待核验；
- interpretation 是否同时给出 primary / alternative；
- 答案里的强断言（确有/已经/属于/已上调/已执行/已补发）是否有 `answer_anchor` 或引用角标。

`verdict` 非 `pass` 不得生成最终报告。

## 5. 和 `check_answer.py` 的分工

- `verify_claims.py`：结论图校验，核心闸门。
- `check_answer.py`：措辞检查（绝对化、未注明假设、台账数量等），辅助闸门。

两个都过，才生成报告。
