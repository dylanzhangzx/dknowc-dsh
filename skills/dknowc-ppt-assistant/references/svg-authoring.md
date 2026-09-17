# 约束 SVG 排版契约（svg-authoring）

本文件定义深知可信PPT的页面设计语言：主 Agent 逐页手写的受限 SVG 方言，以及导出为原生 PPTX 的规则。方言在第三方开源（MIT）SVG 页面设计边界基础上改编；完整示例见 `references/upstream-example/`。

## 一、核心契约

1. **`svg_output/` 是页面设计的唯一完整来源**：导出幻灯片上所有可见的文本、图形、图片、图表呈现，都必须出现在该页 SVG 中。模板和风格预设只是创作输入，不得向 SVG 之外「补」可见内容。
2. **主 Agent 逐页手写 SVG**：禁止编写脚本批量生成 `svg_output/` 页面。每页必须经过模型的设计推理。
3. **编译器不推断**：`svg_to_pptx.py` 只做确定性映射（SVG 元素 → 原生 DrawingML 对象），不补内容、不改结构。SVG 写什么，PPTX 就是什么。
4. **一页一文件，序号命名**：`01_cover.svg`、`02_*.svg`……序号+语义名，全局连续。

## 二、画布规格

| 格式 | viewBox | 适用 |
| --- | --- | --- |
| `ppt169`（默认） | `0 0 1280 720` | 标准汇报演示 |
| `ppt43` | `0 0 960 720` | 传统投影 |
| `xiaohongshu` | 小红书 3:4 | 图文帖 |
| `moments` | 1:1 | 方形海报 |
| `story` | 9:16 | 竖版故事/短视频封面 |
| `a4` | A4 竖版 | 打印物料 |

根元素必须同时写 `viewBox` 和 `width/height`，两者一致。

## 三、允许的元素与属性

**结构**：`<svg>`、`<g>`（带语义 id）、`<defs>`（仅限线性复用声明，不用 `<symbol>`+`<use>`）。

**图形**：`<rect>`、`<circle>`、`<ellipse>`、`<line>`、`<polyline>`、`<polygon>`、`<path>`（贝塞尔路径，复杂形状）。

**文本**：`<text>` + `<tspan>`。多行用 `<tspan x=".." dy="18">`，不用多个 text 堆叠。行内强调用 tspan 的 `font-weight`/`fill` 覆盖。

**图片**：`<image href="../images/xxx.png" x y width height>`，相对路径指向项目 `images/` 目录；必须带 `preserveAspectRatio`（整图 `xMidYMid meet`，裁切铺满 `xMidYMid slice`）。

**通用属性**：`x/y/cx/cy/r/width/height/points/d`、`fill`、`stroke`、`stroke-width`、`opacity`、`font-family`、`font-size`、`font-weight`、`fill`（文字颜色）、`text-anchor`、`letter-spacing`、`transform`（translate 为主）。

## 四、必须遵守的排版纪律

1. **语义分组**：每页按功能组织 `<g id="bg">`、`<g id="header">`、`<g id="content-xxx">`、`<g id="page-footer">` 等分组；同组元素一个用途。
2. **显式样式**：每个 `<text>` 必须写全 `font-family`（完整字体栈）、`font-size`、`fill`。不依赖继承默认值。
3. **纯色扁平**：只用十六进制纯色（`#RRGGBB`）。党政风格下禁止渐变、阴影、滤镜、圆角（`rx>0`）——这是原生转换保真度的前提，也是机关版式的克制要求。
4. **字体栈**：中文在前、西文在后、以 `sans-serif`/`serif` 收尾，XML 引号转义。示例：
   - 标题：`font-family="&quot;Microsoft YaHei&quot;, sans-serif"`
   - 党政庄重标题可映射为小标宋语义（导出后由打开端字体决定实际字形）
5. **安全边距**：默认左右 64px、上下 56px；页脚页码 `NN / 总页数` 放右下角 `text-anchor="end"`。
6. **页面注释**：每页 SVG 第一行加 `<!-- P0N 语义名 · 密度 · 布局类型 -->` 注释；图表区加 `<!-- chart-plot-area: x,y,w,h -->` 注释。这些注释不渲染，但便于质检与维护。
7. **文本即最终文本**：SVG 中的文字就是幻灯片上的文字，逐字校对，不写占位符。

## 五、图表的画法（图元自绘）

图表**不用语义标记魔法**，直接用 SVG 图元绘制（这是扁平原生导出最稳的路径）：

- **时间线**：`<line>` 轨道 + `<circle>` 节点 + 节点上下文本（见示例 `03_origin.svg`）
- **柱状图**：`<rect>` 柱体 + 数值 `<text>` + 基线 `<line>`
- **折线图**：`<polyline>` + 数据点 `<circle>`
- **饼图/环图**：`<path>` 扇形（A 命令）+ 图例色块
- **表格**：`<rect>`/`<line>` 网格 + 单元格 `<text>`；或整表区按行列对齐文本
- **流程/架构**：`<rect>` 框 + `<line>`/`<polygon>` 箭头

数据必须来自内容包中带来源的素材；图表下以小号注释文本标明「数据来源：XXX」。

## 六、禁止清单（编译器拒收或质检报错）

- `<style>`、`class` 属性、`<foreignObject>`、`textPath`、`@font-face`
- `<animate*>`、`<script>`、`<iframe>`（动画转场由导出参数控制，不在 SVG 内）
- `<symbol>` + `<use>` 组合
- HTML 命名实体（如 `&nbsp;`）——直接写 Unicode 原字符；XML 保留字必须转义 `&amp; &lt; &gt; &quot; &apos;`
- 渐变（linearGradient/radialGradient）、滤镜（filter）、阴影
- 超出画布 viewBox 的元素坐标

## 七、质检与导出（写完 SVG 后）

```bash
# 质检（quick 模式：无锁检查；--stage final --json 生成导出所需的正式报告）
python3 {skillDir}/scripts/svg_quality_checker.py dknowc-projects/<项目名> --quick-generate --stage final --json

# 编译导出（quick 模式）
uv run --with python-pptx --with XlsxWriter uv run --with python-pptx --with XlsxWriter python3 {skillDir}/scripts/svg_to_pptx.py dknowc-projects/<项目名> --quick-generate
```

质检 errors（exit 1）必须修复后重新导出；warnings 可评估后放行。导出成功后 `.pptx` 写入项目 `exports/`。
