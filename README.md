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

本插件**零 dsh SDK 依赖**（`src/index.js` 只用 Node 内置模块 + cordis 注入的 `ctx`），MCP client 由 dsh 宿主自带并随宿主版本自动对齐（`@deepseek-ai/dsh-mcp-client` 是 dsh CLI 的直接依赖），因此跨 dsh 大版本天然兼容。已在以下版本实测通过（插件加载、skill 注册、MCP 连接均正常）：

- dsh **0.2.1-rc.2**（npm `latest`，2026-10-19 实测：插件树加载零告警；`--dump-config` patch 合成正常；headless 一次性任务会话中 3 skill 出现在 `<available_skills>`（2.2.1 新描述）；MCP server dknowc 连接成功、5 个工具（trusted_search / deep_query / credible_chat / doc_outline / create_api_key）完整同步——见下方 0.2.x 门禁说明）
- dsh 0.1.2-rc.1（SDK 破坏性变更版本）
- dsh 0.1.1-rc.2
- dsh 0.1.0-rc.7（本插件首发基线）

v1.4.0：四 skill 溯源核验报告整体重构（双视图单页/句后引文胶囊/材料专库视图/链接活性检测+存档快照兜底/核验结论分级）；公文范文大纲接入 MCP 第四工具 `doc_outline`；注册统一自动持久化（四 skill 共用同一 `~/.zshrc` 标记块）。

> 注意（dsh 0.1.2 时代）：SDK 破坏性变更（如 `dsh-settings` 移除部分导出）会让引用 SDK 内部包的第三方插件加载失败，且当时的加载机制是**任一插件导入失败即整个 profile 启动失败**。可先用 `dsh --profile web --patch <禁用清单.yml>` 临时禁用可疑插件定位问题；本插件零 SDK 依赖，历次破坏性变更均无需改动。
>
> **dsh 0.2.x 起机制改善**：宿主新增插件兼容性门禁——不兼容插件（peer requirements 不满足）**不再拖垮整树**，而是启动时单独跳过并给出明确告警与精确豁免口（`dsh plugin allow-version`）。2026-10-19 在 0.2.1-rc.2 实测：本插件零告警直接加载（无 peer requirements 冲突项），同环境 dshmarket 1.29.2 被门禁拒绝、升级 1.66.42 后恢复——第三方社区迁移走廊卡（`dsh-plugin-upgrade`，DSH 官方负责人公开推荐）梳理的 0.1.3→0.1.6 全部 25 条破坏性接缝（静默槽位/状态键删除、`agent/created` 监听器竞态、异步注册 INACTIVE_EFFECT、模型 id 删除等）经逐条比对均不涉及本插件接触面（纯同步 `apply()` 注册、无 UI 槽位、无会话 API、无模型引用、无 SDK import）。

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


## License

MIT

## 版本与维护

- 版本历史与逐版变更见 GitHub Releases：<https://github.com/dylanzhangzx/dknowc-dsh/releases>
- 仓库内维护说明（内部流程）见 `MAINTENANCE.md`（不随 npm 包发布）。

