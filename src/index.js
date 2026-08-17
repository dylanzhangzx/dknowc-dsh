/**
 * dknowc-dsh —— 深知可信办公全家桶 skill provider
 *
 * 把 3 个内嵌 skill（dknowc-trusted-consulting / dknowc-trusted-search /
 * dknowc-official-doc-writer）注册进 dsh 的 `ctx.skills`，使它们出现在
 * 会话的 <available_skills> 目录中，可被模型的 `skill` 工具加载。
 *
 * 注册范式对照官方 `@deepseek-ai/dsh-skill-badge`：
 *   - 每个 skill 的 SKILL.md 作为 body
 *   - 每个 skill 目录作为 resourceBase（kind: directory）
 *   - 模型按 SKILL.md 内的相对路径（scripts/...）解析资源与脚本
 */
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const PROVIDER_NAME = 'dknowc-dsh'

/** 内嵌 skill 清单：目录名必须与 frontmatter 的 kebab-case name 一致。 */
const SKILLS = [
  {
    name: 'dknowc-trusted-consulting',
    description:
      '当用户咨询政策法规、政务办事、税务社保、公积金、企业补贴、资质证照、行业标准、公共服务、合规义务、企业经营政策，或要求权威依据、可信溯源、带角标答案时，使用深知可信咨询。输出带真实来源角标的咨询答案并默认生成本轮可点击溯源 HTML。',
  },
  {
    name: 'dknowc-trusted-search',
    description:
      '当用户需要检索权威材料、政策法规/标准原文、政策清单、可点击溯源、知识专库、多地域政策素材收集与对比核验、企业补贴与税惠材料核验、合规依据核验，或明确要求深度搜索、深度分析、全面查找、多轮核验、完整调研方案时，使用深知可信搜索。本 skill 负责检索与核验材料，交付直接答案、可点击溯源 HTML 与干净 Markdown；如用户要求把素材写成正式报告、调研报告、分析报告或公文（如"帮我写一份××报告"），应改用深知公文写作。',
  },
  {
    name: 'dknowc-official-doc-writer',
    description:
      '当用户要求写一份正式文稿、成稿或报告——如"帮我写一份××分析报告"、"写一份××调研报告"、"写一份××政策分析报告"、"写一份××工作报告/总结/方案/汇报材料"，或要求起草通知、请示、报告、函、复函、批复、会议纪要、通报、通告、公告、意见、管理办法、发言稿、讲话稿、经验材料等正式文种时，使用深知公文写作。正式交付支持生成 Word 文档，用户明确需要时可生成红头文件；涉及政策依据时可内部通过深知可信搜索（MCP）获取素材并生成可信溯源报告。若用户只是要求检索/查证政策原文或做深度搜索核验而不是把素材写成成稿，应改用深知可信搜索。',
  },
]

const candidates = SKILLS.map((skill) => ({
  name: skill.name,
  description: skill.description,
  invocation: { modelInvocable: true, userInvocable: true },
  provider: PROVIDER_NAME,
  source: 'bundled',
  resourceBase: {
    kind: 'directory',
    path: fileURLToPath(new URL(`../skills/${skill.name}/`, import.meta.url)),
  },
  rank: 600, // bundled 层 rank，低于用户/项目层，允许上层覆盖
  locator: skill.name,
}))

const provider = {
  name: PROVIDER_NAME,
  list: () => Promise.resolve(candidates),
  async get(candidate) {
    const skill = SKILLS.find((s) => s.name === candidate.name)
    if (!skill) return undefined
    const bodyUrl = new URL(`../skills/${skill.name}/SKILL.md`, import.meta.url)
    const content = await readFile(bodyUrl, 'utf8')
    return {
      name: skill.name,
      description: skill.description,
      invocation: { modelInvocable: true, userInvocable: true },
      provider: PROVIDER_NAME,
      source: 'bundled',
      resourceBase: {
        kind: 'directory',
        path: fileURLToPath(new URL(`../skills/${skill.name}/`, import.meta.url)),
      },
      content,
    }
  },
}

/** Cordis 插件名。 */
export const name = 'dknowc-dsh'

/**
 * 依赖服务：
 * - skills：注册 bundled skill provider
 * - shellEnv：把 DKNOWC_API_KEY 显式注入 dsh 的 bash 子进程（dsh 安全机制会
 *   清理名字含 KEY 的隐式环境变量，但 shell-env 是官方显式通道，注入后脚本
 *   子进程能读到 DSH_DKNOWC_API_KEY，从而让 initialize.py 的门禁能真实检查）
 */
export const inject = ['skills', 'shellEnv']

/** 注册 bundled skill provider + shell-env Key 注入。 */
export function apply(ctx) {
  ctx.skills.registerProvider(() => provider)

  // 显式转发 DKNOWC_API_KEY：dsh 的 bash 工具会清理名字含 KEY 的隐式变量，
  // 通过 shell-env 注册表以 DSH_ 前缀显式注入，脚本子进程即可读取。
  ctx.shellEnv.register({
    name: 'dknowc-dsh',
    variables: {
      DSH_DKNOWC_API_KEY: {
        description:
          '深知可信接口 API Key（来源为 dsh 主进程环境变量 DKNOWC_API_KEY）。供深知系列 skill 的脚本检查门禁与兜底直连使用；MCP 场景下接口认证由 MCP Bearer 承担，本变量仅用于门禁判断与离线兜底。',
      },
    },
    resolve: () =>
      process.env.DKNOWC_API_KEY ? { DSH_DKNOWC_API_KEY: process.env.DKNOWC_API_KEY } : {},
  })
}
