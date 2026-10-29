# 公文格式标准索引

本目录包含 33 个公文格式标准文件（00–32），另附 99 常用句式，共 34 个文件；按照"只保留格式规范，释放模型能力"的原则设计。文种写法要点见 `reference/genre_writing_notes.md`；本目录只收格式标准。

---

## 标准文件列表

### 法定公文（按《党政机关公文处理工作条例》顺序）

| 编号 | 文件 | 文种 | 类型 | 行文方向 |
|-----|------|------|------|---------|
| 01 | [01_report.md](01_report.md) | 报告 | 上行文 | 下级→上级 |
| 02 | [02_qingshi.md](02_qingshi.md) | 请示 | 上行文 | 下级→上级 |
| 03 | [03_pifu.md](03_pifu.md) | 批复 | 下行文 | 上级→下级 |
| 04 | [04_tongzhi.md](04_tongzhi.md) | 通知 | 下行文 | 上级→下级 |
| 05 | [05_yijian.md](05_yijian.md) | 意见 | 可上可下 | 根据用途 |
| 06 | [06_han.md](06_han.md) | 函 | 平行文 | 不相隶属单位 |
| 07 | [07_minutes.md](07_minutes.md) | 会议纪要 | 平行文 | 内部使用 |
| 08 | [08_tongbao.md](08_tongbao.md) | 通报 | 下行文 | 上级→下级 |
| 09 | [09_tonggao.md](09_tonggao.md) | 通告 | 下行文 | 面向社会 |
| 10 | [10_gonggao.md](10_gonggao.md) | 公告 | 下行文 | 面向社会公众 |
| 16 | [16_decision.md](16_decision.md) | 决定 | 可上可下 | 根据用途 |
| 17 | [17_resolution.md](17_resolution.md) | 决议 | 会议文件 | 会议→发布范围 |
| 18 | [18_order.md](18_order.md) | 命令（令） | 下行文 | 发布机关→有关单位 |
| 19 | [19_gazette.md](19_gazette.md) | 公报 | 下行文 | 面向社会公众 |
| 20 | [20_motion.md](20_motion.md) | 议案 | 上行文 | 提请人大/常委会审议 |

### 常用文种

| 编号 | 文件 | 适用范围 | 说明 |
|-----|------|---------|------|
| 11 | [11_fuhan_approve.md](11_fuhan_approve.md) | 复函（无意见） | 平行文，同级机关 |
| 12 | [12_fuhan_objection.md](12_fuhan_objection.md) | 复函（有意见） | 平行文，同级机关 |
| 13 | [13_reminder.md](13_reminder.md) | 提醒函 | 下行文，上级→下级 |
| 14 | [14_generic.md](14_generic.md) | 通用公文 | 无特定文种时使用 |

### 事务文书

| 编号 | 文件 | 适用范围 | 说明 |
|-----|------|---------|------|
| 15 | [15_business_docs.md](15_business_docs.md) | 总结、计划、发言稿等（通用） | 继承通用公文标准 |
| 21 | [21_explanation.md](21_explanation.md) | 说明（情况/补充/原因说明） | 高频 |
| 22 | [22_application.md](22_application.md) | 申请（经费/资源/立项） | 高频 |
| 23 | [23_publicity.md](23_publicity.md) | 公示 | 公示事项+期限+异议渠道 |
| 24 | [24_procurement.md](24_procurement.md) | 采购公告 | 项目+预算+响应要求+联系人 |

### 工作材料

| 编号 | 文件 | 适用范围 | 说明 |
|-----|------|---------|------|
| 25 | [25_plan.md](25_plan.md) | 方案/实施方案/建设方案 | 目标+任务+责任+进度+保障+验收 |
| 26 | [26_summary.md](26_summary.md) | 工作总结/工作要点 | 周期复盘/阶段任务 |
| 27 | [27_speech.md](27_speech.md) | 讲话稿/致辞/述职 | 场合+身份+听众 |
| 28 | [28_rules.md](28_rules.md) | 制度/规定/办法/实施细则 | 章条结构 |
| 29 | [29_research.md](29_research.md) | 调研报告 | 事实支撑判断建议 |
| 30 | [30_feasibility.md](30_feasibility.md) | 可研报告 | 必要性+可行性+成本+风险 |
| 31 | [31_review_material.md](31_review_material.md) | 审查材料 | 对象+依据+发现+风险+整改 |
| 32 | [32_ai_compute.md](32_ai_compute.md) | AI 算力/技术服务 | 需求+测算+成本+SLA+安全 |

### 可选参考

| 文件 | 内容 | 说明 |
|-----|------|------|
| [99_expressions.md](99_expressions.md) | 常用句式、篇幅参考、结构框架 | 仅供参考，不强求使用 |

---

## 使用原则

### 1. 标准文件只包含格式规范

每个标准文件只包含：
- 文体分类（上行文/下行文/平行文）
- 格式规范（红头、标题、正文、落款）
- 最基本的结构说明

### 2. 内容限制已移至可选参考

以下内容已移至 `reference/standards/99_expressions.md`：
- 常用句式（如"为深入贯彻落实..."）
- 篇幅参考（如"500-1500字"）
- 详细的注意事项
- 结构框架
- 语言风格要求

### 3. 释放模型能力

AI在撰写公文时：
- **必须遵循**：格式规范（字体、字号、行距、缩进等）
- **自由发挥**：内容表达、句式选择、篇幅控制
- **可选参考**：`reference/standards/99_expressions.md`（不强求使用）

### 4. 事实克制

正式写作一律遵守 `reference/fact_discipline.md` 的事实边界约束；定稿前可按 `reference/anti_ai_patterns.md` 做语言复核。

---

## 快速查找

### 按场景查找

| 场景 | 推荐标准 |
|-----|---------|
| 向上级汇报工作 | [01_report.md](01_report.md) |
| 需要上级批准 | [02_qingshi.md](02_qingshi.md) |
| 回复下级请示 | [03_pifu.md](03_pifu.md) |
| 部署工作、告知事项 | [04_tongzhi.md](04_tongzhi.md) |
| 提出政策措施 | [05_yijian.md](05_yijian.md) |
| 与其他单位商洽 | [06_han.md](06_han.md) |
| 记录会议内容 | [07_minutes.md](07_minutes.md) |
| 表彰或批评 | [08_tongbao.md](08_tongbao.md) |
| 向社会公布事项 | [09_tonggao.md](09_tonggao.md) |
| 宣布重大事项 | [10_gonggao.md](10_gonggao.md) |
| 回复征求意见（无意见） | [11_fuhan_approve.md](11_fuhan_approve.md) |
| 回复征求意见（有意见） | [12_fuhan_objection.md](12_fuhan_objection.md) |
| 提醒下级注意 | [13_reminder.md](13_reminder.md) |
| 作出重大决定 | [16_decision.md](16_decision.md) |
| 会议审议通过事项 | [17_resolution.md](17_resolution.md) |
| 公布规章/任免/嘉奖 | [18_order.md](18_order.md) |
| 公开发布权威信息 | [19_gazette.md](19_gazette.md) |
| 提请人大/常委会审议 | [20_motion.md](20_motion.md) |
| 写总结、计划等 | [26_summary.md](26_summary.md) / [15_business_docs.md](15_business_docs.md) |
| 写情况说明 | [21_explanation.md](21_explanation.md) |
| 申请经费/资源 | [22_application.md](22_application.md) |
| 发布公示 | [23_publicity.md](23_publicity.md) |
| 发布采购公告 | [24_procurement.md](24_procurement.md) |
| 写方案/实施方案 | [25_plan.md](25_plan.md) |
| 写讲话稿/致辞/述职 | [27_speech.md](27_speech.md) |
| 写制度/办法/细则 | [28_rules.md](28_rules.md) |
| 写调研报告 | [29_research.md](29_research.md) |
| 写可研报告 | [30_feasibility.md](30_feasibility.md) |
| 写审查材料 | [31_review_material.md](31_review_material.md) |
| 写 AI 算力/技术材料 | [32_ai_compute.md](32_ai_compute.md) |

---
