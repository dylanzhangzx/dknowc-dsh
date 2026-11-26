# 答案与报告规范（answer-and-report）

## 答案结构（固定五段）

1. **结论**：一两句话直接回答；写明适用纳税年度（如"2023 年 1 月 1 日至 2027 年 12 月 31 日期间…"）。
2. **适用条件**：身份（小规模/一般纳税人/居民个人）、金额标准、行业、期限、例外；逐条列。
3. **政策依据**：文件全称 + 文号 + 发布日期 + 条款/段落，每条挂角标 `[n]`；文号缺失的镜像副本降级标注（只写标题+日期+源网址）或换带文号副本。引用标注：政策依据用「发文机构：XX」，数据支撑/参考案例用「来源：XX」，不写「数据源：XX」。
4. **算例**（如涉计算）：逐项写出公式与数字；税率表/速算扣除数标年度与文件依据；提交前重算一遍。
5. **需要你确认**：用户没给但影响结论的事实（收入构成、扣除项目、是否预缴、纳税年度、所在地）。

## 措辞红线

- 原文与解释分开：条文没有的推论必须标"按通常口径"或删除；
- 绝对化表述（只能/唯一/一定/全部/一律/一旦…）要么有封闭列举依据，要么改写；
- 0 条写"本次未召回"，不写"无相关政策"；
- 版本措辞不进交付：不写"版本待复核""库内标记失效"，用"该文件发布于 X 年 X 月，适用以最新公告为准"这类用户语言；
- 地方口径：没有当地文件时写"以当地税务机关/社保经办口径为准"，不把某地做法推广到全国。

## 生成前强制检查

```bash
python3 scripts/check_answer.py \
  --answer ./runs/<任务>-<时间>/tax_answer.txt \
  --selfcheck ./runs/<任务>-<时间>/tax_selfcheck.json
```

退出码 0 才继续；命中项改写，或在 selfcheck 的 `absolute_review` 按行号逐条说明（对象，键=行号）。注意管道会吞退出码，直接跑、别接 `| tail; echo $?`。

## 自检五项（AI 验收轨，写入 selfcheck JSON）

五项键：`fact_basis`（每个结论有材料依据）/ `binding`（引用绑定到载有该依据的材料）/ `consistency`（结论间无矛盾）/ `freshness`（年度/时效已核对，引用的是目标年度口径）/ `no_gap`（用户问题无遗漏子问题）。

**结构化契约（1.8.2 两轨验收）**：每项写 `{"verdict": "pass|fail|pending", "basis": "判定说明", "evidence": ["可回查证据", …]}`；旧字符串写法（`"通过：说明"`）兼容，但说明文字会被当作唯一证据。**声明"通过"但 evidence 里没有可回查要素（`[n]` 材料编号／`第X条` 条款号／`〔20xx〕` 文号／日期／年份／文件名／GB 标准号）→ 渲染按"证据不足"拦截，不出报告**。`fail` 否决；`pending`（待人工复核）不否决。示例：

```json
{
  "fact_basis": {"verdict": "pass", "basis": "每个结论逐字核对到材料段落",
                 "evidence": ["[2] 《财政部 税务总局公告2023年第19号》第一条"]},
  "binding":    {"verdict": "pass", "basis": "角标挂到载有该依据的材料", "evidence": ["[2]"]},
  "consistency":{"verdict": "pass", "basis": "结论间无矛盾", "evidence": ["[2] 全文单结论"]},
  "freshness":  {"verdict": "pass", "basis": "已核对适用年度", "evidence": ["2023年1月1日至2027年12月31日"]},
  "no_gap":     {"verdict": "pass", "basis": "子问题无遗漏", "evidence": ["[2] 免征范围已覆盖"]}
}
```

**角标要素分挂**：一句话里的文号/发文日期/文件名/条款号必须分别挂到**载有该要素**的材料上——《办法》条文不能用来支撑文号（文号在通告里就挂通告）；AI 验收"角标绑定"抽查必须覆盖文号/日期要素。

外部材料（阶段二联网/阶段三宿主 WebSearch）相关自检：
- **来源等级（2026-11-24 口径）**：外部官方信源（gov 域名/官方机构名）可作正文依据，卡片标「公开网络·官方」，不作问题；正文依据**全部为第三方信源**时，`fact_basis` 的 basis 写明"全部为第三方信源，建议以官方口径复核"（报告会出提醒）；
- 正文每个外部引用必须有徽标（「公开网络·官方」或「非官方来源」，渲染器自动）与源网址；报告正文页出现"本页部分材料来自公开网络…"提示条；
- 自检说明与用户可见文本不出现"阶段二/三""可信联网""宿主 WebSearch"等内部词；「非官方来源」是正式徽标用语。

自检说明里的日期一律写"YYYY年M月D日"（如 2023年1月1日），不写连写数字——2026-11-06 实测出现过"2023001起执行"笔误；提交前把 selfcheck JSON 的说明字段扫一遍再渲染。

## 角标与引用契约

- `[n]` = 合并产物里的材料 `编号` 字段（`merge_search_results.py` 输出），不要按数组位置数；
- 角标挂在**直接载有该依据**的材料上；找不到就补搜或写"未检索到直接依据"；
- claim 的 `quote` 逐字；允许省略号，不得改条件、数字、主体、期限；同条但书/例外一并纳入；
- quote 写前把前 10 个字在检索 JSON 里 grep 到再写（防凭记忆写"很熟"的条文）；
- **答案正文不写 Markdown `>` 引用块**（内核无此分支，会按普通段落渲染出字面 `>`）；原文由角标「引用依据」弹窗/材料卡回看。

## 渲染与交付

```bash
RUN=./runs/<任务>-<时间>
CFG=<Skill目录>/reference/trace_report.config.json

python3 scripts/merge_search_results.py --run "$RUN" \
  --input tax_search_label.json --search-key "带标签检索" \
  --input tax_search_nolabel.json --search-key "无标签对照" \
  --output tax_merged.json

# 渲染内核（上游「溯源核验报告生成器」）只认通用 JSON，先转换再渲染
python3 {baseDir}/../dk-trace-report/scripts/build_report_input.py "$RUN/tax_merged.json" \
  --run "$RUN" --output input.json

python3 {baseDir}/../dk-trace-report/scripts/render_trace_html.py "$RUN/input.json" \
  --run "$RUN" \
  --output "<答案标题 8-20 字短名>.html" \
  --config "$CFG" \
  --answer-file tax_answer.txt \
  --verify-file tax_verify.json \
  --self-check-file tax_selfcheck.json \
  --question-file tax_question.txt

（dsh：产物已在会话工作区，直接展示路径）
```

- 单文件三页：正文（去角标干净版）／溯源核验报告（默认落点）／知识专库；
- **两轨门禁**：结构核验或 AI 验收任一不过，渲染器退出 1 不写 HTML——按 stderr原因修正后重跑，不产出问题报告；
- 核验状态只认 `tax_verify.json`：`record`（answer/evidence 摘要，trust_digest 口径）与当前答案/材料不一致即判“核验记录与当前答案不一致”拦截；不传 `--verify-file` 按“缺少核验记录”未通过处理；
- run 内重跑**直接覆盖同名**；交付文件名用 8-20 字短名，不带 `_v2`/时间戳/长问句；
- 交付只给 HTML：`tax_answer.txt`、`tax_verify.json` 留在运行目录备查，不复制成 `.md` 交付；
- 自检不写死计数（材料数/引用数由报告统计）；不写材料编号（渲染器会重编号，用"《文件名》第X条挂在载有该条的材料"描述）；
- 运行目录内中间文件用短标识 `tax_question.txt` / `tax_answer.txt` / `tax_selfcheck.json`；中间产物不按版本编号。

## 带标签 0 条时的答案写法

> 本次带「税务」标签检索未召回到结果（已重试一次）。以下结果来自不带标签的独立检索，两次检索记录都附在溯源报告中。
