# 个人素材库与写作偏好

本文件是本机个人状态（素材库 `knowledge-base/`、写作偏好 `config/writing_preferences.json`）的完整使用规则。二者均只对当前用户生效、不随公开包分发、不上传；初始化结果的 `local_memory` 字段返回数量，数量大于 0 时写作任务应先检索素材库并应用偏好。

## 一、个人素材库（knowledge-base/）

用户提供的材料（单位资料、政策文件、数据资料、历史文稿、业务口径等）默认只在当轮使用、不留存。以下情况才存入素材库：

- 用户明确说"存下来""记住这份材料""加到素材库"等 → 直接保存。
- Agent 判断材料有长期复用价值（单位基本信息、常用政策依据、历史成稿、内部业务口径），主动建议保存并说明用途 → 用户确认后保存。

未经用户确认，不得擅自把材料写入素材库；一次性使用的内容（单次任务草稿、临时改稿素材）不保存。

保存与检索命令：

```bash
python3 scripts/local_memory.py kb save <文件> --category <分类> --tags <场景标签> --note <备注> [--title <标题>]
python3 scripts/local_memory.py kb list [--category <分类>] [--tag <标签>]
python3 scripts/local_memory.py kb search <关键词> [--category <分类>]
python3 scripts/local_memory.py kb remove <素材ID>    # 必须先经用户确认
```

分类固定六类：`unit-profile`（单位资料）、`policy`（政策文件）、`data`（数据资料）、`past-docs`（历史文稿）、`business-rules`（业务口径）、`misc`（其他）；场景标签按写作场景打（如：通知、请示、总结、汇报材料）。

素材使用规则：

- 正式写作需要材料支撑时，先检索素材库，命中后读取对应文件作为用户材料使用，优先级与用户当轮提供的材料相同，高于搜索素材。
- 素材库材料是用户私有材料，其中的单位名称、数据、口径按用户提供材料对待，可直接使用；但仍须按 `reference/fact_discipline.md` 保持状态强度，不得过度推断。
- 素材库不足或未命中时，再按搜索规则进入深知搜索流程，不得把素材库检索替代必要的政策核验。
- 删除素材必须先向用户确认。

## 二、写作偏好（writing_preferences.json）

用户在写作过程中表达的重复性习惯，经确认后沉淀为偏好，分三类：

- `content`（内容习惯）：如"总结里要写党建部分""问题分析不超过三条"。
- `format`（排版习惯）：如"标题不用问句""落款日期用中文数字"。
- `phrasing`（表达习惯）：如"不用'赋能''抓手'这类词""称呼统一用'贵单位'"。

沉淀时机：用户明确说"以后都这样写""记住这个习惯"→ 直接保存；用户在某次修改中纠正了 Agent 的写法且该纠正具有一般性 → Agent 主动询问"是否把这条作为你的常用写作偏好"，确认后保存。

```bash
python3 scripts/local_memory.py pref save --type <content|format|phrasing> --scope <通用或文种> --rule <偏好内容> [--source <来源>]
python3 scripts/local_memory.py pref list [--type <类型>] [--scope <范围>]
python3 scripts/local_memory.py pref remove <偏好ID>    # 必须先经用户确认
```

应用规则：

- 每次正式写作前，若偏好数量大于 0，先读取全部偏好；`scope` 命中当前文种或为"通用"的偏好均生效。
- 用户明示的写作偏好优先于文种标准和默认排版；仅红头文件的国标版记位置等强制国标要求例外，冲突时向用户说明。
- 偏好不得与用户当轮要求冲突：当轮要求优先。用户明确否定某条偏好时，应建议删除该条。
- 删除偏好必须先向用户确认。
