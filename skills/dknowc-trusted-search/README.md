# 深知可信搜索（法律、政策、标准）（dsh 版）

这是深知可信搜索（法律、政策、标准）的 DeepSeek Harness（dsh）插件分发版。功能逻辑与 full 版对齐，不再调用统一咨询接口；检索统一走本 Skill 脚本通道（1.3.5 起彻底回退 MCP 通道，MCP 大结果落盘方案效果有问题，待技术侧改造后恢复）。本版本不内置 API Key；优先从环境变量 `DKNOWC_API_KEY` 读取，宿主进程读不到 shell 环境变量时自动从本机专用配置文件 `~/.config/dknowc/api_key` 读取（不读写任何 shell 配置文件，避免 WorkBuddy 等宿主误报缺 Key）；未配置时 Agent 可先通过 MaaS 手机号验证码流程获取 Key（注册成功自动写入专用配置文件）。

## 能力范围

- 可信搜索：查找原文、依据、权威材料或来源时调用 `scripts/trusted_search.py`（API Key）返回重点来源文章；**按问题复杂度分级，判据是"先数对象"**——**只有 1 个对象/地域**（含"北京有哪些租房补贴政策""怎么申请""条件是什么"这类单地域枚举、单点事实、单政策解读）走可信搜索建证据池；**≥2 个对象/地域要放在一起比、跨地域跨层级聚合、或用户明确表达深度意图**时才用 `scripts/deep_query.py` **单路**深度搜索（query 直接用用户原始问题、默认不传地域，服务端按 query 中的地域概念自动拆子查询）；**拿不准时先走可信搜索**，证据不足再升级。政策依据型再以可信搜索补搜文号/原文。**资格/准入/受限类问题必须补一路要件式 query**（对象＋申请条件／不予受理情形／除外情形），禁止是非问法或同义替换直接检索（1.6.0）。**任务型交付**：用户指令要什么产出物，正文就是该成品内容全文（邮件/纪要等在聊天直出去角标全文、可直接复制），依据与分析沉淀核验报告页；不生成 .docx/.pdf，正式公文排版走公文写作类 Skill。**三阶段联网检索降级链（1.7.2；1.7.3 增补可引用性判定）**：默认只查深知库内；**阶段二**库内无结果或核心事实无直接支撑（含方向不一致）时走 `--search-channel webSearch`（可溯源原段、自动开 dataAuthority、渲染自动标"非官方来源"）；**阶段三**仍无支撑时用宿主 WebSearch，结果必须经 `scripts/websearch_convert.py` 转通用形态、`merge_search_results.py` 合并进同一份报告（材料统一标"非官方来源"，正文页加统一来源提示条）；境外制度如实说明不支持。**可引用性（1.7.3）**：policy 版本索引/无正文材料在产物中标 `可引用=false`，只能当版本线索、禁止挂角标；核心事实只有此类材料时按“搜不到”继续降级或换绑有正文摘录的材料。**单路文号（1.7.4；1.8.1 入口化）**：入口适配器同时兼容可信 V2 的 `发文字号`、深搜 V3 的 `writtenText` 与 merge 归一后的 `文号`，单路产物经 `build_trace_input.py` 转换后不再漏显知识专库文号。合并脚本输出材料池清单（机构/文号/金额/标题），写答案大纲前先扫描——池内与用户情形相关但未被问到的主题要进大纲（1.4.3 证据侧覆盖）。
- **运行目录与两轨核验（1.8.0 起；1.8.2 增补两轨）**：产出一份 HTML 的核验结论由两条轨道共同判定——**结构核验**（依据溯源/引用对应/材料新旧/自检格式与证据/记录指纹）与**AI 验收**（五项 Agent 验收，要求 `verdict` + `basis` + 可回查 `evidence`：材料编号/条款/文号/日期/标准号/文件名；数字/标准号/地域/缺席/金额对象/措辞等内容判断全部由 AI 负责）；**任一轨不过即整体未通过**，空话（无证据）只记“证据不足”、不算通过；`agentCheck` 为 `selfCheck` 别名，旧字符串写法仍兼容。所有检索、答案、自检、报告产物写入会话工作区的独立 `$RUN/`，脚本统一传 `--run "$RUN"`；拒绝写入 Skill 安装目录，不再默认创建 `official-docs/`；内部重跑覆盖同名文件，交付层（用户目录）才按 `_v2`/`_v3` 编号。**不合格不出报告**：结构不合格（角标未绑、依据无摘录、不可引用材料作依据、自检声明通过但无证据、核验记录失效/verdict=fail）或 AI 验收判 `fail`，渲染器直接退出、不生成 HTML，必须修正后重跑；交付物只有“已核验”一种形态。脚本不做任何内容判断，也不再输出内容线索（`claim_audit.py` 于 1.8.2 移除）。来源等级：接口无数据时使用公开网络的官方信源（政府域名/法定机构）可正常支撑结论，仅第三方信源全占时提醒。
- 深度搜索：仅在用户明确要求或确认升级后，调用 `scripts/deep_query.py`（deep-query/v3，非流式）做多轮检索和分析。
- 最终交付：聊天回复（任务型＝成品全文去角标干净版，可直接复制；问答型＝核心结论＋必要来源摘要）＋溯源核验报告 HTML（唯一文件产物；正文 Markdown/PDF 由用户在 HTML 顶栏「导出 ▾」自助导出，本 Skill 不生成 .md/.docx/.pdf 文件）。**角标编号契约**：答案里 `[n]` 的 n = 该材料在本次传入 JSON（多路检索为合并产物，每篇带 `编号` 字段）中的 1-based 序号；必须边写边标，禁止写完正文再回头反查补标——编号写错会静默绑到另一份材料，核验单不会报错（渲染器只重排"展示编号"，不解绑绑定关系）。
- 默认产出物（1.5.1 banner 收敛版；1.5.0 三页架构；1.8.1 入口化）：最终解决问题时，先用 `scripts/build_trace_input.py` 把检索/merge 产物转成通用 JSON，再用 `scripts/render_trace_html.py --config config/trace_report.config.json` 生成单文件《简短文件名.html》（文件名由 Agent 用 --output 命名）（顶部三页切换——正文（去索引）/ 溯源核验报告（默认落点，文头「溯源核验报告：{标题}」）/ 知识专库；正文页=strip_cites 干净正文+文头标题；顶栏「导出 ▾」＝导出 Markdown（正文）/ 导出 PDF（正文）/ 导出 PDF（溯源核验报告）；hero＝三页切换→原问题（15px 居中）→统计行；AI 自验收过程条按接口通道拆分计数（深度搜索 N 路 · 可信补搜 M 次）、来源动态声明；核验单五项指标真实计算、核验明细与检查说明 details 折叠；章节目录正文/报告页双锚点；报告页正文行内只留可点击数字角标 `[n]`，点击弹出引用依据弹窗（1.8.0，原"标题胶囊 + 原地展开"已移除）；知识专库检索分组 tabs（仅多分组时显示）+ 已引用材料卡 + 「未进入正文的参考材料」折叠区；生成前内置 policyFiles 文号匹配、来源文章去重（归一化标题+URL 双键 + 句子指纹二次去重 + 标题链污染段剔除）、存档快照附加回看、原文链接不做活性探测原样进报告；`--question` 用户原话显示 hero 原问题行、`--research-notes-file` 在 AI 自验收体现研究资料整理规模（核心事实总表 + 数据口径表，口径缺口驱动补搜）；生成前硬校验答案必须有 [n] 角标且逐条绑定材料；文件名由 Agent 用 --output 指定（标题式短名，8-20 字）；内部重跑覆盖同名文件，交付层才编号）。不再生成 `.clean.md`（正文页与导出 Markdown 已覆盖）顶部为单一吸顶 banner（切换+工具+原问题+统计，切页高度不变，统计口径为『知识专库文章 N 篇 · 正文实际引用 M 处』）。深度搜索 v3 产物须先经 `scripts/deep_convert.py` 转通用形态再进 merge（1.5.1 起 merge 只吃通用形态）。
- dsh 交付：产物直接生成在会话工作区 `$RUN/`（`dknowc-output/<会话ID前8位>/runs/<任务>/`），dsh 以工作区为文件视图，直接展示脚本打印的路径即可，无需交付复制。
- 政策可视化（1.4.0 起**并入核验报告，只有这一条路**）：需要图表时，把带来源的结构化图表 JSON 写入 `$RUN/`，在入口生成 `input.json` 后用 `render_trace_html.py --config ... --charts-json` 与核验报告**一次成稿**——图表跟着数据走：`metadata.section` 指定所属章节、直接插进该章正文之后（如奖励金额对比的图就排在"奖励金额对比"那一节里）；缺锚点时才退化为核验报告单之后的独立"数据可视化"章节，**一次任务只交付 1 个 HTML，任何时候都不产出第二份图表报告**。是否画图有明确判据：用户明确要图（图表/柱状图/折线图/饼图/环形图/可视化/画个图…）必须画；用户没提时 Agent 可自行判断，但须同时满足"≥2 对象/时点/构成项可比 + 数值可绑定来源 + 图比文字更易读 + 结论是数据性的"四条（`对比/梳理/分析/系统` 等分析措辞不算画图指令）。可用图型只有四类：对象×指标→柱状、趋势→折线、并列对比→分组柱、构成占比→环形；不做地图。**用包内定制版 ECharts 内联渲染**（`resources/echarts.custom.min.js` 526KB 定制构建，单文件完全离线可开），点击图表项跳转来源原文；资源缺失或数据不足（<2 点/系列）整章略过、不阻断报告。

## 首次启动初始化

只要调用本 Skill，Agent 必须先运行：

```bash
python3 {baseDir}/scripts/initialize.py
```

只有返回 `ready=true`、`api_key_configured=true`、`api_key_source` 为 `environment` 或 `keyfile` 后才继续处理原任务。初始化未通过时，只允许引导用户完成 MaaS Key 获取或环境变量配置，不得先输出答案、草稿、大纲、材料清单或分析结论。

## 版本自检与引导升级

initialize.py 每次运行会匿名查询 MaaS 技能中心公开目录（免认证、不扣积分、无需 Key），与本包 SKILL.md 版本比较：仅当远端登记版本更高时输出 `update.update_available=true` 与提示话术（不提示降级；用户话术不暴露 MaaS 等内部术语）。提示在**开始执行用户任务前**进行（initialize 之后、处理任务之前先征询，每会话最多一次），Agent 转述话术征得明确同意后才执行升级；升级由 `scripts/update_skill.py` 代码化执行（`python3 {baseDir}/scripts/update_skill.py` 预览，`--yes` 执行）：脚本内置官方目录白名单、下载源 OSS 前缀白名单（`https://down.dknowc.cn/upload/maas/skills/`）与固定包名校验、解压总量上限与禁重定向，自动完成「下载 → 验包（单一顶层目录／无路径逃逸与软链接／zip 完整性／包内 SKILL.md 名称一致且版本＝登记版本）→ 整目录备份 → 就地替换当前安装目录（不新建第二目录、不残留旧程序文件；会话工作区运行产物不受影响）→ 替换后验证，失败自动回滚」，退出码 2＝无更新、3＝下载或验包失败、4＝替换失败已回滚。**拒绝记忆**：用户拒绝后 Agent 运行 `update_skill.py --decline` 静默记录被拒版本，该版本不再重复提示，仅当目录出现更高版本时才重新提示一次；用户主动要求升级时以 `--yes --force` 无视拒绝记录执行（仍走全部校验）。升级统一采用官方 MaaS 渠道包，已注册用户的 Key 与注册关系不受影响、无需二次注册；升级后调用来源声明随包统一为 MaaS 渠道（官方升级契约见 `https://platform.dknowc.cn/agent-docs/skills/install.md`）。检查自带 24h 本地缓存与 3s 超时静默失败，任何失败都不阻断任务；`DKNOWC_UPDATE_CHECK=0` 可整体停用。

## MaaS 注册与环境变量配置

当前版本统一通过 `DKNOWC_API_KEY` 提供 Key（读取顺序：环境变量 → 本机专用配置文件 `~/.config/dknowc/api_key`；不读写任何 shell 配置文件），不扫描或复用其他深知系列 Skill 的本地 `config.ini`，业务调用脚本经 `api_key.py` 统一解析、不读取 `config.ini` 或传入 `szUserId`。如当前环境变量未配置：

- 可运行 `scripts/register_key.mjs` 注册/查回 Key：**默认 `challenge` 走注册通行码一次发码（`flow:"key"`，不需要领题作答）**，发码会话按手机号落盘并在 `register` 复用；注册通行码失效时自动回落原领题流程（`challenge` → `answer` → `register`），平台回退时再走旧版短信直发分支，输出 `flow` 标明 `key`/`agent-text`/`legacy`；限频、号码被拒、供应商失败、结果未确认一律停点不回落；各分支输出 `user_message` 固定话术，Agent 必须原样转述；题目由 Agent 当场计算，不进入对话；宿主提供「深知可信工作台」（dknowc-mcp）且用户已完成 OAuth 授权时，优先经其 `create_api_key` 工具直接取 Key 并用 `save-key` 子命令落盘，免去手机号验证码（随公文写作 3.7.7 移植）。
- 所有向深知 MaaS 发请求的脚本（trusted_search / deep_query / register_key.mjs）统一携带 `X-Dknowc-Attribution` 来源声明头（`kind=skill;agentSource=dknowc-trusted-search;version=…;channel=dsh`，json 字段名保持 `source`、仅头内键名为 `agentSource`，读包根 `attribution.json` + SKILL.md version 动态构造；仅统计用、不参与鉴权，读取失败不加头不阻断）。注册链路（challenge/answer/register）另携带 `X-MaaS-Entry-Surface: DIRECT_API`、`X-MaaS-Client-Name: dknowc-trusted-search`、`X-MaaS-Client-Version`（运行时读 SKILL.md）、`X-MaaS-Client-Instance-Id`（服务端签发后落盘 `~/.config/dknowc/maas_client_instance` 并回传，不自行生成）；注册 body 的 `source="agent"` 为注册 API 合同标记（服务端按它放行老用户直接返 Key）。register_key.mjs 退出码：challenge/answer 0=已发码、2=需人工验证链接、3=答错换题（answer，需再答）、4=结果未确认、1=错误；register 可能返回 `pending:true`（密钥准备中，非错误）。
- 注册成功自动把 Key 写入本机专用配置文件 `~/.config/dknowc/api_key`（0600 权限、临时文件原子替换；`--no-persist` 仅用于诊断，跳过后不会返回明文 Key、无法继续检索），脚本不读取、不写入、不改写任何 shell 配置文件（历史 Key 标记块请用户自行处理）；业务脚本与 `initialize.py` 直读该文件，无需重启宿主。
- 脚本任何情况下都不返回明文 `apiKey`；业务脚本从 0600 配置文件直读，写入失败时停止检索并提示修复权限。
- MaaS 平台登录页：`https://platform.dknowc.cn/auth/#/login`

## 开通引导（1.2.1 起固定话术）

初始化检测到 Key 未配置时输出 `guide_message`（S1 三段式：价值 / 权益+开通方式 / 退路+样例钩子），Agent 优先原样转述；注册漏斗与报错场景的完整固定话术见 `reference/onboarding_scripts.md`（S1-S6 场景话术、注册与搜索链路报错对照表、FAQ、通用禁则）。核心纪律：引导前禁示（确认前不得输出"已核实/已查到"类内容）、权益前置（注册赠送 10 万积分 + 实名认证再送 10 万积分在引导时告知）、退路唯一（"依据待核验"标注，禁止承诺联网检索替代）、手机号全程脱敏。用户犹豫或询问效果时，用 `reference/sample_search_result.md` 与 `reference/sample_trace_report.html` 展示检索结果和溯源报告效果（两文件均为示例数据，仅供展示，不得作为交付物）。

## 接口地址

- 可信搜索接口（**V2，1.6.0 起**）：`https://open.dknowc.cn/open-api/maas/dependable/v2/search`（V1 路径不再保留）；`searchType` 单值必填（policy 默认，混传报错——两类来源并行两路再 merge）；定档 segmentCount=4 / MaterialLength=18000 / filterPara=true / queryTopArea=false
- 深度搜索接口：`https://open.dknowc.cn/api/services/deep-query/v3`（非流式，请求体字段 `query`，`areas` 支持多地域）
- MaaS 平台登录页：`https://platform.dknowc.cn/auth/#/login`

## 工作区与产物约定

所有中间产物与交付物落在**会话工作区的独立 run 目录**，不再写 Skill 安装目录，也不再默认创建 `official-docs/`：

- `$RUN/*.json`：查询/搜索/深度搜索/合并结果；
- `$RUN/*.txt`、`$RUN/*.json`：最终答案与五项自检；
- `$RUN/*.html`：唯一文件产物（图表并入其中；正文 Markdown/PDF 由用户在 HTML 顶栏「导出 ▾」自助导出）。

查询脚本用 `--run "$RUN" --json-only --output <文件名>`；渲染脚本用 `--run "$RUN"` 并从同名目录读取答案/自检。`--run` 或绝对 `--output` 指向 Skill 安装目录会被拒绝；内部重跑覆盖同名文件；交付到用户目录时同名且内容不同才 `_v2`/`_v3`。

## 常用测试

```bash
python3 -m py_compile {baseDir}/scripts/*.py
node --check {baseDir}/scripts/register_key.mjs
```

请求参数检查：

```bash
python3 {baseDir}/scripts/trusted_search.py "公积金租房提取政策原文" --show-payload --dry-run
python3 {baseDir}/scripts/deep_query.py "重庆智能化改造补贴和税惠综合判断" --show-payload --dry-run
```

公开包不得包含 `_meta.json`、`CHANGE_log.md`、`config.ini`、`config.ini.example`、真实 API Key、本地生成的 HTML/SVG 输出或缓存文件；包里也不带 `official-docs/` 或任何运行产物。
