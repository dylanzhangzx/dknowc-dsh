# 第三方组件声明（THIRD_PARTY_NOTICES）

本 Skill 的 SVG→PPTX 编译器及配套工具链抽取自开源项目 **ppt-master**，并按本项目需要做了如下改动：移除官方发行版完整性门（attribution_guard 及二级身份校验）、以纯净版 `console_encoding.py` 替代原实现、按依赖闭包抽取子集。上游其余逻辑保持原样。

- 上游项目：https://github.com/hugohe3/ppt-master
- 作者：Hugo He
- 许可证：MIT License（Copyright (c) 2025-2026 Hugo He）
- 抽取范围：`skills/ppt-master/scripts/` 下的 `svg_to_pptx`、`pptx_shapes`、`svg_quality`、`svg_finalize`、`pptx_animations`、`pptx_transitions`、`pptx_to_svg`、`native_payloads`、`language_tags`、`hyperlink_contract`、`config`、`project_utils`、`resource_paths`、`slide_roster`、`update_spec`、`error_helper`、`pptx_effects`、`pptx_opc_validation`、`register_template` 及其入口脚本与数据文件；示例文件来自 `examples/ppt169_swiss_grid_systems`（存放于 `references/upstream-example/`）。

MIT 许可证原文：

```
MIT License

Copyright (c) 2025-2026 Hugo He

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

另：`pptx_shapes/data/` 内含 Open XML SDK（MIT）与 Apache 2.0 许可的数据文件，其原始许可文本保留在同目录的 `LICENSE-OPEN-XML-SDK-MIT.txt`、`LICENSE-APACHE-2.0.txt` 与 `NOTICE.md` 中。
