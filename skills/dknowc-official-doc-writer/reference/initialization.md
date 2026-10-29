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
- 不向用户暴露内部术语（MaaS、API Key、环境变量名、脚本名、渠道码）；用户侧统一说"开通搜索功能"，**同时必须说清事实**：这一步是**用手机号注册一个检索账号**，注册成功后在本机保存一份检索凭证（仅存本机配置文件，不上传、不外传）；验证码由用户本人接收并输入，不得代输；用户追问时如实说明，不得以"只是开通功能"回避注册事实。
- 样例悬念式出示：引导后用户未立即同意或提出疑问 → 立即出示 `reference/sample_trace_report.html` 示例（示例数据仅供展示，不得作为写作素材）。
- 用户拒绝后不纠缠；交付后轻提示每个任务最多一次。
- 手机号全程脱敏显示。

MaaS 注册三步执行（初始化输出 `guide_message` 已含引导话术）。平台要求 Agent 先答一道文字题再发码，题目由 Agent 当场计算，**不把题目发给用户**：

```bash
node <skillDir>/scripts/register.mjs challenge --phone <手机号>
```

challenge 读取官方注册指引并领题，只调用一次、不自动重试，按退出码与 JSON 分流。**平台回退自动兜底**：若官方指引不可用（文字题接口尚未上线，或平台临时回退到旧版发码接口），challenge 自动改走原有短信直发分支——退出 0 即表示验证码已发送（`code:"SMS_SENT"`），此路径**不需要调用 answer**，直接等用户 6 位验证码；退出 2 为人工验证链接。输出字段 `flow` 为 `agent-text` 表示走文字题流程，为 `legacy` 表示走旧发码分支，两种对用户等价：

- **退出 0（`status:true`）**：JSON 里带 `<question>.prompt` 与 `answerFormat`。直接按题意计算，用非负整数调用下一步；**题目、token、答题过程都不进入对话**。若返回 `reused:true`，表示本机已有同一手机号未过期的题目，直接沿用，不重新请求。
- **退出 2（`code:"HUMAN_REQUIRED"`）**：平台要求人工完成图片验证，转述脚本 `user_message`（含经校验的验证链接），暂停自动流程，等持有人完成验证并提供短信验证码。链接一次性、约 10 分钟有效，仅私下展示给手机号持有人，不得拼改、转发或贴群。
- **退出 1（错误）**：按脚本 `user_message` 处理——限频（`SMS_RATE_LIMIT`）、目标锁定（`AGENT_TEXT_TARGET_LOCKED`）、服务不可用（`AGENT_TEXT_UNAVAILABLE`）、号码被拒（`SMS_REQUEST_REJECTED`）、结果未确认各有专门话术与停点（见 `reference/onboarding_scripts.md` 报错表）；不循环重试、不换手机号、不换接口绕过。

```bash
node <skillDir>/scripts/register.mjs answer --phone <手机号> --answer <非负整数>
```

answer 提交答案；答对即申请发码，按退出码分流：

- **退出 0（`SMS_SENT`）**：转述脚本 `user_message`（含脱敏号码与"最新一条"提示），等用户提供 6 位验证码；不得重复调 answer。
- **退出 3（`AGENT_TEXT_RETRY`）**：答错已换新题，JSON 带新的 `question`。重新计算后再次调用 answer，含首次最多 3 次；**不得把 attempt 重置、不得重复领题刷机会**。
- **退出 2（`HUMAN_REQUIRED`）**：转人工，按上一条的链接话术处理。
- **退出 4（`RESULT_UNKNOWN`）**：发送结果未确认（超时/断网）。先让持有人看手机，**不得自动重发、不得重新领题**；用户确认没收到后再由用户要求重试。
- **退出 1（错误）**：按 `user_message` 停止本轮，不绕过。

```bash
node <skillDir>/scripts/register.mjs register --phone <手机号> --vcode <验证码> --organ 个人 --name 用户
```

成功后转述脚本 `user_message`（积分到账轻确认；`existed=true` 时为老用户找回话术；`pending=true` 时为密钥准备中话术——非错误，不重新注册、不重新发码，等用户示意后用同一手机号与同一验证码重试一次，短信码 5 分钟内有效），并按 `envWriteSucceeded` 处理：**为 true** 时脚本已把 Key 写入本机专用配置文件（`~/.config/dknowc/api_key`），直接用返回的 Key 重跑初始化确认后继续原任务；**为 false** 时以脚本返回的 `apiKey` 临时注入环境变量（`DKNOWC_API_KEY=<key> python3 <skillDir>/scripts/initialize.py`）完成本次任务，不得据此判定注册失败、不得重复走手机号流程。不得向用户展示完整 Key。默认不重新生成 Key，仅用户明确要求时追加 `--new-key`。注册失败按脚本 `user_message` 处理；连续失败降级引导 `https://platform.dknowc.cn/auth/#/login`。

领题状态由脚本自行保存（`~/.config/dknowc/maas_agent_challenge.json`，600 权限，含会话 Cookie、题目与 attempt），challenge 与 answer 之间不需要也不允许手工传 token；发码成功、转人工或终态失败后脚本自动清除。同一手机号存在未过期题目时复用，不重复领题。

验证链路安全红线：验证链接、短信验证码、密码与密钥不写入公共日志、群聊或长期记忆；答题过程、题目 token 与领题会话不进入对话正文、不落盘到工作目录；不代用户打开验证页、不模拟或绕过任何验证、不伪造验证凭据；对用户只说"验证链接/验证页面"，不出现验证码组件、滑条、行为验证等内部术语。


