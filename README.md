# dknowc-dsh

深知可信办公全家桶 —— DeepSeek Harness（dsh）插件包。

通过一个 bundle 交付彩智科技的三个深知 Skill（深知可信咨询 / 深知可信搜索 / 深知公文写作），并内置深知可信工作台 MCP 转接层配置：**接口能力统一走 MCP，skill 不再直连深知接口**。

## 包含什么

```
dknowc-dsh/
├── skills/
│   ├── dknowc-trusted-consulting/    深知可信咨询（MCP 转接 credible_chat）
│   ├── dknowc-trusted-search/        深知可信搜索（MCP 转接 trusted_search / deep_query）
│   └── dknowc-official-doc-writer/   深知公文写作（搜索走 MCP；范文大纲保留原脚本直连）
├── src/index.js                      注册 3 个 skill 到 dsh ctx.skills
└── cordis.patch.yml                  挂载 skill provider + mcp-client（Bearer 认证）
```

| Skill | 能力 | 接口调用方式 |
|---|---|---|
| 深知可信咨询 | 政策/法规/办事咨询，带角标答案 + 溯源 HTML | `mcp__dknowc__credible_chat` |
| 深知可信搜索 | 权威材料检索/深度研究，溯源 HTML + 干净 Markdown + 政策可视化 | `mcp__dknowc__trusted_search` / `mcp__dknowc__deep_query` |
| 深知公文写作 | 正式公文起草/改写/Word/红头交付 | 搜索走 `mcp__dknowc__trusted_search`；范文大纲 `outline_reference.py` 保留原脚本直连（特殊能力，不进 MCP） |

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
node skills/dknowc-trusted-consulting/scripts/register_key.mjs send --phone <手机号>
node skills/dknowc-trusted-consulting/scripts/register_key.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

注册成功后脚本返回 `apiKey`（展示为打码形式）。拿到 Key 后，**写入启动 dsh 的环境变量 `DKNOWC_API_KEY`**（标准做法是追加到 `~/.zshrc`）：

```sh
echo 'export DKNOWC_API_KEY=sk-xxx...' >> ~/.zshrc
```

然后**重启 dsh 或新开会话**使配置生效。之后每次启动 dsh 都会自动读到，**无需重复注册**。

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
        ├── output/           溯源 HTML、干净 Markdown、Word/红头文档
        ├── input/            正文临时文件（公文写作）
        └── outline-results/  范文大纲 JSON（公文写作）
```

> 公文写作的**个人素材库与写作偏好**是跨会话持久数据，单独存放在用户主目录 `~/.dknowc-writer/`（不随会话隔离，升级插件不丢失）。

## 使用

装好后，3 个 skill 会出现在 dsh 会话的 `<available_skills>` 目录中，模型会按任务描述自动路由：

- 咨询政策/办事 → 深知可信咨询
- 检索权威材料/深度研究 → 深知可信搜索
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

**skillhub 版本是母版。** 三个 skill 的内容源头分别为：

- `深知可信咨询` → 深知可信咨询skill `public/skillhub/dknowc-trusted-consulting`
- `深知可信搜索` → 深知可信搜索skill `public/skillhub/dknowc-trusted-search`
- `深知公文写作` → 深知公文写作 `public/skillhub/dknowc-official-doc-writer`

**修改流程**：任何 skill 改动优先改 skillhub 母版 → 重新同步到本包 `skills/` 目录 → 重新适配（frontmatter name 改 kebab-case、渠道码换 `46A3BA1D-3E1A-4E8C-BD50-A6DCBEE1DB05`、接口调用改 MCP 转接）。其他各渠道（DeepSeek Club / 夏平 / ClawHub / ModelScope / Qoder / Skills-SH / 华为等）的版本都是在 skillhub 母版基础上更换各自渠道码生成。

## License

MIT
