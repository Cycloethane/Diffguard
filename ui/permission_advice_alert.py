# -*- coding: utf-8 -*-
"""权限顾问置顶浮窗:分析 ZCode 权限请求(是什么/后果/建议),仅作提示。

设计要点(与 DecisionAlert 的差异):
    - 单例置顶,重复请求只更新内容;
    - 两层内容:本地规则层(评分/等级/命中项,即时)+ AI 分析层(流式);
    - **无决策按钮**——用户读完分析后仍在 ZCode 授权弹窗中完成实际选择;
    - 流式协议:#WHAT# / #CONSEQUENCE# / #ADVICE#(JSON,支持跨行合并)/ #ERROR#。
"""

from typing import Any, Optional

import customtkinter as ctk
from loguru import logger

from core.permission_advisor import (
    parse_advice_line,
    parse_consequence_line,
    parse_error_line,
    parse_what_line,
)
from core.risk_score import score_color, score_label
from ui.animation import fade_in_window
from ui.theme import surface, surface_muted, text_color, text_muted

_FG: str = text_color(light=True)
_FG_MUTED: str = text_muted(light=True)
_BG: str = surface(light=True)
_SURFACE: str = surface_muted(light=True)

_POPUP_ALPHA: float = 1.0

# 建议档位 → 展示样式
_ADVICE_STYLES: dict[str, tuple[str, str]] = {
    "allow_once": ("✅ 建议允许一次", "#238636"),
    "always_allow": ("🟡 建议总是允许", "#d29922"),
    "deny": ("❌ 建议拒绝", "#da3633"),
}


class PermissionAdviceAlert(ctk.CTkToplevel):
    """权限顾问单例浮窗(仅提示,无决策按钮)。"""

    _instance: Optional["PermissionAdviceAlert"] = None

    def __init__(self, master: Any) -> None:
        super().__init__(master)
        PermissionAdviceAlert._instance = self
        self._json_buf: str = ""  # #ADVICE# 跨行 JSON 合并缓冲
        self._full_text: list[str] = []  # 供"复制分析"
        self.title("DiffGuard - 权限顾问")
        self.geometry("600x560")
        self.minsize(500, 420)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        self._build_ui()
        self.withdraw()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        card: ctk.CTkFrame = ctk.CTkFrame(self, corner_radius=8)
        card.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        card.grid_rowconfigure(4, weight=1)
        card.grid_columnconfigure(0, weight=1)

        header: ctk.CTkFrame = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text="🔐 ZCode 权限请求分析", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        self.status_label: ctk.CTkLabel = ctk.CTkLabel(
            header, text="", text_color=_FG_MUTED
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        self.info_label: ctk.CTkLabel = ctk.CTkLabel(
            card, text="", anchor="w", justify="left", wraplength=540,
            text_color=_FG_MUTED, font=ctk.CTkFont(size=12),
        )
        self.info_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 4))

        # 本地规则层(即时)
        local_card: ctk.CTkFrame = ctk.CTkFrame(card, fg_color=_SURFACE, corner_radius=8)
        local_card.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        local_card.grid_columnconfigure(1, weight=1)
        self.score_label: ctk.CTkLabel = ctk.CTkLabel(
            local_card, text="--", font=ctk.CTkFont(size=22, weight="bold"), width=64
        )
        self.score_label.grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=8)
        self.findings_label: ctk.CTkLabel = ctk.CTkLabel(
            local_card, text="", anchor="w", justify="left", wraplength=420,
            text_color=_FG_MUTED, font=ctk.CTkFont(size=11),
        )
        self.findings_label.grid(row=0, column=1, sticky="ew", padx=4, pady=(8, 0))
        self.level_label: ctk.CTkLabel = ctk.CTkLabel(
            local_card, text="", anchor="w", font=ctk.CTkFont(size=12, weight="bold")
        )
        self.level_label.grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 8))

        # AI 分析层(三个块,流式填充)
        ai_scroll: ctk.CTkScrollableFrame = ctk.CTkFrame(card, fg_color="transparent")
        ai_scroll.grid(row=4, column=0, sticky="nsew", padx=8, pady=2)
        ai_scroll.grid_columnconfigure(0, weight=1)
        self.what_label = self._build_ai_block(ai_scroll, 0, "这是什么")
        self.consequence_label = self._build_ai_block(ai_scroll, 1, "允许的后果")
        self.advice_label = self._build_ai_block(ai_scroll, 2, "建议怎么处理")

        # 底部:固定提示 + 按钮
        btns: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        btns.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            btns, text="本窗口仅作分析提示，请在 ZCode 弹窗中完成实际选择",
            text_color=_FG_MUTED, font=ctk.CTkFont(size=11), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.copy_btn: ctk.CTkButton = ctk.CTkButton(
            btns, text="复制分析", width=96, height=32, command=self._copy_analysis
        )
        self.copy_btn.grid(row=0, column=1, padx=(6, 0), sticky="e")
        self.close_btn: ctk.CTkButton = ctk.CTkButton(
            btns, text="知道了", width=80, height=32, fg_color=_SURFACE,
            hover_color="#e0e6ee", text_color=_FG, command=self.withdraw,
        )
        self.close_btn.grid(row=0, column=2, padx=(6, 0), sticky="e")

    def _build_ai_block(self, parent: Any, row: int, title: str) -> ctk.CTkLabel:
        """构建一个 AI 分析块:小标题 + 内容标签(初始为…)。"""
        ctk.CTkLabel(
            parent, text=title, font=ctk.CTkFont(size=12, weight="bold"),
            text_color=_FG_MUTED, anchor="w",
        ).grid(row=row * 2, column=0, sticky="ew", padx=6, pady=(8, 0))
        body: ctk.CTkLabel = ctk.CTkLabel(
            parent, text="…", anchor="w", justify="left", wraplength=520,
            font=ctk.CTkFont(size=13),
        )
        body.grid(row=row * 2 + 1, column=0, sticky="ew", padx=6, pady=(0, 4))
        return body

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def show_event(self, event: dict, ai_enabled: bool) -> None:
        """展示一条权限事件的本地层;ai_enabled=False 时提示仅本地分析。"""
        tool: str = str(event.get("tool", "") or "未知工具")
        target: str = str(event.get("target", "") or "")
        score = int(event.get("score", 0) or 0)
        findings = "、".join(str(f) for f in event.get("findings", []) or []) or "无命中"

        self._json_buf = ""
        self._full_text = [f"[{tool}] {target}", f"本地评分 {score}({findings})"]
        self.info_label.configure(text=f"工具：{tool}" + (f"　目标：{target[:60]}" if target else ""))
        color: str = score_color(score)
        self.score_label.configure(text=str(score), text_color=color)
        self.level_label.configure(text=f"本地评级：{score_label(score)}", text_color=color)
        self.findings_label.configure(text=f"命中规则：{findings}")

        self.what_label.configure(text="…", text_color=_FG)
        self.consequence_label.configure(text="…", text_color=_FG)
        self.advice_label.configure(text="…", text_color=_FG)
        if ai_enabled:
            self.status_label.configure(text="分析中…", text_color="#d29922")
        else:
            self.status_label.configure(text="未配置 API Key · 仅本地分析", text_color=_FG_MUTED)
            for lbl in (self.what_label, self.consequence_label):
                lbl.configure(text="（未配置 API Key，仅本地规则分析）", text_color=_FG_MUTED)
            self.advice_label.configure(
                text="建议参考本地评级：" + ("分数较高，谨慎处理" if score >= 40 else "核对目标后处理"),
                text_color=_FG_MUTED,
            )

        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        fade_in_window(self, final_alpha=_POPUP_ALPHA)

    def set_done(self) -> None:
        """AI 分析完成。"""
        self.status_label.configure(text="分析完成", text_color="#238636")

    def set_error(self, message: str) -> None:
        """AI 分析失败。"""
        self.status_label.configure(text="分析失败", text_color="#da3633")
        self.advice_label.configure(text=f"[错误] {message}", text_color="#da3633")

    # ------------------------------------------------------------------
    # 流式增量填充(主线程轮询逐行调用)
    # ------------------------------------------------------------------
    def apply_line(self, line: str) -> None:
        """处理一行协议;#ADVICE# 支持跨行 JSON 合并。"""
        if self._json_buf:
            self._json_buf += line
            if self._try_parse_buffered():
                return
            if len(self._json_buf) > 2000:
                logger.debug("#ADVICE# 跨行解析失败,丢弃: {}", self._json_buf[:120])
                self._json_buf = ""
            return

        what: str = parse_what_line(line)
        if what:
            self.what_label.configure(text=what)
            self._full_text.append(f"这是什么：{what}")
            return
        consequence: str = parse_consequence_line(line)
        if consequence:
            self.consequence_label.configure(text=consequence)
            self._full_text.append(f"允许的后果：{consequence}")
            return
        if line.startswith("#ADVICE#"):
            advice: dict = parse_advice_line(line)
            if advice:
                self._apply_advice(advice)
                return
            self._json_buf = line
            self._try_parse_buffered()
            return
        err: str = parse_error_line(line)
        if err:
            self.set_error(err)

    def _try_parse_buffered(self) -> bool:
        """尝试把跨行缓冲解析为 #ADVICE#;成功返回 True。"""
        advice: dict = parse_advice_line(self._json_buf)
        if advice:
            self._json_buf = ""
            self._apply_advice(advice)
            return True
        return False

    def _apply_advice(self, advice: dict) -> None:
        """渲染建议行(按档位着色)。"""
        decision: str = str(advice.get("decision", ""))
        reason: str = str(advice.get("reason", ""))
        text, color = _ADVICE_STYLES.get(decision, ("建议", _FG))
        if reason:
            text += f"：{reason}"
        self.advice_label.configure(text=text, text_color=color)
        self._full_text.append(f"建议：{text}")
        self.set_done()

    # ------------------------------------------------------------------
    def _copy_analysis(self) -> None:
        """复制完整分析到剪贴板。"""
        if not self._full_text:
            return
        try:
            import pyperclip

            pyperclip.copy("\n".join(self._full_text))
        except Exception as exc:
            logger.debug("复制分析失败: {}", exc)

    # ------------------------------------------------------------------
    # 单例访问
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls, master: Any) -> Optional["PermissionAdviceAlert"]:
        """返回已存在的单例;不存在或已销毁时返回 None。"""
        inst = cls._instance
        if inst is not None:
            try:
                if inst.winfo_exists():
                    return inst
            except Exception:
                pass
        return None

    @classmethod
    def ensure_instance(cls, master: Any) -> "PermissionAdviceAlert":
        """返回单例,不存在则创建(供 PermissionFlow 使用)。"""
        inst = cls.get_instance(master)
        if inst is None:
            inst = cls(master)
        return inst
