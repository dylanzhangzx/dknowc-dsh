# 深知法律助手（dsh 版）

用深知的检索与政策数据接口处理法律需求：查法条、做法律问答、核对司法解释、核验合同/合规依据，最终交付一份可逐条回看原文的**溯源核验报告**。

本版本不内置 API Key：优先读环境变量 `DKNOWC_API_KEY`，宿主读不到时自动读本机专用配置文件 `~/.config/dknowc/api_key`（Windows 为 `%APPDATA%/dknowc/api_key`）；未配置时按 `reference/onboarding_scripts.md` 引导开通。

## 能力范围

- **法条模式**：已知法律名和条号时，`scripts/legal_search.py --law ... --article ...`（单条）或 `--articles 38,39,40,47`（多条，一次解析/下载/切条）依次调用
  - 001 政策条件筛选：按标题定位法律文件；
  - 003 政策历次版本：取最新修正日期；
  - 002/005 正文与全文下载：取全文；
  - 本地按“第X条”切分，返回条文原文。
- **语义模式**：不知道是哪部法时，`scripts/legal_search.py --query ...` 调 012 可信搜索 V2（`validityFilter=false`、条款级、`searchType=policy`）召回候选材料，再回到法条模式取精确原文。
- **检索降级**：库内无果时先用 `--search-channel webSearch`（深知联网），仍不足再用宿主 WebSearch；外部材料经 `websearch_convert.py` 转统一材料，内部标 `非官方来源=True`（含义：非深知库内材料），报告用户可见标签为“外部公开材料 · 政府网站/官方媒体/次级媒体”；LPR 等公开数据单列“外部数据”。
- **政策全文**：001 命中但正文没有“第X条”时，法条模式返回库内全文（`legal-policy-fulltext`），适用于“一、二、（一）”结构的地方政策；库内只有旧版时，用 WebSearch 核对新版并说明版本差异。
- **底层能力层**：问题画像 → 材料画像 → 结论图 → 通用校验；地域/时点/来源等级/引文/计算/冲突都在这层检查，不靠针对具体错题的正则。
- **选本规则**：排除 `EXPIRED_OR_REPEALED`；`OTHER` 暂按现行有效；用 003 的最新修正日期做正文标记校验，标题精确/成文日期/正文标记三者加权选出当前合并本。
- **交付形态**：直接答案 + 单文件 HTML（正文／溯源核验报告／知识专库三页，默认落溯源核验报告页），顶栏可导出 Markdown / PDF。

## 覆盖范围

- 中国大陆法律、行政法规、司法解释、部门规章、地方性法规与政策文件（以库内实际收录为准）。
- **不覆盖**：香港、澳门、台湾地区法律；新加坡及其他外国法；实时工商/征信/证券数据（需另接外部 MCP）。

## 目录

```
SKILL.md                     Skill 规则与工作流
scripts/
  initialize.py              初始化检查（Key 就绪）
  api_key.py                 Key 解析（环境变量 → ~/.config/dknowc/api_key）
  legal_client.py            001/002/003/005/012 接口客户端
  legal_search.py            法条模式 + 语义模式检索（含政策全文回退）
  calc_period.py             日期天数与利息计算（含首尾/算头不算尾）
  calc_legal.py              纯算术（经济补偿折算/年假300%/比例/倍数/封顶）
  question_profile.py        问题画像（地域/时点/领域/实体）
  source_cards.py            材料画像（地域/机关/来源等级/抓取状态）
  verify_claims.py           结论图通用校验（地域/引文/计算/冲突）
  check_answer.py            措辞检查 + 结论台账硬检查
  websearch_convert.py       宿主 WebSearch 结果转统一材料形态（外部公开材料/来源性质）
  render_trace_html.py       单文件溯源核验报告渲染器（上游单源内核）
  build_report_input.py      检索/合并产物 → 通用 JSON 入口适配
  run_paths.py               运行目录与产物路径（内核共用）
  merge_search_results.py    多路结果合并（多法/多条号）
  register_key.mjs           手机号验证码注册/查回 Key
  attribution.py             X-Dknowc-Attribution 来源声明
reference/                   开通引导、结论台账模板、独立复核提示词等
tests/                       回归测试（计算口径、结论台账、来源行）
resources/                   离线 ECharts（图表并入报告时使用）
会话工作区 run 目录（--run）  检索产物、画像、台账、校验记录与最终 HTML（不写 Skill 安装目录）
```

## 快速开始

```bash
python3 {baseDir}/scripts/initialize.py

python3 {baseDir}/scripts/legal_search.py \
  --law "中华人民共和国劳动合同法" --article 47 \
  --query "劳动合同法第四十七条经济补偿的计算标准" \
  --output legal_labor_47.json

# 同一部法多个条号：一次解析、一次下载、切出多条
python3 {baseDir}/scripts/legal_search.py \
  --law "中华人民共和国劳动合同法" \
  --articles 38,39,40,41,46,47,48,87 \
  --output legal_labor_multi.json

python3 {baseDir}/../dk-trace-report/scripts/build_report_input.py \
  --run ./runs/20261120-legal-01 legal_labor_multi.json --adapter merged \
  --answer-file legal_answer.txt \
  --question "劳动合同法第四十七条经济补偿的计算标准" \
  --self-check-file legal_selfcheck.json \
  --verify-file legal_verify.json \
  --output report_input.json

python3 {baseDir}/../dk-trace-report/scripts/render_trace_html.py \
  --run ./runs/20261120-legal-01 \
  --config scripts/trace_report.config.json \
  report_input.json \
  --output "劳动合同法第四十七条经济补偿标准.html"

（dsh：产物已在会话工作区，直接展示路径）
```

## 接口

- 001 政策条件筛选：`POST /open-api/maas/policy-data/v1/policies/filter`
- 002 政策正文：`POST /open-api/maas/policy-data/v1/policy-contents/get`
- 003 政策历次版本：`POST /open-api/maas/policy-data/v1/policy-versions/query`
- 005 正文下载：`GET /open-api/maas/policy-data/v1/policy-contents/download`
- 012 可信搜索 V2：`POST /open-api/maas/dependable/v2/search`

统一鉴权：请求头 `api-key`。所有请求携带 `X-Dknowc-Attribution`（来源统计用，不参与鉴权）。
