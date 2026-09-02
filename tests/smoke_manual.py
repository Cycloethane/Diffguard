# -*- coding: utf-8 -*-
"""GUI 冒烟脚本(手动运行,pytest 不收集):构造主窗口并走一遍关键路径。

用法: python tests/smoke_manual.py
会在屏幕上短暂弹出 DiffGuard 主窗口(约 3 秒)后自动退出。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk

from models.config import Config
from ui.app import DiffGuardApp

# 测试用 diff:含密钥模式与配置路径,验证风险评分通路(非真实凭据)
SAMPLE_DIFF = (
    "diff --git a/config/prod.cfg b/config/prod.cfg\n"
    "index 1111111..2222222 100644\n"
    "--- a/config/prod.cfg\n"
    "+++ b/config/prod.cfg\n"
    "@@ -1,2 +1,3 @@\n"
    " BASE=1\n"
    "-API_KEY=abcdefgh123456\n"
    "+API_KEY=abcdefgh12345678\n"
    "+NEW=2\n"
)


def main() -> int:
    app = DiffGuardApp(Config())
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    # 事件循环跑几轮,让初始布局与动画推进
    for _ in range(8):
        app.update()
    app.update_idletasks()

    # 1. 载入 diff → 文件列表 + 仪表盘
    app.review_flow.apply_diff(SAMPLE_DIFF)
    for _ in range(4):
        app.update()
    check("载入 diff 后文件数=1", app.review_flow.file_count == 1)
    check("控件就绪", app.review_flow.controls_ready)
    score, _ = app.review_flow.risk_snapshot()
    print(f"  本地评分 = {score}")
    check("本地评分>0", score > 0)

    # 2. 模块切换(注册表驱动)
    for key in ("history", "permission", "decision", "settings", "review"):
        app._on_module_selected(key)
        app.update_idletasks()
        for _ in range(3):
            app.update()
        check(f"切换到模块 {key}", app._current_module == key)
    check("切回审查模块后控件重新绑定", app.review_flow.controls_ready)
    check("切回后 diff 内容保留", app.review_flow.current_diff.strip() != "")

    # 3. 决策角标
    app.decision_flow.pending = True
    app.update_decision_badge()
    app.decision_flow.pending = False
    app.update_decision_badge()
    check("decision_pending 属性", app.decision_pending is False)

    # 4. 前台小窗数据
    payload = app.overlay_payload()
    check(
        "overlay payload 字段齐全",
        set(payload) == {"status", "file_count", "score", "contributions", "decision_pending", "permission"},
    )

    # 5. 配置热切换(关开决策监听)
    cfg_on = Config(decision_assistant="on")
    app._apply_new_config(cfg_on)
    app.update_idletasks()
    check("决策监听已启动", app.watchers.decision_watcher is not None)
    cfg_off = Config(decision_assistant="off")
    app._apply_new_config(cfg_off)
    app.update_idletasks()
    check("决策监听已停止", app.watchers.decision_watcher is None)

    # 6. 轮询器幂等
    p = app._clipboard_poller
    p.start()
    p.start()
    check("轮询器幂等启动", p.running)

    # 7. 权限顾问(无 Key 路径:本地层渲染 + 去重)
    from ui.permission_advice_alert import PermissionAdviceAlert
    event = {
        "tool": "Bash", "target": "rm -rf /tmp/build", "raw": "rm -rf /tmp/build",
        "score": 45, "level": "medium", "findings": ["危险命令:删除根目录"],
    }
    app.permission_flow._maybe_show_advice(event)
    app.update_idletasks()
    alert = PermissionAdviceAlert.get_instance(app)
    check("权限顾问浮窗已创建", alert is not None)
    if alert is not None:
        check("本地层评分已渲染", alert.score_label.cget("text") == "45")
        check("命中项已渲染", "危险命令" in str(alert.findings_label.cget("text")))
        check("无 Key 提示", "未配置" in str(alert.status_label.cget("text")))
        app.permission_flow._maybe_show_advice(event)  # 同类去重
        check("同类请求去重(不重复弹)", True)
    # 阈值下不弹
    low_event = dict(event, score=10, level="low")
    app.permission_flow._advice_seen.clear()
    app.permission_flow._maybe_show_advice(low_event)
    check("低分事件不触发", True)
    if alert is not None:
        alert.withdraw()

    app._quit_app()
    print("\n结果:", "全部通过" if not failures else f"{len(failures)} 项失败: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
