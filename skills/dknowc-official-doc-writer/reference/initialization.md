# 启动初始化与检索开通

本文件是启动检查、API Key 按需判定、注册/开通流程的完整规则。**SKILL.md 启动段判定为"未配置且任务需要检索"时必读**；不需要搜索的任务无需读取。

dsh 版不内置深知搜索 API Key。API Key 必须通过环境变量 `DKNOWC_API_KEY` 注入。本 Skill 被调用后，先运行一次初始化检查：

```bash
python3 <skillDir>/scripts/initialize.py
```

初始化用于检查 Python、`python-docx`、`requests` 等基础运行环境，不要求用户提供单位或个人信息，也不上传检测结果。初始化不是 API Key 硬性门禁：只有当当前任务确实需要调用深知搜索时，API Key 才是前置条件。

**素材检索与范文大纲一律走本 Skill 脚本通道**（`deep_query.py` / `dkag_search.py` / `outline_reference.py`），需要 API Key；MCP「深知可信工作台」通道当前未启用。素材检索按**两阶段执行**：首轮用 `deep_query.py` 做**深度搜索广度召回**（3 路按素材类型，query 用「对象+关注方向」句式），返回 JSON 落盘后运行 `python3 <skillDir>/scripts/deep_convert.py` 转换；补搜用 `dkag_search.py` 做**可信搜索精准补强**（深度搜索含快照/段落标题/可信度与文章级文号 writtenText；补搜按缺口驱动，不再为拿文号而必补）。范文大纲用 `outline_reference.py`。深度搜索与可信搜索的返回都**立即完整原样落盘**并 `json.load` 校验后再转换，研究资料、溯源 JSON 整理与核验报告全部按现有流程执行（深度产物含快照/段落标题/可信度与文章级文号；补搜产物四字段完整）。搜索与大纲失败时先串行重试该路一次（鉴权竞争多为瞬态）；任一路额度用尽（`quota_exhausted=true`）整批停止、禁止任何重试、引导 MaaS 平台；重试仍失败才如实告知用户并暂停等待确认，不得擅自改用 Web 搜索或跳过检索。

### 不需要搜索的任务

简单通知、内部事务通知、改写、润色、审查、基于用户材料写作、只生成 Word 或红头文件等不涉及政策、数据、案例检索的任务，只要 `python3`、`python_docx`、`requests` 就绪即可继续写作，不要求配置 API Key，也不必引导用户注册 MaaS。初始化结果显示 `api_key_configured=false` 或 `search_ready=false` 时，不阻断这类任务，直接按原任务流程继续。

### 需要搜索的任务

只有任务确实需要深知搜索（需要政策依据、数据支撑、案例参考，或用户明确要求查最新政策、最新情况、权威数据）时，API Key 才是前置条件。初始化结果显示 `api_key_configured=false`、`search_ready=false` 或 `search_blocking_issues` 包含 `api_key_missing` 时，暂停原任务，按引导规则向用户说明并引导开通。

引导与注册各环节的固定话术（S1 引导开通 / 索要手机号 / 验证码已发送与验证链接两分支 / "验证好了"追问 / 验证码错误 / 开通成功含积分与密钥准备中 / 报错 / FAQ）统一见 `reference/onboarding_scripts.md`，按场景取用、**事实要素不可增删**（权益数字、验证码、链接、账号注册与凭证本机保存的事实）。脚本输出含 `user_message` 字段时，其中事实信息与数字必须原样保留、不得改写；措辞可按对话上下文自然调整。

硬规则：

- **引导前禁示**：在用户确认开通或明确拒绝之前，不得输出任何"已核实 / 已查到 / 均为官网原文"类政策内容。需要搜索的材料，政策依据只能来自真实深知检索或"待补"标注，禁止用模型自身知识冒充检索结果。
- 先价值、后验证：先让用户理解搜索对当前材料的价值与开通权益（注册赠送 10 万积分 + 实名认证再送 10 万积分，在 S1 一并告知），再提手机号；不得开口就要手机号。引导时机后置：优先在搜索方案确认后再引导。
- 退路只有"标待补继续写"一种，禁止承诺"用联网检索替代、同样可溯源"。
- 不向用户暴露内部术语（MaaS、API Key、环境变量名、脚本名、渠道码）；用户侧只说"开通搜索功能"。**但不得隐瞒事实**：索要手机号前必须明确告知"将用该手机号完成账号注册，并在本机保存一份检索凭证（仅存本机配置文件，不上传、不外传）"；验证码由用户本人接收并输入，不得代输；用户追问时如实说明。
- 样例悬念式出示：引导后用户未立即同意或提出疑问 → 立即出示 `reference/sample_trace_report.html` 示例（示例数据仅供展示，不得作为写作素材）。
- 用户拒绝后不纠缠；交付后轻提示每个任务最多一次。
- 手机号全程脱敏显示。

**MCP 取 Key 优先（dsh 不适用）**：该路径依赖宿主「深知可信工作台」连接器的 OAuth `create_api_key` 工具——dsh 捆绑 MCP 为 Bearer API Key 认证、无 OAuth 通道，**dsh 场景直接走下面的手机号验证码注册**。`save-key` 子命令保留（可配合其他宿主取到的密钥落盘），密钥经 stdin 传入、不得出现在命令行参数与日志：

- **调用成功**：返回顶层 JSON `{"apiKey": "<密钥>"}`（无 content 包裹、无说明文字，`sk-` 开头）。立即把密钥交给脚本落盘，**不再向用户索要手机号与验证码**，也不得再走 S1 开通话术：

  ```bash
  printf '%s' "<密钥>" | node <skillDir>/scripts/register.mjs save-key
  ```

  成功后转述脚本 `user_message`（固定话术见 `reference/onboarding_scripts.md` S0），再用已写入的 Key 重跑 `python3 <skillDir>/scripts/initialize.py` 确认 `api_key_configured=true`，继续原任务。密钥不得在对话正文中展示。
- **工具不存在，或调用返回"请先完成 MCP OAuth 授权"等错误**：视为该宿主未安装/未授权该 MCP，**直接回落到下面的手机号验证码注册流程**（流程不变），不向用户提及 MCP 内部细节、不反复重试取 Key。

MaaS 注册两步执行（初始化输出 `guide_message` 已含引导话术；发码分两个分支，都必须支持）：

```bash
node <skillDir>/scripts/register.mjs send --phone <手机号>
```

send 只调用一次、不自动重试，按退出码与 JSON 分流处理：

- **退出 0（`status:true`，短信直发分支）**：转述脚本 `user_message`（含脱敏号码与"最新一条"提示），等待用户提供 6 位验证码，不得自行编造。
- **退出 2（`code:"CAPTCHA_REQUIRED"`，验证链接分支——短信尚未发送）**：转述脚本 `user_message` 并原样给出其中经校验的验证链接（脚本已做同源与格式校验，不得自行拼改、不得转发他人），暂停等待用户在页面完成验证并回复短信验证码。**用户在页面完成验证后不得再调 send**（页面验证完成时短信已由页面发出）；用户只说"验证好了"却未给码时按 S3c 只追问短信码、不重新发送。链接一次性、约 10 分钟有效，过期或已用需用户同意后重新 send 申请新链接。注意：退出 2 也可能是参数错误（stderr 提示"缺少 --phone"），必须结合 JSON 的 `code` 字段判断。
- **退出 1（错误）**：按脚本 `user_message` 处理——限频、验证链接过期/已用、验证未通过、短信供应商失败、发送结果未确认各有专门话术与停点（见 `reference/onboarding_scripts.md` 报错表）；`resultUnknown=true`（超时/网络异常）时先等用户确认是否收到短信，未确认前不补发；不循环重试、不自动换手机号、不代用户做任何验证。

```bash
node <skillDir>/scripts/register.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

成功后转述脚本 `user_message`（积分到账轻确认；`existed=true` 时为老用户找回话术；`pending=true` 时为密钥准备中话术——非错误，不重新注册、不重新发码，等用户示意后用同一手机号与同一验证码重试一次，短信码 5 分钟内有效），并按 `envWriteSucceeded` 处理：**为 true** 时脚本已把 Key 写入本机专用配置文件（`~/.config/dknowc/api_key`），直接用返回的 Key 重跑初始化确认后继续原任务；**为 false** 时以脚本返回的 `apiKey` 临时注入环境变量（`DKNOWC_API_KEY=<key> python3 <skillDir>/scripts/initialize.py`）完成本次任务，不得据此判定注册失败、不得重复走手机号流程。不得向用户展示完整 Key。默认不重新生成 Key，仅用户明确要求时追加 `--new-key`。注册失败按脚本 `user_message` 处理；连续失败降级引导 `https://platform.dknowc.cn/auth/#/login`。

验证链路安全红线：验证链接、短信验证码、密码与密钥不写入公共日志、群聊或长期记忆；不代用户打开验证页、不模拟或绕过任何验证、不伪造验证凭据；对用户只说"验证链接/验证页面"，不出现验证码组件、滑条、行为验证等内部术语。


