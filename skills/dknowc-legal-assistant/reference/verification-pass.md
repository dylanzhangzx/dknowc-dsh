# 交付前独立复核（verification pass）

`verify_claims.py` + `check_answer.py` 是机器检查（只判结构与台账口径）；本步是**另一个复核视角**，专门抓“作者自己觉得自己对”的错误，产出直接喂给两轨自验收的 **AI 验收轨**（`legal_selfcheck.json` 的结构化五项）。复核员只拿材料、结论台账和草稿，不看作者自己写的五项自检。

## 什么时候跑

- `check_answer.py` 通过之后、`render_trace_html.py` 之前。
- 复杂题、含外部材料、含数量/金额/日期/分类判断的题必须跑。
- 复核不通过，回到答案修改；不要用 `absolute_review` 放行台账类问题。

## 输入

1. `legal_question_profile.json`：问题画像（地域/时点）。
2. `legal_source_cards.json`：材料画像（地域/来源等级/抓取状态）。
3. `legal_claims.json`：结论台账。
4. 草稿答案 `legal_answer.txt`。

## 复核提示词

```text
你是复核员，不是作者。不要相信草稿里的自检说明，也不要根据常识补全。
只根据我给你的材料原文和结论台账，逐条核对草稿中的每个结论。

对每条 claim 输出：
- id
- verdict: pass / fail
- 依据：材料中的原文片段（逐字）；找不到就写“未找到”
- 问题：数量、主体、范围、日期、口径、措辞哪一处不成立

重点检查：
1. direct：quote 是否在材料里；count 是否等于引文里（一）（二）……的实际项数。
2. calculation：日期/利息是否用 calc_period.py，days/convention/interest 是否与工具输出一致，答案是否写明“含首尾/算头不算尾”；纯算术是否用 calc_legal.py，mode/inputs 是否齐全，months_factor/amount/total/additional/value 是否与工具输出一致，是否写明封顶等假设。
3. negative：是否写“截至YYYY-MM-DD，公开渠道未见/未检索到”；禁止“未上调/未发生/不存在”；as_of/coverage 是否齐全。
4. inference：是否写“通常/一般/以属地……认定为准”；禁止“属于/就是”。
5. external：source_nature、as_of、jurisdiction 与 question_jurisdiction 是否齐全；外省材料是否被套到本省问题；只有次级媒体来源时是否有官方口径或“待核验”措辞。
6. 草稿里有没有台账外的规范性句子；有就标 fail，要求补台账或删除。
7. **角标要素分挂**：一句话里的文号、发文日期、文件名、条款号是否分别挂在**载有该要素**的材料上——《办法》条文不能拿来支撑文号，文号在通告里就挂通告。
8. **经验性统计**（“败诉率最高”“大多数法院”这类）没有材料支撑就判 fail，要求补来源或删掉——不加脚本规则，全靠这一步把关。

复核结论直接写入 `legal_selfcheck.json` 的结构化五项（`{"verdict": "pass|fail|pending", "basis": …, "evidence": [……]}`）；声明“通过”的证据必须带 `[n]`／`第X条`／〔20xx〕文号／日期／文件名／GB 标准号任一可回查要素。

只输出复核结果，不要改写答案，不要给法律建议。
```

## 输出

落盘 `<run>/legal_verify.json`（`verify_claims.py --run <run> --answer ...`，含 answer/evidence 指纹）：

```json
{
  "verdict": "pass",
  "items": [
    {"id": "c1", "verdict": "pass", "quote": "……"},
    {"id": "c2", "verdict": "fail", "issue": "答案写六项，原文七项"}
  ]
}
```

`verdict` 不是 `pass` 时不得生成最终报告；先改答案，再重跑本步。
