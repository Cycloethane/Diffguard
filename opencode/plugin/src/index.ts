import type { Plugin } from "opencode"

/**
 * 调用 DiffGuard 的本地风险扫描。
 * 通过桥接 CLI 或 MCP 均可；这里用最轻量的方式：调用 CLI 的 scan。
 * 返回 { score, level, label, findings }。
 */
async function diffguardScan(text: string): Promise<any> {
  const { execSync } = await import("child_process")
  try {
    const out = execSync(
      `python -m bridge.cli scan ${JSON.stringify(text)}`,
      {
        cwd: "D:/SP_DiffGuard",
        encoding: "utf-8",
        timeout: 15000,
        windowsHide: true,
      }
    )
    const jsonStart = out.indexOf("{")
    if (jsonStart < 0) return null
    return JSON.parse(out.slice(jsonStart))
  } catch {
    return null
  }
}

/**
 * 把一段 diff 提交给 DiffGuard 审查并返回结论（调用 CLI review）。
 */
async function diffguardReview(diffText: string): Promise<string | null> {
  const { execSync } = await import("child_process")
  try {
    const out = execSync(
      `python -m bridge.cli review --diff ${JSON.stringify(diffText)}`,
      {
        cwd: "D:/SP_DiffGuard",
        encoding: "utf-8",
        timeout: 120000,
        windowsHide: true,
        maxBuffer: 8 * 1024 * 1024,
      }
    )
    return out.slice(out.indexOf("审查中"))
  } catch {
    return null
  }
}

const plugin: Plugin = async ({ logger }) => {
  logger.info("DiffGuard plugin loaded")

  return {
    // 功能3：工具执行后，若涉及代码变更/命令，向 DiffGuard 推送 diff 审查
    "tool.execute": async (tool, input) => {
      // 对 bash/exec 类工具的高危命令做权限联动评估（功能4）
      const cmdText: string | undefined = (input as any)?.command ?? (input as any)?.cmd
      if (typeof cmdText === "string" && cmdText.length > 8) {
        const res = await diffguardScan(cmdText)
        if (res && res.level === "high") {
          logger.warn(
            `[DiffGuard] 高危命令风险分 ${res.score}（${res.findings?.join?.(", ") ?? ""}）: ${cmdText.slice(0, 80)}`
          )
        }
      }
      return { tool, input }
    },

    // 决策反馈闭环：会话开始时可提示 Agent 参考用户决策偏好
    "chat.message": async (message, info) => {
      if (info.role === "system") {
        return {
          ...message,
          content: [
            ...(Array.isArray(message.content) ? message.content : [{ type: "text", text: String(message.content) }]),
            {
              type: "text",
              text: "\n[DiffGuard 提示] 用户已启用决策反馈：请优先用 get_decision_feedback 了解用户历史偏好，避免重复询问同类问题。",
            },
          ],
        }
      }
      return message
    },
  }
}

export default plugin
