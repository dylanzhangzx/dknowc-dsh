# dknowc-dsh

深知可信办公全家桶 —— DeepSeek Harness（dsh）插件包。

通过一个 bundle 交付彩智科技的三个深知 Skill（深知可信搜索 / 深知可信PPT / 深知公文写作），接口能力统一走**脚本直连**（全量结构化返回），并捆绑深知可信工作台 MCP（trusted_search / deep_query / doc_outline）作为脚本异常时的应急兜底。

## 包含什么

```
dknowc-dsh/
├── skills/
│   ├── dknowc-trusted-search/        深知可信搜索（脚本直连 + deep_convert 转换层；三页产出物 HTML）
│   ├── dknowc-ppt-assistant/         深知可信PPT（素材检索脚本直连；SVG→原生PPTX 纯本地编译）
│   └── dknowc-official-doc-writer/   深知公文写作（两阶段检索脚本直连；公文 Word × 产出物 HTML 双开关交付）
├── src/index.js                      注册 3 个 skill 到 dsh ctx.skills
└── cordis.patch.yml                  挂载 skill provider + mcp-client（Bearer 认证）
```

| Skill | 能力 | 接口调用方式 |
|---|---|---|
| 深知可信搜索 | 咨询类政策问答 + 权威材料检索/深度研究（分级），单文件产出物 HTML 三页（正文/溯源核验报告/知识专库，图表一体化，研究资料层） | 脚本直连（`trusted_search.py` / `deep_query.py` + `deep_convert.py` 转换层）；MCP 兜底 `mcp__dknowc__trusted_search` / `mcp__dknowc__deep_query` |
| 深知公文写作 | 正式公文起草/改写/多轮改稿，交付双开关：15 种法定公文出 Word（可红头）、执行过搜索出产出物 HTML 三页；研究资料层 + 参考范文召回 | 脚本直连（`dkag_search.py`/`deep_query.py`/`deep_convert.py`/`outline_reference.py`）；MCP 兜底 `mcp__dknowc__*` |
| 深知可信PPT | 演示文稿制作：SVG 逐页创作→编译原生可编辑 .pptx，双版核验报告（提纲/成稿）+ 页面预览页 | 素材检索脚本直连（`trusted_search.py`）；编译纯本地（python-pptx，uv 隔离依赖） |

## dsh 版本兼容性

本插件**零 dsh SDK 依赖**（`src/index.js` 只用 Node 内置模块 + cordis 注入的 `ctx`），MCP client 由 dsh 宿主自带并随宿主版本自动对齐（`@deepseek-ai/dsh-mcp-client` 是 dsh CLI 的直接依赖），因此跨 dsh 大版本天然兼容。已在以下版本实测通过（插件加载、4 skill 注册、MCP 连接均正常）：

- dsh 0.1.0-rc.7（本插件首发基线）
- dsh 0.1.1-rc.2（npm `latest`，`npx @deepseek-ai/dsh` 默认拿到）
- dsh 0.1.2-rc.1（npm `next`，SDK 破坏性变更版本）

v1.4.0：四 skill 溯源核验报告整体重构（双视图单页/句后引文胶囊/材料专库视图/链接活性检测+存档快照兜底/核验结论分级）；公文范文大纲接入 MCP 第四工具 `doc_outline`；注册统一自动持久化（四 skill 共用同一 `~/.zshrc` 标记块）。

> 注意：dsh 0.1.2 起 SDK 有破坏性变更（如 `dsh-settings` 移除部分导出），一批引用 SDK 内部包的第三方插件会加载失败，且 dsh 的加载机制是**任一插件导入失败即整个 profile 启动失败**。如升级 dsh 后无法启动，可先用 `dsh --profile web --patch <禁用清单.yml>` 临时禁用可疑插件定位问题（`- id: <插件id>` + `disabled: true`），本插件本身在 0.1.2 上无需任何改动。

## 安装

前置：Node.js 22.19+，已安装 dsh。

```sh
dsh plugin --profile web add dknowc-dsh
```

或从源码/本地目录安装：

```sh
dsh plugin --profile web add github:彩智/dknowc-dsh     # GitHub 安装
dsh plugin --profile web add ./dknowc-dsh              # 本地 checkout
```

## 配置 MCP 认证

接口走深知可信工作台 MCP，Bearer 认证使用环境变量 `DKNOWC_API_KEY`：

```sh
export DKNOWC_API_KEY=你的APIKey
```

`cordis.patch.yml` 中已内置：

```yaml
- id: mcp-dknowc
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: dknowc
    transport: streamable-http
    url: https://mcp.dknowc.cn/s6/mcp/
    headers:
      Authorization: !!js '`Bearer ${process.env.DKNOWC_API_KEY}`'
```

### 获取并配置 API Key

未配置 `DKNOWC_API_KEY` 时，可运行任一 skill 内置的注册脚本（使用 dsh 专属渠道码 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`）：

```sh
node skills/dknowc-trusted-search/scripts/register_key.mjs send --phone <手机号>
node skills/dknowc-trusted-search/scripts/register_key.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

注册成功后脚本自动把 Key 写入本机专用配置文件 `~/.config/dknowc/api_key`（600 权限，并清理历史 `~/.zshrc` 旧块）——dsh 的环境变量清理机制不影响配置文件读取，**本会话立即可用，无需重启**：

脚本会同时输出 `envWriteInstruction`。已有历史 `~/.zshrc` Key 块的用户无需处理（脚本与 initialize 自动兼容读取）；如仍想让 dsh 主进程环境变量持有 Key（MCP 兜底通道用），可自行追加 `export DKNOWC_API_KEY=...` 并重启 dsh，属可选项。

> **Key 的传递机制**：dsh 的安全机制会清理名字含 `KEY` 的隐式环境变量（`DKNOWC_API_KEY` 会被拦）。本 bundle 插件会把 dsh 主进程的 `DKNOWC_API_KEY` 值经 shell-env 显式通道注入为 `DSH_DKNOWC_API_KEY` 供脚本门禁检查与兜底使用；**用户只需配置 `DKNOWC_API_KEY`，无需设置 `DSH_DKNOWC_API_KEY`**。MCP 的 Bearer 认证直接读 dsh 主进程的 `process.env.DKNOWC_API_KEY`。

## 工作区与产物位置

bundle 内的 skill 目录是**只读发布产物**，运行时产物（溯源 HTML、搜索结果 JSON、Word 文档、中间文件）**不会写入 bundle**，而是写入**当前会话工作区**（dsh 里即你在 Web UI 中选中的 workspace 目录）。

机制：所有脚本支持 `DKNWOC_WS_ROOT` 环境变量显式指定产物根；未设置时，若存在 `DSH_SESSION_ID`（dsh 注入）则自动使用**会话隔离目录**，否则回退当前目录。因此：

- 在 dsh 里：**每个会话的产物自动落到 `<工作区>/dknowc-output/<会话ID前8位>/`**，同一工作区多会话互不混杂、互不覆盖
- 本地裸跑：无会话变量时落 `dknowc-output/_default/`
- 显式指定：`DKNWOC_WS_ROOT` 优先级最高（测试/特殊场景）

产物结构（在工作区内，按会话隔离）：
```
<workspace>/dknowc-output/
└── <会话ID前8位>/
    └── official-docs/
        ├── search-results/   接口 JSON、MCP 原始返回、规范化 JSON、答案文件
        ├── output/           产出物 HTML（正文/溯源核验报告/知识专库 三页）、Word/红头文档
        ├── input/            正文临时文件（公文写作）
        └── outline-results/  范文大纲 JSON（公文写作）
```

> 公文写作的**个人素材库与写作偏好**是跨会话持久数据，单独存放在用户主目录 `~/.dknowc-writer/`（不随会话隔离，升级插件不丢失）。
> 可信PPT 的**项目目录**是跨会话延续的工作数据，单独存放在工作区级 `dknowc-projects/<项目名>/`（内容包、SVG、导出的 .pptx，访达可直接找到，不随会话隔离）。

## 使用

装好后，3 个 skill 会出现在 dsh 会话的 `<available_skills>` 目录中，模型会按任务描述自动路由：

- 咨询政策/办事、检索权威材料/深度研究 → 深知可信搜索
- 制作 PPT/演示文稿/课件 → 深知可信PPT
- 起草/改写/生成正式公文 → 深知公文写作

也可在 dsh 中通过 skill 名称直接触发。

## 本地验证

```sh
npm run check
```

## 分发

- GitHub 仓库：打 `dsh-plugin` topic 以便生态发现
- npm：`pnpm publish`（本包零构建，`main` 直接指向 `src/index.js`）

## 维护约定（重要）

**skillhub 版本是母版。** 四个 skill 的内容源头分别为：

- `深知可信搜索` → 深知可信搜索skill `public/skillhub/dknowc-trusted-search`
- `深知可信PPT` → 深知可信PPT Skill `public/skillhub/dknowc-ppt-assistant`
- `深知公文写作` → 深知公文写作 `public/skillhub/dknowc-official-doc-writer`

**修改流程**：任何 skill 改动优先改 skillhub 母版 → 重新同步到本包 `skills/` 目录 → 重打 dsh 补丁（WS_ROOT 会话隔离与 `dknowc-output/` 路径前缀、dsh Key 三级门禁、SKILL.md 版本号 `-dsh` 后缀与 `<skillDir>` 前缀、渠道码换 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`、移除母版专属脚本 `deliver_outputs.py`/`check_release.py`/`detect_workbuddy.py` 并把交付步骤改写为 dsh 工作区交付）。其他各渠道（DeepSeek Club / 夏平 / ClawHub / ModelScope / Qoder / Skills-SH / 华为等）的版本都是在 skillhub 母版基础上更换各自渠道码生成。

**产品文档**：`dknowc-dsh-产品文档.html`（仓库根，10 节结构：概览 / 能力矩阵 / 全景流程 / 交付物 / 文件清单 / 红线 / 接口与Key / 分发渠道 / 版本历史 / 已知问题；不入 npm 包）。版本定稿后与母版同步同批维护。

## License

MIT


## v2.0.0 变更要点

- **移除深知可信咨询 skill**：与可信搜索功能重叠且效果不及，咨询类政策问答由可信搜索承接（检索作答 + 溯源）。
- **检索通道反转为脚本直连**（跟随母版 3.7.5/1.4.0 决策）：MCP 返回为精简视图（缺文号/快照/标题链/可信度），脚本直连返回全量；Key 落盘迁至 `~/.config/dknowc/api_key`（dsh 环境变量清理不影响，注册后本会话即用）。
- 三 skill 同步母版 1.4.2 / 1.3.4 / 3.7.7（溯源核验报告持续修复、图表一体化、参考范文召回、X-Dknowc-Attribution 来源声明 channel=dsh、积分制权益话术）。

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
