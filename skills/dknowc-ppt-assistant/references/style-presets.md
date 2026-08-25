# 风格预设（style-presets）

深知可信PPT内置风格预设，在「结构方案确认门」向用户展示推荐与备选；用户明确指定时优先。每个预设以 spec_lock 同构的结构描述（画布/配色/字体/版式纪律），主 Agent 手写 SVG 时严格遵循。

## 选择规则

1. 默认按用途映射：工作总结/日常汇报/会议报告 → `gov-simple`；数据/指标/政策对比 → `gov-data`；对外/跨单位汇报 → `business`；重大会议/纪念/授奖 → `formal`；宣讲/培训/授课 → `training`。
2. 用户明确说「商务风」「庄重一点」「图表多」等时按用户意图选择。
3. 非党政场景可选通用风格：瑞士极简（swiss-minimal，白底黑字红点睛）、暗色科技（dark-tech，深底亮字，慎用于机关场合）。

---

## gov-simple 党政简洁（默认）

日常汇报、工作总结、会议报告、专题汇报。

```yaml
canvas: { format: ppt169, viewBox: "0 0 1280 720", margins: "左右64 上下56" }
colors:
  bg: "#FFFFFF"
  secondary_bg: "#F4F4F4"
  primary: "#C00000"        # 机关红：标题横线、强调、序号
  accent: "#1F4E79"         # 深蓝：副题、图表第二色
  text: "#262626"
  text_secondary: "#666666"
  text_tertiary: "#999999"
  border: "#E5E5E5"
typography:
  title_family: '"Microsoft YaHei", sans-serif'      # weight 700
  body_family: '"Microsoft YaHei", sans-serif'
  cover_title: 72           # 封面主标
  title: 32                 # 页标题
  subtitle: 20
  body: 18
  annotation: 13            # 来源注释、页码
discipline:
  - 60-30-10：白底≥60%，深字~30%，红≤10%
  - 页标题下加 3px 红色短线（x=64, 宽56）
  - 版面克制：无圆角、无渐变、无阴影；信息密度中偏低，一页一个观点
  - 页脚右下「NN / 总页数」11px 灰
```

## gov-data 数据图表

专项数据汇报、年度指标、政策对比、趋势分析。

```yaml
canvas: { format: ppt169, viewBox: "0 0 1280 720" }
colors:
  bg: "#FFFFFF"
  primary: "#1F4E79"        # 深蓝为数据主色（数据场景以蓝为基）
  accent: "#C00000"         # 红仅用于关键结论/警戒值
  chart_series: ["#1F4E79", "#2E75B6", "#8FAADC", "#C00000"]
  text: "#262626"; text_secondary: "#666666"; border: "#E8E8E8"
typography: { title: 30, subtitle: 20, body: 16, annotation: 13, hero_number: 44 }
discipline:
  - 每页一图一结论：图表区占版面≥55%，结论句压在下部
  - 关键数字用 hero_number 大号呈现
  - 图表下必须标「数据来源：XXX」13px 灰
  - 同一 deck 图表系列色一致，不混用色板
```

## business 商务汇报

对上级、外单位、跨单位汇报，商务演示。

```yaml
canvas: { format: ppt169, viewBox: "0 0 1280 720" }
colors:
  bg: "#FFFFFF"
  band: "#1F3864"           # 封面与章节页深蓝整幅色带
  primary: "#1F3864"; accent: "#2E75B6"
  text: "#333333"; text_secondary: "#7F7F7F"; border: "#E0E6ED"
typography: { cover_title: 64, title: 30, body: 17, annotation: 13 }
discipline:
  - 封面/章节页可用深蓝整幅色带+白字（内容页保持白底）
  - 双色系层次：深蓝标题 + 浅蓝支撑图形
  - 信息密度中高，允许更丰富的图形语言（仍禁渐变阴影）
```

## formal 庄重典雅

重大会议、纪念活动、授奖仪式、开幕式配套。

```yaml
canvas: { format: ppt169, viewBox: "0 0 1280 720" }
colors:
  bg: "#F8F6F0"             # 米白宣纸底
  primary: "#8C1F28"        # 暗红
  accent: "#B8860B"         # 金（少量：分隔线、纹样描边）
  text: "#2B2B2B"; text_secondary: "#8A867B"; border: "#E3DFD3"
typography:
  title_family: '"SimSun", "Songti SC", serif'   # 宋体系庄重
  body_family: '"FangSong", "STFangsong", serif'
  cover_title: 68; title: 30; body: 18; annotation: 13
discipline:
  - 米白底+暗红+金三色，金占比<5%
  - 版面严谨对称，标题居中为主
  - 大量留白，信息密度低；装饰只用细线与规则几何
```

## training 培训课件

政策宣讲、党建学习、业务培训、授课。

```yaml
canvas: { format: ppt169, viewBox: "0 0 1280 720" }
colors:
  bg: "#FFFFFF"
  primary: "#2E75B6"        # 蓝主调
  accent: "#C00000"         # 红强调（重点标注）
  text: "#262626"; text_secondary: "#666666"; band: "#F2F7FC"
typography: { title: 28, subtitle: 20, body: 17, annotation: 13 }
discipline:
  - 层级清晰：章节页/要点页/案例页分明
  - 重点用红字或红色下划线标注，每页≤2处
  - 留白充足便于记笔记；可重复使用「编号要点」版式
```

---

## 使用要求

- 风格一经确认，整个 deck 的配色、字体、页脚纪律**全局一致**；跨页不得漂移。
- 混合需求（如「庄重但要有数据」）以主场景定风格，次需求在版式内消化，不混用两个预设的色板。
- 用户单位有 VI 色时，可在确认门提出替换 primary/accent，其余纪律不变。
