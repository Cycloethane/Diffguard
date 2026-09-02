# -*- coding: utf-8 -*-
"""审查流程控制器:diff 载入、渲染、风险仪表、AI 审查流式、保存/导出/恢复。

审查模块的控件(文件列表/Diff 区/报告区/仪表盘)随模块切换销毁重建,
ReviewFlow 通过 attach()/detach() 在模块构建时重新绑定控件引用;
控件未就绪时业务入口自动先切回审查模块(保持旧交互)。
"""

import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import customtkinter as ctk
from loguru import logger
from pygments import token
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer_for_filename

from core.diff_parser import (
    build_file_diff,
    build_title,
    compute_risk_level,
    file_risk_level,
    parse_diff,
    parse_diff_with_status,
    render_file_summary,
)
from core.reviewer import analyze_diff
from core.risk_score import compute_risk_score, score_color, score_to_level
from models.config import is_configured
from models.history import save_review
from ui.animation import breathing_text, blinking_cursor
from ui.poller import QueuePoller
from ui.widgets import bind_tooltip, html_escape

_FG: str = "#3A4A5A"
_FG_MUTED: str = "#8A96A8"

_RISK_MARK: dict[str, str] = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}

_RISK_BUTTON_COLORS_DARK: dict[str, tuple[str, str]] = {
    "high": ("#7f1d1d", "#991b1b"),
    "medium": ("#854d0e", "#a16207"),
    "low": ("#14532d", "#166534"),
}
_RISK_BUTTON_COLORS_LIGHT: dict[str, tuple[str, str]] = {
    "high": ("#fca5a5", "#f87171"),
    "medium": ("#fcd34d", "#fbbf24"),
    "low": ("#86efac", "#4ade80"),
}

_TOKEN_COLORS_DARK: dict[str, str] = {
    "tok.keyword": "#ff7b72",
    "tok.string": "#a5d6ff",
    "tok.comment": "#8b949e",
    "tok.number": "#79c0ff",
    "tok.func": "#d2a8ff",
    "tok.name": "#d2a8ff",
    "tok.operator": "#ff7b72",
    "tok.punct": "#c9d1d9",
    "tok.generic": "#7ee787",
    "tok.default": _FG,
}
_TOKEN_COLORS_LIGHT: dict[str, str] = {
    "tok.keyword": "#d73a49",
    "tok.string": "#032f62",
    "tok.comment": "#6a737d",
    "tok.number": "#005cc5",
    "tok.func": "#6f42c1",
    "tok.name": "#6f42c1",
    "tok.operator": "#d73a49",
    "tok.punct": "#24292e",
    "tok.generic": "#22863a",
    "tok.default": "#24292e",
}


class ReviewFlow:
    """审查业务流。app 提供 config/status/模块切换/设置入口等宿主能力。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        # 当前文档状态
        self.current_diff: str = ""
        self.current_files: list[dict[str, Any]] = []
        self.current_report: str = ""
        self._analyzing: bool = False
        self._stop_breathing: Optional[Callable[[], None]] = None
        self._stop_cursor: Optional[Callable[[], None]] = None
        self._file_buttons: list[ctk.CTkButton] = []
        # 审查模块控件(随模块切换重建)
        self._diff_textbox: Optional[ctk.CTkTextbox] = None
        self._report_textbox: Optional[ctk.CTkTextbox] = None
        self._file_list_frame: Optional[ctk.CTkScrollableFrame] = None
        self._dash_score: Optional[ctk.CTkLabel] = None
        self._dash_level: Optional[ctk.CTkLabel] = None
        self._dash_count: Optional[ctk.CTkLabel] = None
        self._dash_points: Optional[ctk.CTkLabel] = None
        self._guide: Optional[ctk.CTkFrame] = None
        # 流式审查队列与轮询
        self._stream_queue: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
        self._stream_poller = QueuePoller(
            app, self._stream_queue, self._handle_stream_item,
            interval_ms=50, label="review-stream",
        )

    # ------------------------------------------------------------------
    # 控件绑定(由 ReviewModule 构建时调用)
    # ------------------------------------------------------------------
    def attach(
        self,
        diff_textbox: ctk.CTkTextbox,
        report_textbox: ctk.CTkTextbox,
        file_list_frame: ctk.CTkScrollableFrame,
        dash_score: ctk.CTkLabel,
        dash_level: ctk.CTkLabel,
        dash_count: ctk.CTkLabel,
        dash_points: ctk.CTkLabel,
        guide: Optional[ctk.CTkFrame] = None,
    ) -> None:
        """绑定审查模块控件并恢复当前文档展示。"""
        self._diff_textbox = diff_textbox
        self._report_textbox = report_textbox
        self._file_list_frame = file_list_frame
        self._dash_score = dash_score
        self._dash_level = dash_level
        self._dash_count = dash_count
        self._dash_points = dash_points
        self._guide = guide
        self.define_text_tags()
        # 模块重建后恢复已有内容(如从历史恢复后切走再切回)
        if self.current_diff:
            self._populate_file_list(self.current_files)
            self._render_raw_diff(self.current_diff)
            if self.current_report:
                self._clear_report()
                self._insert_report(self.current_report)
            self._update_risk_gauge()

    def detach(self) -> None:
        """模块切走时解除控件引用(控件即将销毁)。"""
        self._diff_textbox = None
        self._report_textbox = None
        self._file_list_frame = None
        self._dash_score = None
        self._dash_level = None
        self._dash_count = None
        self._dash_points = None
        self._guide = None

    @property
    def controls_ready(self) -> bool:
        """审查模块控件是否有效存在(未被销毁)。"""
        for w in (self._diff_textbox, self._report_textbox, self._file_list_frame):
            if w is None:
                return False
            try:
                if not w.winfo_exists():
                    return False
            except Exception:
                return False
        return True

    def _ensure_controls(self) -> None:
        """控件未就绪时先切回审查模块。"""
        if not self.controls_ready:
            self.app.select_module("review")
            self.app.update_idletasks()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def file_count(self) -> int:
        return len(self.current_files)

    def risk_snapshot(self) -> tuple[int, list[str]]:
        """当前文档的本地风险评分(供前台小窗等)。"""
        return compute_risk_score(self.current_files)

    # ------------------------------------------------------------------
    # 文本标签(依赖当前主题,主题切换后重定义)
    # ------------------------------------------------------------------
    def define_text_tags(self) -> None:
        """为 diff 与报告文本框定义颜色/字体标签。"""
        if self._diff_textbox is None or self._report_textbox is None:
            return
        dark: bool = ctk.get_appearance_mode() == "Dark"
        token_colors: dict[str, str] = _TOKEN_COLORS_DARK if dark else _TOKEN_COLORS_LIGHT

        for tag, opts in {
            "pfx_add": {"foreground": "#3fb950"},
            "pfx_del": {"foreground": "#f85149"},
            "bg_add": {"background": "#0f2b1a" if dark else "#e6ffec"},
            "bg_del": {"background": "#331414" if dark else "#ffebe9"},
            "hunk": {"foreground": "#8b949e"},
        }.items():
            self._diff_textbox.tag_config(tag, **opts)

        for tag, color in token_colors.items():
            self._diff_textbox.tag_config(tag, foreground=color)

        self._report_textbox.tag_config("report_error", foreground="#f85149")

    def refresh_theme(self) -> None:
        """主题切换后刷新标签与文件列表配色。"""
        self.define_text_tags()
        if self.controls_ready:
            self._populate_file_list(self.current_files)

    def apply_accent(self, primary: str, hover: str) -> None:
        """强调色切换后刷新引导卡按钮配色(递归查找嵌套按钮)。"""
        if self._guide is None:
            return

        def _walk(widget: Any) -> None:
            try:
                for child in widget.winfo_children():
                    if isinstance(child, ctk.CTkButton):
                        child.configure(fg_color=primary, hover_color=hover)
                    _walk(child)
            except Exception:
                pass

        try:
            _walk(self._guide)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # diff 载入
    # ------------------------------------------------------------------
    def paste_from_clipboard(self) -> None:
        """从剪贴板读取内容并尝试加载。"""
        self._ensure_controls()
        try:
            import pyperclip

            text: str = pyperclip.paste()
        except Exception as exc:
            logger.error("读取剪贴板失败: {}", exc)
            self.app.set_status("读取剪贴板失败")
            return
        if text and "diff --git" in text:
            self.apply_diff(text)
            self.app.set_status("已从剪贴板加载 diff")
        else:
            self.app.set_status("剪贴板中没有检测到 git diff")

    def apply_diff(self, diff_text: str, silent: bool = False) -> None:
        """解析并展示一段 diff：重置文件列表、Diff 区与报告区。"""
        self.current_diff = diff_text.strip()
        files, status = parse_diff_with_status(self.current_diff)
        self.current_files = files
        self.current_report = ""
        if self._guide is not None:
            try:
                self._guide.grid_remove()
            except Exception:
                pass
        if not self.controls_ready:
            return
        self._populate_file_list(files)
        self._render_raw_diff(self.current_diff)
        self._clear_report()
        self._update_risk_gauge()
        if silent:
            return
        if not files:
            self.app.set_status("未识别到文件变更（请确认是否为 git diff）")
        else:
            base: str = f"已加载 diff：{len(files)} 个文件"
            if status.get("lenient"):
                base += "（内容不完整/被截断，仅粗略解析）"
            elif status.get("strict") is False:
                base += "（部分内容无法严格解析）"
            self.app.set_status(base)

    def restore_review(self, record: Any) -> None:
        """从历史记录恢复某次审查到主界面。"""
        try:
            self._ensure_controls()
            self.current_diff = record.raw_diff
            self.current_files = parse_diff(record.raw_diff)
            self.current_report = record.ai_report or ""
            if self._guide is not None:
                try:
                    self._guide.grid_remove()
                except Exception:
                    pass
            self._populate_file_list(self.current_files)
            self._render_raw_diff(record.raw_diff)
            self._clear_report()
            self._insert_report(record.ai_report or "")
            self._update_risk_gauge()
            self.app.set_status(f"已恢复历史 id={record.id}")
        except Exception as exc:
            logger.error("恢复历史记录失败: {}", exc)
            self.app.set_status("恢复历史记录失败")

    # ------------------------------------------------------------------
    # 仪表盘 / 文件列表
    # ------------------------------------------------------------------
    def _update_risk_gauge(self) -> None:
        """根据当前文件列表刷新顶部仪表盘卡。"""
        score, contributions = compute_risk_score(self.current_files)
        try:
            if self._dash_score is not None:
                self._dash_score.configure(text=str(score), text_color=score_color(score))
            if self._dash_level is not None:
                self._dash_level.configure(
                    text=_RISK_MARK.get(score_to_level(score), score_to_level(score)),
                    text_color=score_color(score),
                )
            if self._dash_count is not None:
                self._dash_count.configure(text=str(len(self.current_files)))
            if self._dash_points is not None:
                top: list[str] = contributions[:3] if contributions else ["无突出风险点"]
                self._dash_points.configure(text="\n".join(top))
        except Exception:
            pass

    def _populate_file_list(self, files: list[dict[str, Any]]) -> None:
        """根据文件风险等级渲染文件列表（红/黄/绿 + 高危标记）。"""
        if self._file_list_frame is None:
            return
        for widget in self._file_list_frame.winfo_children():
            widget.destroy()
        self._file_buttons = []

        if not files:
            ctk.CTkLabel(self._file_list_frame, text="（无文件变更）", text_color=_FG_MUTED).pack(
                fill="x", padx=8, pady=6
            )
            return

        colors: dict[str, tuple[str, str]] = (
            _RISK_BUTTON_COLORS_DARK
            if ctk.get_appearance_mode() == "Dark"
            else _RISK_BUTTON_COLORS_LIGHT
        )
        for info in files:
            level: str = file_risk_level(info)
            base, hover = colors.get(level, ("#333333", "#444444"))
            flags: list[str] = info.get("risk_flags", []) or []
            mark: str = ""
            tooltip_parts: list[str] = []
            if level == "high":
                mark = "⚠ "
                tooltip_parts.append("高风险")
            elif flags:
                tooltip_parts.append("含风险标记")

            text: str = f"{mark}{render_file_summary(info)}"
            btn: ctk.CTkButton = ctk.CTkButton(
                self._file_list_frame,
                text=text,
                anchor="w",
                height=36,
                fg_color=base,
                hover_color=hover,
                text_color=_FG,
                font=ctk.CTkFont(size=12),
                command=lambda info=info: self._on_file_selected(info),
            )
            btn.pack(fill="x", padx=4, pady=3)
            self._file_buttons.append(btn)

            if tooltip_parts:
                reason: str = "；".join(flags) if flags else "文件级风险"
                tip: str = f"{info.get('file_path','')}\n" + reason
                bind_tooltip(btn, tip)

    def _on_file_selected(self, file_info: dict[str, Any]) -> None:
        """点击文件列表项：在 Diff 区展示该文件的高亮内容。"""
        diff_text: str = build_file_diff(file_info)
        self._render_raw_diff(diff_text)
        self.app.set_status(
            "正在查看: {} (+{} -{})".format(
                file_info["file_path"], file_info["additions"], file_info["deletions"]
            )
        )

    # ------------------------------------------------------------------
    # diff 渲染(Pygments 高亮)
    # ------------------------------------------------------------------
    @staticmethod
    def _guess_lexer(file_path: str) -> Any:
        """根据文件名猜测 Pygments 词法分析器，失败时回退到纯文本。"""
        try:
            return guess_lexer_for_filename(file_path, "")
        except Exception:
            try:
                return get_lexer_by_name("diff")
            except Exception:
                return TextLexer()

    def _render_raw_diff(self, diff_text: str) -> None:
        """渲染 diff 文本：以 Pygments 分词着色，并标记 + / - 前缀。"""
        if self._diff_textbox is None:
            return
        self._diff_textbox.delete("1.0", "end")
        if not diff_text:
            return
        lexer: Any = self._guess_lexer("_.diff")
        try:
            tokens = list(lexer.get_tokens(diff_text + "\n"))
        except Exception as exc:
            logger.warning("Pygments 高亮失败: {}", exc)
            tokens = [(token.Text, diff_text + "\n")]

        line_index: int = 0
        col: int = 0
        lines: list[list[tuple[str, Optional[str], int]]] = [[]]

        for ttype, value in tokens:
            tag: Optional[str] = self._classify_token(ttype)
            parts: list[str] = value.split("\n")
            for i, piece in enumerate(parts):
                if i > 0:
                    line_index += 1
                    lines.append([])
                    col = 0
                if piece:
                    lines[line_index].append((piece, tag, col))
                    col += len(piece)

        for i, segs in enumerate(lines):
            self._insert_highlighted_line(i + 1, segs)

    @staticmethod
    def _classify_token(ttype: Any) -> Optional[str]:
        """将 Pygments token 映射到预定义标签。"""
        if ttype in token.Keyword:
            return "tok.keyword"
        if ttype in token.String:
            return "tok.string"
        if ttype in token.Comment:
            return "tok.comment"
        if ttype in token.Number:
            return "tok.number"
        if ttype in token.Name.Function:
            return "tok.func"
        if ttype in token.Name:
            return "tok.name"
        if ttype in token.Operator:
            return "tok.operator"
        if ttype in token.Punctuation:
            return "tok.punct"
        if ttype in token.Generic:
            return "tok.generic"
        return None

    def _insert_highlighted_line(
        self, line_no: int, segs: list[tuple[str, Optional[str], int]]
    ) -> None:
        """插入单行到 diff 文本框，并应用 token 颜色与 +/- 行标记。"""
        tb = self._diff_textbox
        line_text: str = "".join(chunk for chunk, _, _ in segs)
        line_type: str = line_text[0] if line_text else ""

        if line_type in ("+", "-"):
            bg_tag: str = "bg_add" if line_type == "+" else "bg_del"
            tb.tag_add(bg_tag, f"{line_no}.0", f"{line_no}.end")

        for chunk, tag, start_col in segs:
            tb.insert("end", chunk)
            end_col = start_col + len(chunk)
            if tag and chunk[0] != line_type:
                tb.tag_add(tag, f"{line_no}.{start_col}", f"{line_no}.{end_col}")

        if line_type in ("+", "-"):
            tb.tag_add(
                "pfx_add" if line_type == "+" else "pfx_del",
                f"{line_no}.0",
                f"{line_no}.1",
            )
        elif line_text.startswith("@@"):
            tb.tag_add("hunk", f"{line_no}.0", f"{line_no}.end")

        tb.insert("end", "\n")

    # ------------------------------------------------------------------
    # AI 审查(流式)
    # ------------------------------------------------------------------
    def start_review(self) -> None:
        """开始 AI 审查：后台线程调用模型，主线程轮询队列流式展示。"""
        self._ensure_controls()
        if self._analyzing:
            return
        raw_text: str = self.current_diff or (
            self._diff_textbox.get("1.0", "end") if self._diff_textbox is not None else ""
        )
        if not raw_text.strip():
            self.app.set_status("请先粘贴 diff")
            return
        if not is_configured(self.app.config):
            self.app.set_status("尚未配置 API Key，请先设置")
            self.app.open_settings()
            return

        # 未解析过文件时先解析一次
        if not self.current_files:
            self.current_files = parse_diff(raw_text)
            self._populate_file_list(self.current_files)

        self._analyzing = True
        self.app.set_review_buttons(state="disabled")
        self.app.set_status("分析中")
        self._stop_breathing = breathing_text(self.app.status_label, "分析中")
        self._stop_cursor = blinking_cursor(self._report_textbox)
        self._clear_report()
        self._stream_queue = queue.Queue()

        worker: threading.Thread = threading.Thread(
            target=self._review_worker, daemon=True
        )
        worker.start()
        self._stream_poller = QueuePoller(
            self.app, self._stream_queue, self._handle_stream_item,
            interval_ms=50, label="review-stream",
        )
        self._stream_poller.start()

    def _review_worker(self) -> None:
        """后台线程：消费 analyze_diff 生成器，将片段送入流式队列。"""
        try:
            for chunk in analyze_diff(self.current_diff, self.app.config):
                self._stream_queue.put(("chunk", chunk))
        except Exception as exc:  # 兜底：不让线程崩溃
            logger.exception("审查线程发生异常: {}", exc)
            self._stream_queue.put(("error", str(exc)))
        finally:
            self._stream_queue.put(("done", None))

    def _handle_stream_item(self, item: tuple[str, Optional[str]]) -> None:
        """处理一条流式事件;收到 done 时收尾并停止轮询。"""
        kind, payload = item
        if kind == "chunk":
            self._insert_report(payload or "")
        elif kind == "error":
            self._insert_report(f"\n\n[错误] {payload}\n")
        elif kind == "done":
            self._on_review_done()
            self._stream_poller.stop()
            return
        try:
            if self._report_textbox is not None:
                self._report_textbox.see("end")
        except Exception:
            pass

    def _on_review_done(self) -> None:
        """审查完成：恢复按钮并缓存报告。"""
        self._analyzing = False
        if self._stop_breathing is not None:
            self._stop_breathing()
            self._stop_breathing = None
        if self._stop_cursor is not None:
            self._stop_cursor()
            self._stop_cursor = None
        report_text: str = (
            self._report_textbox.get("1.0", "end").strip()
            if self._report_textbox is not None
            else ""
        )
        self.current_report = report_text
        self.app.set_review_buttons(state="normal")
        if report_text:
            self.app.set_status("审查完成，可保存到历史")
        else:
            self.app.set_status("审查完成，但未获得有效内容")

    # ------------------------------------------------------------------
    # 报告文本框辅助
    # ------------------------------------------------------------------
    def _clear_report(self) -> None:
        """清空报告文本框。"""
        if self._report_textbox is None:
            return
        self._report_textbox.configure(state="normal")
        self._report_textbox.delete("1.0", "end")
        self._report_textbox.configure(state="disabled")

    def _insert_report(self, chunk: str) -> None:
        """向只读的报告文本框追加文本。"""
        if self._report_textbox is None:
            return
        self._report_textbox.configure(state="normal")
        self._report_textbox.insert("end", chunk)
        self._report_textbox.configure(state="disabled")

    # ------------------------------------------------------------------
    # 保存 / 导出
    # ------------------------------------------------------------------
    def save_history(self) -> None:
        """保存当前审查结果到历史数据库。"""
        if self._analyzing:
            self.app.set_status("审查尚未完成")
            return
        if not self.current_report:
            self.app.set_status("还没有可保存的审查报告")
            return
        record_id: Optional[int] = save_review(
            title=build_title(self.current_files),
            file_count=len(self.current_files),
            risk_level=compute_risk_level(self.current_files),
            ai_report=self.current_report,
            raw_diff=self.current_diff,
        )
        if record_id is not None:
            self.app.set_status(f"已保存到历史 (id={record_id})")
        else:
            self.app.set_status("保存失败，请查看日志")

    def export_report(self) -> None:
        """将当前 AI 审查报告导出为 Markdown / HTML / 文本。"""
        if not self.current_report:
            self.app.set_status("当前没有可导出的报告")
            return
        from tkinter import filedialog

        path: str = filedialog.asksaveasfilename(
            parent=self.app,
            title="导出审查报告",
            defaultextension=".md",
            filetypes=(
                ("Markdown", "*.md"),
                ("HTML", "*.html"),
                ("文本", "*.txt"),
            ),
            initialfile=f"diffguard-report-{datetime.now():%Y%m%d-%H%M}.md",
        )
        if not path:
            return
        try:
            body: str = str(self.current_report)
            ext: str = Path(path).suffix.lower()
            content: str
            if ext == ".html":
                content = (
                    "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
                    "<title>DiffGuard 审查报告</title></head><body>"
                    "<pre>" + html_escape(body) + "</pre></body></html>"
                )
            else:
                content = (
                    f"# DiffGuard 审查报告\n\n"
                    f"- 时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                    f"- 文件数: {len(self.current_files)}\n\n---\n\n{body}\n"
                )
            Path(path).write_text(content, encoding="utf-8")
            self.app.set_status(f"报告已导出: {path}")
        except Exception as exc:
            logger.error("导出报告失败: {}", exc)
            self.app.set_status("导出报告失败，请查看日志")
