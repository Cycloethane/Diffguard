---
name: diffguard:scan
description: 用 DiffGuard 本地风险扫描检查一段文本/命令/文件内容(不调用 AI,秒级)
---

# DiffGuard 本地风险扫描

对给定内容做本地风险扫描:

1. 若 $ARGUMENTS 是文件路径:读取文件内容;若是命令或任意文本:直接使用。
2. 调用 diffguard MCP 的 `scan_risk` 工具(`text` = 待扫描内容)。
3. 汇报结果:风险分(0-100)、等级(极低/低/中/高/极高)、命中项列表。
4. `level == "high"` 时,明确建议用户不要执行/提交,并说明命中原因。
