# -*- coding: utf-8 -*-
"""决策助手置顶浮窗：展示 Agent 的决策问题、AI 对各选项的通俗解析与推荐。

设计要点：
    - 单例：整个进程只有一个浮窗，重复决策只更新内容并重新置顶。
    - 置顶：attributes("-topmost") 保证浮窗浮在其它应用之上。
    - 流式：解析结果逐行到达，本窗口增量填充（#OPTION# / #RECOMMEND# / #ERROR#）。
    - 两种模式：
        on：检测到即自动弹出并开始解析。
        ask：先弹确认框，用户点"解析"才调用 AI。
    - 选项点击：用户点击某个选项后高亮该选项，并可通过回调记录最终选择。
"""

from typing import Any, Callable, List, Optional

import customtkinter as ctk
from loguru import logger

from core.decision_explainer import (
    parse_error_line,
    parse_opt_line,
    parse_question_line,
    parse_recommend_line,
)
from models.decision_prompt import DecisionPrompt
from ui.animation import animate, fade_in_window, fade_out_window
from ui.theme import surface, surface_muted, text_color, text_muted

# 颜色（浅色主题，配合吉祥物配色；高风险保持红色）
_FG: str = text_color(light=True)
_FG_MUTED: str = text_muted(light=True)
_BG: str = surface(light=True)
_SURFACE: str = surface_muted(light=True)
_RISK_COLORS: dict[str, str] = {
    "low": "#238636",
    "medium": "#d29922",
    "high": "#da3633",
}
_RISK_LABELS: dict[str, str] = {
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
}

# 浮窗整体不透明度（让桌面背景透出）
_POPUP_ALPHA: float = 1.0

# 单行选项卡片高度（展开后）
_CARD_H: int = 78


class DecisionAlert(ctk.CTkToplevel):
    """决策解析单例浮窗。

    属性:
        _instance: 类级单例引用。
        on_decide: 用户点击某选项后的回调，签名 callback(prompt, key: str)。
    """

    _instance: Optional["DecisionAlert"] = None

    def __init__(
        self,
        master: Any,
        on_decide: Callable[[DecisionPrompt, str], None],
    ) -> None:
        super().__init__(master)
        DecisionAlert._instance = self
        self._on_decide: Callable[[DecisionPrompt, str], None] = on_decide
        self._prompt: Optional[DecisionPrompt] = None
        self._option_frames: dict[str, ctk.CTkFrame] = {}
        self._option_meta_labels: dict[str, ctk.CTkLabel] = {}
        self._option_selected: dict[str, bool] = {}
        self._json_buf: str = ""  # 跨行 JSON 合并缓冲
        self._pending_high_key: Optional[str] = None  # 等待"三思"确认的高危选项
        self.confirm_layer: Optional[ctk.CTkFrame] = None
        self.title("DiffGuard - 决策助手")
        self.geometry("640x560")
        self.minsize(520, 400)
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
        card.grid_rowconfigure(3, weight=1)
        card.grid_columnconfigure(0, weight=1)

        header: ctk.CTkFrame = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text="🤔 Agent 需要你决策", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        self.status_label: ctk.CTkLabel = ctk.CTkLabel(
            header, text="待解析", text_color=_FG_MUTED
        )
        self.status_label.grid(row=0, column=1, sticky="e")

        self.source_label: ctk.CTkLabel = ctk.CTkLabel(
            card, text="", anchor="w", text_color=_FG_MUTED, justify="left"
        )
        self.source_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 4))

        self.question_label: ctk.CTkLabel = ctk.CTkLabel(
            card,
            text="",
            anchor="w",
            justify="left",
            wraplength=580,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.question_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))

        # 选项区（可滚动）
        self.opt_scroll: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(
            card, fg_color="transparent"
        )
        self.opt_scroll.grid(row=3, column=0, sticky="nsew", padx=8, pady=2)
        self.opt_scroll.grid_columnconfigure(0, weight=1)
        self._opt_inner_row: int = 0

        # 推荐区
        rec: ctk.CTkFrame = ctk.CTkFrame(card, fg_color="transparent")
        rec.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 2))
        rec.grid_columnconfigure(0, weight=1)
        self.recommend_label: ctk.CTkLabel = ctk.CTkLabel(
            rec,
            text="",
            anchor="w",
            justify="left",
            wraplength=580,
            text_color=_FG,
            font=ctk.CTkFont(size=13),
        )
        self.recommend_label.grid(row=0, column=0, sticky="ew")

        # 底部按钮
        btns: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        btns.grid_columnconfigure(1, weight=1)
        self.copy_btn: ctk.CTkButton = ctk.CTkButton(
            btns, text="复制结论", width=100, height=34, command=self._copy_conclusion
        )
        self.copy_btn.grid(row=0, column=0, padx=(0, 6))
        self.close_btn: ctk.CTkButton = ctk.CTkButton(
            btns, text="关闭", width=80, height=34, fg_color=_SURFACE, hover_color="#e0e6ee",
            text_color=_FG, command=self.withdraw,
        )
        self.close_btn.grid(row=0, column=2, padx=(6, 0))

        # 高危选项"三思"确认层（覆盖在浮窗内容之上）
        self.confirm_layer = ctk.CTkFrame(
            self, fg_color="#2b1212", corner_radius=10
        )
        self.confirm_layer.grid(row=0, column=0, sticky="nsew", padx=24, pady=24)
        self.confirm_layer.grid_rowconfigure(3, weight=1)
        self.confirm_layer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.confirm_layer,
            text="⚠ 且慢（Wait）：请三思",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#ff6b6b",
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))

        self.confirm_question: ctk.CTkLabel = ctk.CTkLabel(
            self.confirm_layer,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
            justify="left",
            wraplength=520,
        )
        self.confirm_question.grid(row=1, column=0, sticky="ew", padx=20, pady=(2, 4))

        self.confirm_risk: ctk.CTkLabel = ctk.CTkLabel(
            self.confirm_layer,
            text="",
            anchor="w",
            justify="left",
            wraplength=520,
            text_color="#ffb4b4",
            font=ctk.CTkFont(size=13),
        )
        self.confirm_risk.grid(row=2, column=0, sticky="ew", padx=20, pady=(2, 10))

        confirm_btns: ctk.CTkFrame = ctk.CTkFrame(self.confirm_layer, fg_color="transparent")
        confirm_btns.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 16))
        confirm_btns.grid_columnconfigure(0, weight=1)
        self.confirm_proceed: ctk.CTkButton = ctk.CTkButton(
            confirm_btns,
            text="我仍要选择",
            fg_color="#da3633",
            hover_color="#ff5f56",
            height=38,
            command=self._confirm_proceed,
        )
        self.confirm_proceed.grid(row=0, column=1, padx=(0, 6))
        self.confirm_cancel: ctk.CTkButton = ctk.CTkButton(
            confirm_btns,
            text="再看看",
            fg_color=_SURFACE,
            hover_color="#e0e6ee",
            text_color=_FG,
            height=38,
            command=self._confirm_cancel,
        )
        self.confirm_cancel.grid(row=0, column=2, padx=(6, 0))
        self.confirm_layer.grid_remove()  # 默认隐藏

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def show_prompt(
        self, prompt: DecisionPrompt, auto_explain: bool = False
    ) -> None:
        """展示一个决策请求；auto_explain=True 时由调用方立即启动 AI 解析。"""
        self._prompt = prompt
        self._option_frames.clear()
        self._option_meta_labels.clear()
        self._option_selected.clear()
        # 清空选项区
        for w in self.opt_scroll.winfo_children():
            w.destroy()
        self._opt_inner_row = 0

        self.source_label.configure(text=f"来源：{prompt.source}")
        self.question_label.configure(text=prompt.question or "Agent 请求你做出一个选择")
        self.status_label.configure(text="等待解析" if auto_explain else "待用户确认", text_color=_FG_MUTED)
        self.recommend_label.configure(text="")
        self._pending_high_key = None
        self._hide_confirm_layer()
        self._render_options(prompt.options)

        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        fade_in_window(self, final_alpha=_POPUP_ALPHA)

    def set_explaining(self, explaining: bool) -> None:
        """切换"解析中"状态。"""
        self.status_label.configure(
            text="解析中…" if explaining else "解析完成",
            text_color="#d29922" if explaining else "#238636",
        )

    def set_error(self, message: str) -> None:
        """显示解析错误。"""
        self.status_label.configure(text="解析失败", text_color="#da3633")
        self.recommend_label.configure(
            text=f"[错误] {message}", text_color="#da3633"
        )

    # ------------------------------------------------------------------
    # 流式增量填充（由 app.py 主线程轮询逐行调用）
    # ------------------------------------------------------------------
    def apply_line(self, line: str) -> None:
        """处理一行结构化输出；支持 #OPTION# / #RECOMMEND# 跨行 JSON 合并。"""
        # 合并累积：若当前在 JSON 缓冲中，先尝试拼接
        if self._json_buf:
            self._json_buf += line
            if self._try_parse_buffered():
                return
            # 缓冲仍未闭合，等待更多行
            return
        q: str = parse_question_line(line)
        if q:
            self.question_label.configure(text=q)
            return
        if line.startswith("#OPTION#") or line.startswith("#RECOMMEND#"):
            # 直接尝试解析（单行 JSON）
            opt: dict[str, Any] = parse_opt_line(line)
            if opt:
                self._update_option(opt)
                return
            rec: dict[str, Any] = parse_recommend_line(line)
            if rec:
                self._apply_recommend(rec)
                return
            # 单行解析失败 → 开启跨行缓冲
            self._json_buf = line
            if self._try_parse_buffered():
                pass
            return
        err: str = parse_error_line(line)
        if err:
            self.set_error(err)

    def _try_parse_buffered(self) -> bool:
        """尝试把跨行缓冲解析为 #OPTION# 或 #RECOMMEND#；成功返回 True。"""
        opt: dict[str, Any] = parse_opt_line(self._json_buf)
        if opt:
            self._json_buf = ""
            self._update_option(opt)
            return True
        rec: dict[str, Any] = parse_recommend_line(self._json_buf)
        if rec:
            self._json_buf = ""
            self._apply_recommend(rec)
            return True
        # 缓冲超长仍无闭合 → 放弃（防内存增长）
        if len(self._json_buf) > 2000:
            logger.debug("跨行 JSON 解析失败，丢弃: {}", self._json_buf[:120])
            self._json_buf = ""
        return False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _render_options(self, options: Any) -> None:
        cards: list[ctk.CTkFrame] = []
        for opt in options:
            key: str = opt.key or ""
            text: str = opt.text or ""
            frame: ctk.CTkFrame = ctk.CTkFrame(self.opt_scroll, corner_radius=6)
            frame.grid(
                row=self._opt_inner_row,
                column=0,
                sticky="ew",
                padx=2,
                pady=(2, 2),
            )
            frame.grid_columnconfigure(1, weight=1)
            self._opt_inner_row += 1

            key_label: ctk.CTkLabel = ctk.CTkLabel(
                frame,
                text=key,
                width=34,
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            key_label.grid(row=0, column=0, rowspan=2, padx=(8, 4), pady=6, sticky="n")

            text_label: ctk.CTkLabel = ctk.CTkLabel(
                frame,
                text=text,
                anchor="w",
                justify="left",
                wraplength=500,
                font=ctk.CTkFont(size=13),
            )
            text_label.grid(row=0, column=1, sticky="ew", padx=4, pady=(6, 0))

            meta_label: ctk.CTkLabel = ctk.CTkLabel(
                frame,
                text="",
                anchor="w",
                justify="left",
                wraplength=500,
                text_color=_FG_MUTED,
                font=ctk.CTkFont(size=11),
            )
            meta_label.grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 6))

            self._option_frames[key] = frame
            self._option_meta_labels[key] = meta_label

            frame.bind("<Button-1>", lambda e, k=key: self._select_option(k))
            key_label.bind("<Button-1>", lambda e, k=key: self._select_option(k))
            text_label.bind("<Button-1>", lambda e, k=key: self._select_option(k))
            meta_label.bind("<Button-1>", lambda e, k=key: self._select_option(k))

            cards.append(frame)

        # 选项卡片依次淡入（stagger）
        for idx, frame in enumerate(cards):
            delay: int = idx * 70
            if delay:
                frame.after(delay, lambda f=frame: self._card_appear(f))
            else:
                self._card_appear(frame)

    def _card_appear(self, frame: ctk.CTkFrame) -> None:
        """单张选项卡片淡入。"""
        def _step(t: float) -> None:
            try:
                frame.attributes("-alpha", t)
            except Exception:
                pass

        animate(frame, _step, duration_ms=180)

    def _update_option(self, data: dict[str, Any]) -> None:
        key: str = data.get("key", "")
        if key not in self._option_meta_labels:
            # 尝试用文本匹配
            key = self._match_key_by_text(data.get("text", "")) or key
            if key not in self._option_meta_labels:
                return
        meta: str = data.get("meaning", "") or ""
        risk: str = data.get("risk", "") or ""
        reason: str = data.get("reason", "") or ""
        parts: list[str] = []
        if meta:
            parts.append(meta)
        if risk:
            color: str = _RISK_COLORS.get(risk, _FG_MUTED)
            label: str = _RISK_LABELS.get(risk, risk)
            parts.append(f"[{label}]")
            self._option_meta_labels[key].configure(text_color=color)
        if reason:
            parts.append(f"理由：{reason}")
        self._option_meta_labels[key].configure(text="\n".join(parts))

    def _apply_recommend(self, data: dict[str, Any]) -> None:
        conclusion: str = data.get("conclusion", "") or ""
        option: str = data.get("option", "") or ""
        if conclusion:
            prefix: str = f"✅ 推荐 {option}：" if option else "💡 "
            self.recommend_label.configure(text=prefix + conclusion, text_color="#238636")
        self.status_label.configure(text="解析完成", text_color="#238636")

    def _select_option(self, key: str) -> None:
        """用户点击某选项：高危选项先弹"三思"确认，其余直接回调。"""
        if self._prompt is None:
            return
        risk: str = self._option_risk(key)
        if risk == "high":
            self._show_confirm_layer(key)
            return
        self._commit_choice(key)

    def _option_risk(self, key: str) -> str:
        """返回选项的 AI 风险等级（low/medium/high），无则空串。"""
        label = self._option_meta_labels.get(key)
        if label is None:
            return ""
        meta: str = label.cget("text") or ""
        for name, lv in (("高风险", "high"), ("中风险", "medium"), ("低风险", "low")):
            if name in meta:
                return lv
        return ""

    def _commit_choice(self, key: str) -> None:
        """真正提交选择：高亮 + 回调。"""
        if self._prompt is None:
            return
        self._option_selected[key] = True
        for k, frame in self._option_frames.items():
            if k == key:
                frame.configure(fg_color="#2d4a2d")
            else:
                frame.configure(fg_color="transparent")
        logger.info("用户选择了决策选项: {}", key)
        self._on_decide(self._prompt, key)

    # ------------------------------------------------------------------
    # 高危选项"三思"确认层
    # ------------------------------------------------------------------
    def _show_confirm_layer(self, key: str) -> None:
        """显示高危选项的二次确认层。"""
        if self._prompt is None:
            return
        self._pending_high_key = key
        opt_text: str = ""
        risk_reason: str = ""
        for opt in self._prompt.options:
            if getattr(opt, "key", "") == key:
                opt_text = getattr(opt, "text", "")
                risk_reason = getattr(opt, "risk_reason", "") or ""
                break
        self.confirm_question.configure(text=f"你选择了：{key}）{opt_text}")
        reason: str = risk_reason or "该选项被 AI 判定为高风险，可能带来安全隐患或不可逆影响"
        self.confirm_risk.configure(text=f"风险：高风险\n代价：{reason}")
        self.confirm_layer.grid()
        self.confirm_layer.lift()

    def _hide_confirm_layer(self) -> None:
        """隐藏确认层。"""
        self._pending_high_key = None
        if self.confirm_layer is not None:
            self.confirm_layer.grid_remove()

    def _confirm_proceed(self) -> None:
        """用户确认仍要选择高危选项。"""
        key: Optional[str] = self._pending_high_key
        self._hide_confirm_layer()
        if key:
            self._commit_choice(key)

    def _confirm_cancel(self) -> None:
        """用户返回再看。"""
        self._hide_confirm_layer()

    def _match_key_by_text(self, text: str) -> Optional[str]:
        """按选项文本反查 key（处理模型返回 key 与原始不一致的情况）。"""
        if self._prompt is None:
            return None
        for opt in self._prompt.options:
            if text and text in (opt.text or ""):
                return opt.key
        return None

    def _copy_conclusion(self) -> None:
        """复制结论到剪贴板。"""
        text: str = self.recommend_label.cget("text")
        if not text:
            return
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception as exc:
            logger.debug("复制结论失败: {}", exc)

    # ------------------------------------------------------------------
    # 单例访问
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls, master: Any) -> Optional["DecisionAlert"]:
        """返回已存在的单例；不存在或已销毁时返回 None。"""
        inst = cls._instance
        if inst is not None:
            try:
                if inst.winfo_exists():
                    return inst
            except Exception:
                pass
        return None
