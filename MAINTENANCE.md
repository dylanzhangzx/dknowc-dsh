# dknowc-dsh 维护说明（内部，不随 npm 包发布）

本文件承接原 README 的维护约定与逐版变更要点，仅存于仓库。

## 维护约定
**skillhub 版本是母版。** 四个 skill 的内容源头分别为：

- `深知可信搜索` → 深知可信搜索skill `public/skillhub/dknowc-trusted-search`
- `深知可信PPT` → 深知可信PPT Skill `public/skillhub/dknowc-ppt-assistant`
- `深知公文写作` → 深知公文写作 `public/skillhub/dknowc-official-doc-writer`

**修改流程**：任何 skill 改动优先改 skillhub 母版 → 重新同步到本包 `skills/` 目录 → 重打 dsh 补丁（WS_ROOT 会话隔离与 `dknowc-output/` 路径前缀、dsh Key 三级门禁、SKILL.md 版本号 `-dsh` 后缀与 `<skillDir>` 前缀、渠道码换 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`、移除母版专属脚本 `deliver_outputs.py`/`check_release.py`/`detect_workbuddy.py` 并把交付步骤改写为 dsh 工作区交付）。其他各渠道（DeepSeek Club / 夏平 / ClawHub / ModelScope / Qoder / Skills-SH / 华为等）的版本都是在 skillhub 母版基础上更换各自渠道码生成。

**产品文档**：`dknowc-dsh-产品文档.html`（仓库根，10 节结构：概览 / 能力矩阵 / 全景流程 / 交付物 / 文件清单 / 红线 / 接口与Key / 分发渠道 / 版本历史 / 已知问题；不入 npm 包）。版本定稿后与母版同步同批维护。

## 逐版变更要点
## v2.0.0 变更要点

- **移除深知可信咨询 skill**：与可信搜索功能重叠且效果不及，咨询类政策问答由可信搜索承接（检索作答 + 溯源）。
- **检索通道反转为脚本直连**（跟随母版 3.7.5/1.4.0 决策）：MCP 返回为精简视图（缺文号/快照/标题链/可信度），脚本直连返回全量；Key 落盘迁至 `~/.config/dknowc/api_key`（dsh 环境变量清理不影响，注册后本会话即用）。
- 三 skill 同步母版 1.4.2 / 1.3.4 / 3.7.7（溯源核验报告持续修复、图表一体化、参考范文召回、X-Dknowc-Attribution 来源声明 channel=dsh、积分制权益话术）。
## v2.2.1 变更要点

- 产品化修正：公文写作示例文件 `reference/sample_trace_report.html` 中内嵌的 2 处人名注释中性化（母版 3.8.x 渲染器注释带入，含示例 HTML；其余文件在 2.2.0 已清理）。内容与 2.2.0 一致，仅此一处清洁性修复。
## v2.3.1 变更要点

- **三 skill 同步母版**：深知公文写作 3.9.4 / 深知可信搜索 1.6.2 / 深知可信PPT 1.5.2（dsh 版本号 `3.9.4-dsh` / `1.6.2-dsh` / `1.5.2-dsh`）。
- **注册链路切换 Agent 文字题**（MaaS 身份中心 2026-10-28 升级适配）：`send` 移除，注册三步 `challenge`（领题，Agent 当场计算、不进对话）→ `answer`（作答发码）→ `register`；官方指引不可用时自动回落旧版短信直发（`flow:"legacy"`）；`AGENT_TEXT_*` 新错误族停点（换题≤3 次/锁定/不可用终止）；验证页链接校验放宽为同源+`sms-verification-page` 结尾。
- **安全与合规整改**（母版审核轮）：① **脚本不再读写 `~/.zshrc`**——`register` 删除 zshrc 清理逻辑，搜索 `api_key.py` 移除 zshrc 只读兜底（Key 来源收敛为环境变量 → 配置文件两级；PPT 清理改显式 `--clean-zshrc`）；② 话术去写死号码（`<脱敏手机号>` 占位）、如实说明注册账号性质；③ 母版侧人名清理（搜索 SKILL.md/脚本 4 处"徐总"移除）；④ 母版死文件删除（公文/搜索 `mcp_convert.py`、PPT `upstream-docs`/孤立工具）——dsh 侧同步删除（dsh 专属 `mcp_direct.py`/`adapt_mcp_result.py` 保留）。
- **母版功能整改同步**：公文 `save-key` 子命令正式下线（注册仅 challenge/answer/register）、`--no-write` 参数、initialize Key 格式校验（`sk-` 前缀≥20 位）、format_document GBK 正文回退、prose_lint 坏 docx 报错、search_guide 自检中文五键示例；PPT 品牌名统一（`~/.dknowc-ppt` 配置目录）、导出 `-o` 固定名+备份+600 权限、端点白名单、requests 降可选。
- **dsh 侧**：全部补丁落点重放（注册三步命令/新 initialization 文档/deliver_outputs 口径保持 dsh 交付）；清理本轮无差别拷贝误带入的母版专属脚本。
## v2.3.0 变更要点

- **三 skill 同步母版大版本**：深知公文写作 3.9.2 / 深知可信搜索 1.6.0 / 深知可信PPT 1.5.0（dsh 版本号 `3.9.2-dsh` / `1.6.0-dsh` / `1.5.0-dsh`）。
- **可信搜索全面切换 V2 接口**（三 skill 的检索客户端）：端点 `/open-api/maas/dependable/v2/search`；`searchType` 必填单值分路（政策依据 `policy` / 数据案例 `govSite`，混传报错）；参数定档 `segmentCount=4` / `MaterialLength=18000` / `filterPara=true`；成功判定 `ret==0 且 content.code==200`；`tid` 随产物落盘。V2 文章级新字段（发文字号/生效日期/失效日期/文章类型/文章Id）透传进来源卡关键性行。
- **文号链路修复**（V2 配套）：merge 键链扩为 `文号 > 发文字号 > doc_number > writtenText`（中文键优先）——V2 切换起文章级文号在 merge 被丢的问题修复；正文文号只认材料清单「发文字号」字段（公文 G6 gate，`check_materials.py` 拦截从段落正文提取文号）；补搜改为纯缺口驱动（文号缺失不再构成补搜理由）。
- **安全加固**（应用市场注入扫描中危修复，三 skill 渲染器同源）：表格清洗改 HTMLParser 元素级白名单（防 `<svg/onload>` 类畸形标签绕过）；全部外链协议白名单 `safe_url()`（仅 http/https）；页尾注入 JSON 字符级转义；公文 `format_document.py` 目录白名单 realpath 校验；畸形表格（数据行整片包 thead）自动修正。
- **过程统计与装配契约**：merge 记录每路调用增量（`new_articles`/`added_paragraphs`），过程条显示「该路新增 N 篇 · 补充 K 段」；`--question-file` 用户原问题全文落盘传入（多行问题禁止只传首行，`check_materials.py` 对空 question 拦截）；补搜计数与真实调用次数对齐。
- **搜索 1.6.0 专属**：要件式改写规则（资格/准入/受限类问题必须补要件式 query）；联网检索降级链（`--search-channel webSearch`，联网材料自动打「非官方来源」徽标）。
- **PPT 1.5.0 专属**：质检判据定死（退出码 0 且 errors=0 即通过，warnings 不阻断；质检循环最多 3 轮、导出后不回头）；SKILL.md 定向瘦身（新 `references/initialization.md`）。
- **公文 3.9.x 专属**：SKILL.md 396→143 行重构（细节拆入 `initialization/outline_rules/materials_pipeline/writing_rules/working_principles/genre_writing_notes` 六篇新 reference）；写作规则收紧（事实来源三分法、标准引用四查、调研方法只写实际执行、篇幅只服从用户明确要求——取消默认 3500-5000 门槛）；Word 补交不重渲染 HTML；深搜 `writtenText` 文号透传。
- **注册话术透明化**：索要手机号前明确告知账号注册与本机保存凭证事实；话术事实要素不可增删、措辞可自然调整。
- **dsh 侧**：与母版同步更新全部 dsh 补丁落点（公文 SKILL.md 新结构、新 reference 六篇、PPT initialization.md、deliver_outputs 相关步骤全部保持 dsh 交付口径）；V2 参数/分路规则同步；渲染器与文档中 6 处母版带入人名中性化（待反馈母版）。
## v2.2.0 变更要点

- **三 skill 同步母版大版本**：深知公文写作 3.8.1 / 深知可信搜索 1.5.1 / 深知可信PPT 1.3.7（对应 dsh 版本号 `3.8.1-dsh` / `1.5.1-dsh` / `1.3.7-dsh`）。
- **产出物 HTML 三页架构**（公文写作 + 可信搜索，跟随母版 3.8.x/1.5.x 交付形态大改）：单文件 HTML 顶部切换 **正文（去索引）/ 溯源核验报告 / 知识专库** 三页，默认落在报告页；单一吸顶 banner（文稿名 + 三页切换 + 复制/导出 + 原问题 + 统计行，切页高度不变）；导出菜单（Markdown（正文）/ PDF（正文）/ PDF（溯源核验报告））；可信搜索不再生成 `.clean.md`（正文页与导出已覆盖）。
- **公文写作交付双开关**：命中 15 种法定公文 → Word（可红头）；执行过深知搜索 → 产出物 HTML；两者可同时成立（task_router 交付矩阵）。
- **核验报告数据正确性修复**（母版同步）：merge 句子指纹二次去重（同内容多标题变体只出一张卡）+ 标题链污染段剔除；检索通道标注全链路透传（深度搜索/可信搜索分路计数与来源声明，双通道拼接保留）；materials 按角标号升序重排（修胶囊错位）；深度搜索表格标签保留（修知识专库表格拍平）；check_materials 同标题多 URL 变体误判修复；研究资料 gate（研究型文种缺研究资料拒绝渲染）。
- **可信搜索新增 deep_convert.py 转换层**：深度搜索 v3 原始产物先转通用形态再进 merge（merge 拒绝 v3 原始形态并提示）；研究资料层（核心事实总表 + 数据口径表，缺口驱动补搜）。
- **可信PPT**：知识专库卡片横向溢出修复（minmax(0,1fr)）；交付清单纪律（三件套之外一律不交付）。
- **dsh 侧修正**：修复 2.1.0 遗留的 `deliver_outputs.py` 幽灵引用（可信搜索 SKILL.md 步骤 7/8、可信PPT SKILL.md 与 generate-pptx Step 9——dsh 包内本就无此脚本，现统一改为 dsh 工作区交付表述）；修复可信PPT initialize.py 重复函数定义（dsh Key 门禁分支此前被同名函数覆盖为死代码）；可信搜索"检索产物位置"说明改为会话工作区口径（原误写为 skill 安装目录）；src/index.js 三条 skill 描述同步新交付形态（原残留 MCP 直连与"干净 Markdown"旧口径）。
- **产品化清扫**：渲染器代码注释中的 2 处人名残留中性化（母版 3.8.x 新增注释带入）。
## v2.1.0 变更要点

- 同步注册链路契约（母版 3.7.9 / 1.4.5 / 1.3.6）：注册 body `source="agent"` 合同标记回退（修复老用户返 Key）、`X-Dknowc-Attribution` 头键名 `source`→`agentSource`、sendMessage 两分支（直发/验证链接）、X-MaaS 四个观测头。
