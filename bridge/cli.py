# -*- coding: utf-8 -*-
"""DiffGuard CLI：面向 AI Agent 与高级用户的命令行接口。

用法（源码运行）：
    python -m bridge.cli review --diff "..."    审查一段 diff
    python -m bridge.cli review --file path      审查某文件的 git diff
    python -m bridge.cli history --limit 10      查看最近审查历史
    python -m bridge.cli permissions --limit 10  查看最近权限记录
    python -m bridge.cli decisions --limit 10    查看最近决策反馈
    python -m bridge.cli decision-stats          用户决策偏好统计
    python -m bridge.cli scan "text"             本地风险扫描
    python -m bridge.cli submit-decision --question ... --options '[...]'
    python -m bridge.cli status                   当前状态
    python -m bridge.cli mcp                      启动 MCP stdio server
    python -m bridge.cli install-git-hook --dir . 安装 pre-commit 审查钩子
    python -m bridge.cli install-zcode --dir . --scope workspace
                                        把 DiffGuard 注册进 ZCode（MCP+hooks+skill+命令）
    python -m bridge.cli uninstall-zcode --dir . --scope workspace
                                        移除 ZCode 集成

零第三方依赖（仅标准库 + 项目自身模块）。
"""

import argparse
import json
import os
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_options(text: str) -> list[dict]:
    """把 'A) x B) y' 或 JSON 字符串解析为选项列表。"""
    text = text.strip()
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # 简单解析：A) xx / A. xx / 1. xx
    import re

    pat = re.compile(r"(?:^|\s)([A-Z0-9])\s*[).、]\s*([^A-Z0-9)].*?)(?=(?:\s[A-Z0-9]\s*[).、])|$)")
    matches = pat.findall(text)
    return [{"key": k, "text": t.strip()} for k, t in matches]


def cmd_review(args: argparse.Namespace) -> int:
    from core.reviewer import analyze_diff
    from models.config import load_config

    cfg = load_config()
    if args.diff:
        diff_text = args.diff
    elif args.file:
        import subprocess

        try:
            proc = subprocess.run(
                ["git", "diff", args.base, "--", args.file],
                capture_output=True, text=True, cwd=os.getcwd(), timeout=30,
            )
            diff_text = proc.stdout or ""
            if not diff_text.strip():
                print(f"[提示] 未获取到 {args.file} 的 diff（可能无变更或不在 git 仓库）。")
                return 0
        except Exception as exc:
            print(f"[错误] 获取 git diff 失败: {exc}")
            return 1
    elif args.stdin:
        diff_text = sys.stdin.read()
    else:
        print("请提供 --diff 或 --file 或 --stdin")
        return 2
    print("审查中...（调用模型）")
    for chunk in analyze_diff(diff_text, cfg):
        sys.stdout.write(chunk)
    sys.stdout.write("\n")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    from models.history import get_recent

    recs = get_recent(args.limit)
    if not recs:
        print("暂无审查历史。")
        return 0
    for r in recs:
        print(f"[{r.timestamp:%Y-%m-%d %H:%M}] id={r.id} {r.title} | 文件={r.file_count} 风险={r.risk_level} 决策={r.user_decision}")
    return 0


def cmd_permissions(args: argparse.Namespace) -> int:
    from models.permission_history import get_recent_permissions

    recs = get_recent_permissions(args.limit)
    if not recs:
        print("暂无权限审批记录。")
        return 0
    for r in recs:
        print(f"[{r.timestamp:%Y-%m-%d %H:%M}] id={r.id} {r.source} | {r.action} {r.target[:60]} 风险={r.risk_score} 决策={r.user_decision}")
    return 0


def cmd_decisions(args: argparse.Namespace) -> int:
    from models.decision_history import get_recent_decisions

    recs = get_recent_decisions(args.limit)
    if not recs:
        print("暂无决策反馈记录。")
        return 0
    for r in recs:
        print(f"[{r.timestamp:%Y-%m-%d %H:%M}] id={r.id} {r.question} → 用户选择 {r.user_decision or '(跳过)'}")
    return 0


def cmd_decision_stats(_args: argparse.Namespace) -> int:
    from models.decision_history import decision_stats

    stats = decision_stats(200)
    print(f"决策总数: {stats['total']}，已作选择: {stats['with_choice']}")
    print("来源分布: " + ("，".join(f"{k}:{v}" for k, v in stats["by_source"].items()) or "无"))
    print("最近偏好:")
    for p in stats["recent_preferences"][-10:]:
        print(f"  - {p['timestamp'][:16]} {p['question']} → {p['chosen']}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    from core.risk_score import score_text
    from models.config import load_config

    text = args.text or (sys.stdin.read() if not sys.stdin.isatty() else "")
    if not text:
        print("请提供要扫描的文本。")
        return 2
    res = score_text(text, load_config())
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_submit_decision(args: argparse.Namespace) -> int:
    from bridge import store

    options = _parse_options(args.options)
    if len(options) < 2:
        print("[错误] 需要至少两个选项，如：--options 'A) 单文件 B) 目录'")
        return 2
    ok = store.write_agent_decision(args.question, options, args.context, source=args.source)
    if not ok:
        print("[错误] 写入决策请求失败。")
        return 1
    print(f"已提交决策请求：{args.question}（{len(options)} 个选项）。请等待用户在 DiffGuard 浮窗中选择。")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    from models.config import load_config
    from models.decision_history import decision_stats

    cfg = load_config()
    stats = decision_stats(50)
    print(f"已配置 API: {bool(cfg.api_key)}")
    print(f"模型: {cfg.model}")
    print(f"决策助手: {cfg.decision_assistant}（水平 {cfg.decision_level}）")
    print(f"权限监控: {cfg.permission_monitor}")
    print(f"剪贴板监听: {cfg.auto_clipboard}")
    print(f"OpenCode 桥接: {cfg.agent_bridge} | MCP: {cfg.agent_mcp}")
    print(f"决策总数: {stats['total']}")
    return 0


def cmd_mcp(_args: argparse.Namespace) -> int:
    from bridge.mcp_server import run_stdio_loop

    run_stdio_loop()
    return 0


def cmd_install_git_hook(args: argparse.Namespace) -> int:
    """安装 pre-commit 钩子：提交前自动让 DiffGuard 审查暂存 diff。"""
    hooks_dir = os.path.join(args.dir, ".git", "hooks")
    if not os.path.isdir(hooks_dir):
        print(f"[错误] 不是 git 仓库目录: {args.dir}")
        return 1
    hook_path = os.path.join(hooks_dir, "pre-commit")
    script = _GIT_HOOK_TEMPLATE.replace("__DIFFGUARD_CWD__", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(hook_path, 0o755)
        print(f"已安装 pre-commit 钩子: {hook_path}")
    except OSError as exc:
        print(f"[错误] 安装钩子失败: {exc}")
        return 1
    return 0


# ----------------------------------------------------------------------
# ZCode 集成安装器
# ----------------------------------------------------------------------
_PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ZCODE_PLUGIN_DIR: str = os.path.join(_PROJECT_ROOT, "zcode")
_BOOTSTRAP: str = os.path.join(_ZCODE_PLUGIN_DIR, "bootstrap.py")
_SKILL_SRC: str = os.path.join(_ZCODE_PLUGIN_DIR, "skills", "diffguard")
_COMMANDS_SRC: str = os.path.join(_ZCODE_PLUGIN_DIR, "commands", "diffguard")

# 钩子条目里用于识别"这是 DiffGuard 安装的"的标记
_OUR_MARKER: str = "bootstrap.py"


def _zcode_paths(scope: str, target_dir: str) -> dict:
    """返回指定作用域下各配置/资源路径。"""
    if scope == "user":
        home = os.path.expanduser("~")
        return {
            "config": os.path.join(home, ".zcode", "cli", "config.json"),
            "skills_dir": os.path.join(home, ".zcode", "skills"),
            "commands_dir": os.path.join(home, ".zcode", "commands"),
        }
    zcode_dir = os.path.join(target_dir, ".zcode")
    return {
        "config": os.path.join(zcode_dir, "config.json"),
        "skills_dir": os.path.join(zcode_dir, "skills"),
        "commands_dir": os.path.join(zcode_dir, "commands"),
    }


def _read_json_file(path: str) -> dict:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_json_file(path: str, data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        print(f"[错误] 写入 {path} 失败: {exc}")
        return False


def _strip_diffguard_entries(config: dict) -> None:
    """移除 config 中 DiffGuard 安装的 MCP server 与 hooks 条目。"""
    servers = (config.get("mcp") or {}).get("servers")
    if isinstance(servers, dict):
        servers.pop("diffguard", None)

    def _clean_event(groups) -> None:
        kept: list = []
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            hooks = group.get("hooks")
            if isinstance(hooks, list) and hooks:
                remaining = [
                    h for h in hooks
                    if not isinstance(h, dict)
                    or _OUR_MARKER not in json.dumps(h, ensure_ascii=False)
                ]
                if len(remaining) != len(hooks):
                    # 移除过 DiffGuard 条目;清空后整个组一并移除(避免残留空壳)
                    if remaining:
                        group["hooks"] = remaining
                        kept.append(group)
                    continue
            kept.append(group)

        if isinstance(groups, list):
            groups[:] = kept

    events = (config.get("hooks") or {}).get("events")
    if isinstance(events, dict):
        for groups in events.values():
            _clean_event(groups)


def _add_diffguard_entries(config: dict, python_exe: str, cwd_dir: str) -> None:
    """向 config 注入 diffguard MCP server 与两个钩子(幂等)。"""
    _strip_diffguard_entries(config)

    mcp = config.setdefault("mcp", {})
    servers = mcp.setdefault("servers", {})
    servers["diffguard"] = {
        "type": "stdio",
        "command": python_exe,
        "args": [_BOOTSTRAP, "mcp"],
        "cwd": cwd_dir,
    }

    hooks = config.setdefault("hooks", {})
    hooks["enabled"] = True
    events = hooks.setdefault("events", {})
    events.setdefault("PreToolUse", []).append(
        {
            "matcher": "Bash|Write|Edit|ApplyPatch",
            "hooks": [
                {
                    "type": "process",
                    "command": python_exe,
                    "args": [_BOOTSTRAP, "pre_tool_use"],
                    "timeoutMs": 15000,
                    "statusMessage": "DiffGuard 风险扫描",
                }
            ],
        }
    )
    events.setdefault("PermissionRequest", []).append(
        {
            "hooks": [
                {
                    "type": "process",
                    "command": python_exe,
                    "args": [_BOOTSTRAP, "permission_request"],
                    "timeoutMs": 10000,
                    "statusMessage": "DiffGuard 权限审计",
                }
            ],
        }
    )


def _copy_tree(src: str, dst: str) -> bool:
    """复制目录树(覆盖目标)。"""
    if not os.path.isdir(src):
        print(f"[错误] 缺少插件资源目录: {src}")
        return False
    try:
        if os.path.isdir(dst):
            import shutil

            shutil.rmtree(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        import shutil

        shutil.copytree(src, dst)
        return True
    except OSError as exc:
        print(f"[错误] 复制 {src} -> {dst} 失败: {exc}")
        return False


def _remove_tree(path: str) -> None:
    try:
        if os.path.isdir(path):
            import shutil

            shutil.rmtree(path)
    except OSError:
        pass


def _write_source_marker() -> None:
    """写入源码位置标记,供 zcode/bootstrap.py 在插件缓存模式下定位根目录。

    位置与 bootstrap.py 的读取端一致(%APPDATA%/DiffGuard/source_path.txt)。
    """
    try:
        base = os.path.join(os.environ.get("APPDATA", ""), "DiffGuard")
        if not base:
            return
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "source_path.txt"), "w", encoding="utf-8") as f:
            f.write(_PROJECT_ROOT)
    except OSError as exc:
        print(f"[警告] 写入源码位置标记失败: {exc}")


def cmd_install_zcode(args: argparse.Namespace) -> int:
    """把 DiffGuard 注册进 ZCode(MCP + hooks + skill + 命令)。"""
    if not os.path.isfile(_BOOTSTRAP):
        print(f"[错误] 未找到插件引导脚本: {_BOOTSTRAP}")
        return 1
    target_dir = os.path.abspath(args.dir)
    if args.scope == "workspace" and not os.path.isdir(target_dir):
        print(f"[错误] 目标目录不存在: {target_dir}")
        return 1

    paths = _zcode_paths(args.scope, target_dir)
    config = _read_json_file(paths["config"])
    _add_diffguard_entries(config, sys.executable, target_dir)
    if not _write_json_file(paths["config"], config):
        return 1

    ok_skill = _copy_tree(_SKILL_SRC, os.path.join(paths["skills_dir"], "diffguard"))
    ok_cmds = _copy_tree(_COMMANDS_SRC, os.path.join(paths["commands_dir"], "diffguard"))
    if not (ok_skill and ok_cmds):
        return 1
    _write_source_marker()

    print(f"已安装 DiffGuard × ZCode 集成（scope={args.scope}）:")
    print(f"  - MCP server 与 hooks: {paths['config']}")
    print(f"  - Skill: {os.path.join(paths['skills_dir'], 'diffguard')}")
    print(f"  - 命令: {os.path.join(paths['commands_dir'], 'diffguard')}（/diffguard:review 等）")
    print("重启 ZCode 会话后生效。")
    return 0


def cmd_uninstall_zcode(args: argparse.Namespace) -> int:
    """移除 DiffGuard 的 ZCode 集成条目。"""
    target_dir = os.path.abspath(args.dir)
    paths = _zcode_paths(args.scope, target_dir)
    config = _read_json_file(paths["config"])
    _strip_diffguard_entries(config)
    if not _write_json_file(paths["config"], config):
        return 1
    _remove_tree(os.path.join(paths["skills_dir"], "diffguard"))
    _remove_tree(os.path.join(paths["commands_dir"], "diffguard"))
    print(f"已卸载 DiffGuard × ZCode 集成（scope={args.scope}）。")
    return 0


_GIT_HOOK_TEMPLATE = r'''#!/usr/bin/env python
# -*- coding: utf-8 -*-
# DiffGuard pre-commit review hook (auto-installed).
# 提交前对暂存区 diff 做一次本地风险扫描；发现高风险时阻止提交。
# 设置环境变量 DIFFGUARD_HOOK_SKIP=1 可临时跳过。
import os
import sys

if os.environ.get("DIFFGUARD_HOOK_SKIP") == "1":
    sys.exit(0)

sys.path.insert(0, "__DIFFGUARD_CWD__")

try:
    import subprocess

    proc = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True, timeout=30)
    diff_text = proc.stdout or ""
except Exception:
    sys.exit(0)

if not diff_text.strip():
    sys.exit(0)

try:
    from core.risk_score import score_text
    from models.config import load_config

    res = score_text(diff_text, load_config())
except Exception:
    sys.exit(0)

print("[DiffGuard] pre-commit review: risk {} ({})".format(res.get("score", 0), res.get("label", "?")))
for f in res.get("findings", []):
    print("  WARN " + str(f))

if res.get("level") == "high":
    print("[DiffGuard] High-risk changes detected, commit blocked. "
          "Set DIFFGUARD_HOOK_SKIP=1 to override.")
    sys.exit(1)
sys.exit(0)
'''


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="diffguard", description="DiffGuard CLI")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("review", help="AI 审查 diff")
    p.add_argument("--diff", help="diff 文本")
    p.add_argument("--file", help="文件路径（取 git diff）")
    p.add_argument("--base", default="HEAD", help="git 基准引用")
    p.add_argument("--stdin", action="store_true", help="从 stdin 读取 diff")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("history", help="查看审查历史")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("permissions", help="查看权限记录")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_permissions)

    p = sub.add_parser("decisions", help="查看决策反馈")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_decisions)

    p = sub.add_parser("decision-stats", help="决策偏好统计")
    p.set_defaults(func=cmd_decision_stats)

    p = sub.add_parser("scan", help="本地风险扫描")
    p.add_argument("text", nargs="?", help="要扫描的文本")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("submit-decision", help="提交决策请求给 DiffGuard")
    p.add_argument("--question", required=True)
    p.add_argument("--options", required=True, help="如 'A) 单文件 B) 目录' 或 JSON")
    p.add_argument("--context", default="")
    p.add_argument("--source", default="CLI", help="提交来源标识（如 ZCode）")
    p.set_defaults(func=cmd_submit_decision)

    p = sub.add_parser("status", help="当前状态")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("mcp", help="启动 MCP stdio server")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("install-git-hook", help="安装 pre-commit 审查钩子")
    p.add_argument("--dir", default=".", help="git 仓库根目录")
    p.set_defaults(func=cmd_install_git_hook)

    p = sub.add_parser(
        "install-zcode",
        help="把 DiffGuard 注册进 ZCode（MCP + hooks + skill + 命令）",
    )
    p.add_argument("--dir", default=".", help="目标仓库根目录（workspace 作用域）")
    p.add_argument("--scope", choices=["workspace", "user"], default="workspace",
                   help="workspace=写入目标仓库 .zcode/；user=写入 ~/.zcode/（全局）")
    p.set_defaults(func=cmd_install_zcode)

    p = sub.add_parser("uninstall-zcode", help="移除 DiffGuard 的 ZCode 集成")
    p.add_argument("--dir", default=".", help="目标仓库根目录（workspace 作用域）")
    p.add_argument("--scope", choices=["workspace", "user"], default="workspace")
    p.set_defaults(func=cmd_uninstall_zcode)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
