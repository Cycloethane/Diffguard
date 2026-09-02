# -*- coding: utf-8 -*-
"""DiffGuard × ZCode 插件引导脚本。

hooks.json(process 型钩子)与 plugin.json(mcpServers)均以
    python <本文件> <子命令>
方式拉起。子命令:

    mcp                启动 DiffGuard MCP server(stdio)
    pre_tool_use       PreToolUse 风险扫描钩子
    permission_request PermissionRequest 审计钩子

DiffGuard 源码根目录解析顺序(克隆/打包位置可能随安装方式变化):
    1. 环境变量 DIFFGUARD_HOME
    2. 本文件上级目录(开发模式:zcode/ 位于仓库内)
    3. %APPDATA%/DiffGuard/source_path.txt 安装标记(install-zcode 写入)
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _looks_like_root(path: str) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, "main.py"))


def _resolve_root() -> str:
    env_home = os.environ.get("DIFFGUARD_HOME", "")
    if _looks_like_root(env_home):
        return env_home
    dev_root = os.path.dirname(_HERE)
    if _looks_like_root(dev_root):
        return dev_root
    marker = os.path.join(os.environ.get("APPDATA", ""), "DiffGuard", "source_path.txt")
    try:
        if os.path.isfile(marker):
            marked = open(marker, encoding="utf-8").read().strip()
            if _looks_like_root(marked):
                return marked
    except OSError:
        pass
    return dev_root


def main() -> None:
    sys.path.insert(0, _resolve_root())
    command = sys.argv[1] if len(sys.argv) > 1 else "mcp"
    if command == "mcp":
        from bridge.mcp_server import main as mcp_main

        mcp_main()
    elif command == "pre_tool_use":
        from bridge.hooks_runner import pre_tool_use_main

        sys.exit(pre_tool_use_main())
    elif command == "permission_request":
        from bridge.hooks_runner import permission_request_main

        sys.exit(permission_request_main())
    elif command == "ask_user_question":
        from bridge.hooks_runner import ask_user_question_main

        sys.exit(ask_user_question_main())
    else:
        sys.stderr.write("未知子命令: {}（可用: mcp / pre_tool_use / permission_request / ask_user_question）\n".format(command))
        sys.exit(1)


if __name__ == "__main__":
    main()
