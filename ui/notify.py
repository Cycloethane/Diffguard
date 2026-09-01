# -*- coding: utf-8 -*-
"""系统托盘：常驻图标 + 右键菜单 + 气球通知（ctypes 直调 Shell_NotifyIconW）。

常驻托盘图标提供：
  - 左键/双击：恢复主界面
  - 右键菜单：显示 DiffGuard / 退出
  - 气球通知：高风险权限请求提醒

托盘宿主运行在独立后台线程，通过注册的消息窗口接收 shell 回调；事件经
on_show / on_quit 回调交给调用方，调用方需自行保证线程安全（如放入
queue.Queue 后由 Tk 主线程轮询）。
"""

import ctypes
import ctypes.wintypes as wt
import threading
import time
from typing import Any, Callable, Optional

from loguru import logger

# ---- 常量（Windows SDK shellapi.h / winuser.h）----
_NIM_ADD = 0x00000000
_NIM_MODIFY = 0x00000001
_NIM_DELETE = 0x00000002
_NIM_SETVERSION = 0x00000004
_NOTIFYICON_VERSION_4 = 4

_NIF_MESSAGE = 0x00000001
_NIF_ICON = 0x00000002
_NIF_TIP = 0x00000004
_NIF_INFO = 0x00000010

_NIIF_INFO = 0x00000001
_NIIF_WARNING = 0x00000002
_NIIF_ERROR = 0x00000003

_WM_USER = 0x0400
_TRAY_MSG = _WM_USER + 20
_WM_QUIT = 0x0012

# 鼠标消息（低 16 位）
_WM_LBUTTONUP = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205
_WM_CONTEXTMENU = 0x007B
_WM_ADD_ICON = 0x8000

# 弹出菜单
_TPM_RIGHTBUTTON = 0x0002
_TPM_RETURNCMD = 0x0100
_MF_STRING = 0x0000

_IMG_ICON = 1
_LR_LOADFROMFILE = 0x0010
_IDI_APPLICATION = 32512

_ID_SHOW = 1001
_ID_QUIT = 1002

try:
    _user32 = ctypes.windll.user32
    _shell32 = ctypes.windll.shell32

    class _WNDCLASSW(ctypes.Structure):
        """WNDCLASSW（ctypes.wintypes 未内置）。"""

        _fields_ = [
            ("style", wt.UINT),
            (
                "lpfnWndProc",
                ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM),
            ),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE),
            ("hIcon", wt.HANDLE),
            ("hCursor", wt.HANDLE),
            ("hbrBackground", wt.HANDLE),
            ("lpszMenuName", wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR),
        ]

    class _NOTIFYICONDATAW(ctypes.Structure):
        """Shell_NotifyIconW 所用的 NOTIFYICONDATAW（Win10 全尺寸版本）。"""

        _fields_ = [
            ("cbSize", wt.DWORD),
            ("hWnd", wt.HWND),
            ("uID", wt.UINT),
            ("uFlags", wt.UINT),
            ("uCallbackMessage", wt.UINT),
            ("hIcon", wt.HANDLE),
            ("szTip", ctypes.c_wchar * 128),
            ("dwState", wt.DWORD),
            ("dwStateMask", wt.DWORD),
            ("szInfo", ctypes.c_wchar * 256),
            ("uTimeout", wt.UINT),
            ("szInfoTitle", ctypes.c_wchar * 64),
            ("dwInfoFlags", wt.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wt.HANDLE),
        ]

    _NID_SIZE = ctypes.sizeof(_NOTIFYICONDATAW)

    # 设定原型，避免 64 位指针/句柄截断导致的访问冲突
    _user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    _user32.DefWindowProcW.restype = ctypes.c_long
    _user32.CreateWindowExW.argtypes = [
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
    ]
    _user32.CreateWindowExW.restype = wt.HWND
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
    _user32.RegisterClassW.restype = ctypes.c_ushort
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    _user32.GetMessageW.restype = wt.BOOL
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    _user32.TranslateMessage.restype = wt.BOOL
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    _user32.DispatchMessageW.restype = wt.LPARAM
    _user32.DestroyWindow.argtypes = [wt.HWND]
    _user32.DestroyWindow.restype = wt.BOOL
    _user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    _user32.PostMessageW.restype = wt.BOOL
    _user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_size_t]  # 资源 ID 为指针宽整数
    _user32.LoadIconW.restype = wt.HANDLE
    _user32.LoadImageW.argtypes = [
        wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT,
    ]
    _user32.LoadImageW.restype = wt.HANDLE
    _user32.CreatePopupMenu.argtypes = []
    _user32.CreatePopupMenu.restype = wt.HMENU
    _user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
    _user32.AppendMenuW.restype = wt.BOOL
    _user32.TrackPopupMenu.argtypes = [
        wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p,
    ]
    _user32.TrackPopupMenu.restype = wt.BOOL
    _user32.DestroyMenu.argtypes = [wt.HMENU]
    _user32.DestroyMenu.restype = wt.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    _user32.GetCursorPos.restype = wt.BOOL
    _shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, wt.LPVOID, wt.UINT]
    _shell32.Shell_NotifyIconW.restype = wt.BOOL

    _NW_OK: bool = True
except Exception:  # 非 Windows / 兼容性问题
    _NW_OK = False


def _delete_icon(hwnd: int) -> None:
    """从托盘移除图标。"""
    try:
        nid = _NOTIFYICONDATAW()
        nid.cbSize = _NID_SIZE
        nid.hWnd = hwnd
        nid.uID = 1
        _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(nid), 0)
    except Exception:
        pass


class _TrayIcon:
    """常驻托盘图标宿主：消息窗口 + 右键菜单 + 气球通知。"""

    _instance: Optional["_TrayIcon"] = None

    def __init__(self) -> None:
        self._hwnd: int = 0
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        # 保持 ctypes 回调/类引用，防止被 GC 导致访问冲突
        self._wndproc: Any = None
        self._wc: Any = None
        self._icon: int = 0
        self._on_show: Optional[Callable[[], None]] = None
        self._on_quit: Optional[Callable[[], None]] = None

    def start(
        self,
        on_show: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> bool:
        """启动托盘宿主（后台线程）。on_show/on_quit 会被在托盘线程调用。"""
        if not _NW_OK or self._running:
            return False
        self._on_show = on_show
        self._on_quit = on_quit
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        for _ in range(100):
            if self._hwnd:
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def _window_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """托盘窗口消息处理：响应 shell 发来的托盘回调消息。"""
        try:
            inst = _TrayIcon._instance
            if inst is not None and msg == _TRAY_MSG:
                mouse: int = lparam & 0xFFFF
                if mouse in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                    inst._fire(inst._on_show)
                    return 0
                if mouse in (_WM_RBUTTONUP, _WM_CONTEXTMENU):
                    inst._show_menu()
                    return 0
                return 0
            if msg == _WM_ADD_ICON and inst is not None:
                inst._add_icon()
                return 0
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception:
            try:
                return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            except Exception:
                return 0

    def _fire(self, cb: Optional[Callable[[], None]]) -> None:
        """在托盘线程调用回调（调用方需保证线程安全）。"""
        if cb is not None:
            try:
                cb()
            except Exception as exc:
                logger.debug("托盘回调异常: {}", exc)

    def _show_menu(self) -> None:
        """在鼠标位置弹出右键菜单。"""
        try:
            hmenu = _user32.CreatePopupMenu()
            if not hmenu:
                return
            _user32.AppendMenuW(hmenu, _MF_STRING, _ID_SHOW, "显示 DiffGuard")
            _user32.AppendMenuW(hmenu, _MF_STRING, _ID_QUIT, "退出")
            pt = wt.POINT()
            _user32.GetCursorPos(ctypes.byref(pt))
            cmd = int(
                _user32.TrackPopupMenu(
                    hmenu,
                    _TPM_RIGHTBUTTON | _TPM_RETURNCMD,
                    pt.x,
                    pt.y,
                    0,
                    self._hwnd,
                    None,
                )
            )
            _user32.DestroyMenu(hmenu)
            if cmd == _ID_SHOW:
                self._fire(self._on_show)
            elif cmd == _ID_QUIT:
                self._fire(self._on_quit)
        except Exception as exc:
            logger.debug("托盘右键菜单失败: {}", exc)

    @staticmethod
    def _icon_candidates(icon_name: str = "tray.ico") -> list:
        """托盘图标候选路径：兼容源码运行、PyInstaller 打包与任意启动目录。"""
        from pathlib import Path

        cands: list = []
        try:
            import sys

            cwd = Path.cwd()
            exe_dir = Path(sys.executable).resolve().parent
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                cands.append(Path(meipass) / icon_name)
            cands.append(exe_dir / icon_name)
            cands.append(exe_dir / "_internal" / icon_name)
            cands.append(cwd / icon_name)
        except Exception:
            cands.append(Path(icon_name))
        return cands

    @staticmethod
    def _system_tray_dark() -> bool:
        """判断系统任务栏是否为深色：读注册表 SystemUsesLightTheme。

        返回 True = 深色任务栏（用白色图标）；False = 浅色任务栏（用黑色图标）。
        读取失败时回退 True（深色，默认白图标）。
        """
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
                # 1 = 浅色任务栏（黑图标），0 = 深色任务栏（白图标）
                return value != 1
        except Exception:
            return True

    def _load_icon(self) -> int:
        """加载托盘图标：按系统任务栏主题自动选择黑白版本。

        深色任务栏 → tray_white.ico；浅色任务栏 → tray_black.ico；
        找不到对应文件时按顺序回退 tray.ico / app.ico，最后回退系统默认。
        """
        dark: bool = self._system_tray_dark()
        if dark:
            candidates: tuple[str, ...] = ("tray_white.ico", "tray.ico", "app.ico")
        else:
            candidates = ("tray_black.ico", "tray.ico", "app.ico")
        for icon_name in candidates:
            try:
                for p in self._icon_candidates(icon_name):
                    if p.is_file():
                        icon = _user32.LoadImageW(
                            None, str(p.resolve()), _IMG_ICON, 16, 16, _LR_LOADFROMFILE
                        )
                        if icon:
                            return int(icon)
            except Exception:
                pass
        return int(_user32.LoadIconW(None, _IDI_APPLICATION))

    def _add_icon(self) -> None:
        """注册常驻托盘图标（必须在消息循环启动后调用）。"""
        self._icon = self._load_icon()
        nid = _NOTIFYICONDATAW()
        nid.cbSize = _NID_SIZE
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = _NIF_ICON | _NIF_MESSAGE | _NIF_TIP
        nid.uCallbackMessage = _TRAY_MSG
        nid.hIcon = self._icon
        nid.szTip = "DiffGuard"
        if _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid), 0):
            ver = _NOTIFYICONDATAW()
            ver.cbSize = _NID_SIZE
            ver.hWnd = self._hwnd
            ver.uID = 1
            _shell32.Shell_NotifyIconW(
                _NIM_SETVERSION, ctypes.byref(ver), _NOTIFYICON_VERSION_4
            )

    def _run(self) -> None:
        """托盘线程主体：注册窗口类、建消息窗口、进入消息循环、注册图标。"""
        try:
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
            )
            self._wndproc = WNDPROC(_TrayIcon._window_proc)
            self._wc = _WNDCLASSW()
            self._wc.style = 0
            self._wc.lpfnWndProc = self._wndproc
            self._wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            self._wc.lpszClassName = "DiffGuardTrayWnd"
            try:
                _user32.RegisterClassW(ctypes.byref(self._wc))
            except Exception:
                pass  # 已注册过
            self._hwnd = _user32.CreateWindowExW(
                0,
                "DiffGuardTrayWnd",
                "DiffGuard",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                self._wc.hInstance,
                None,
            )
            if not self._hwnd:
                self._hwnd = 0
                return
            self._running = True
            msg = wt.MSG()
            _user32.PostMessageW(self._hwnd, _WM_ADD_ICON, 0, 0)
            while self._running:
                r = _user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if r <= 0:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            logger.debug("托盘图标启动失败: {}", exc)
            self._hwnd = 0
        self._running = False

    def notify(self, title: str, message: str, icon: int = 1) -> bool:
        """显示气球通知。icon: 1=info 2=warning 3=error。"""
        if not _NW_OK or not self._hwnd:
            return False
        try:
            nid = _NOTIFYICONDATAW()
            nid.cbSize = _NID_SIZE
            nid.hWnd = self._hwnd
            nid.uID = 1
            nid.uFlags = _NIF_ICON | _NIF_MESSAGE | _NIF_INFO
            nid.hIcon = self._icon
            nid.szInfo = message[:255]
            nid.szInfoTitle = title[:63]
            nid.dwInfoFlags = icon if icon in (1, 2, 3) else 1
            nid.uTimeout = 8000
            return bool(_shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(nid), 0))
        except Exception as exc:
            logger.debug("托盘通知失败: {}", exc)
            return False

    def destroy(self) -> None:
        """停止托盘线程并移除图标。"""
        self._running = False
        if _NW_OK and self._hwnd:
            try:
                _delete_icon(self._hwnd)
                _user32.PostMessageW(self._hwnd, _WM_QUIT, 0, 0)
            except Exception:
                pass
        self._hwnd = 0


def tray_host(
    on_show: Optional[Callable[[], None]] = None,
    on_quit: Optional[Callable[[], None]] = None,
) -> bool:
    """启动常驻托盘图标并注册回调（回调在托盘线程调用，需自行保证线程安全）。"""
    if not _NW_OK:
        logger.debug("托盘不可用（缺少系统托盘支持）")
        return False
    if _TrayIcon._instance is None:
        _TrayIcon._instance = _TrayIcon()
    inst = _TrayIcon._instance
    if inst._running:
        inst._on_show = on_show
        inst._on_quit = on_quit
        return True
    return inst.start(on_show, on_quit)


def tray_notify(title: str, message: str, icon: int = 1) -> bool:
    """保证托盘图标存在并显示气球通知。icon: 1=info 2=warning 3=error。"""
    if not _NW_OK:
        logger.debug("托盘通知不可用")
        return False
    if _TrayIcon._instance is None:
        _TrayIcon._instance = _TrayIcon()
        if not _TrayIcon._instance.start():
            return False
    return _TrayIcon._instance.notify(title, message, icon)


def tray_destroy() -> None:
    """销毁托盘图标（应用退出时调用）。"""
    if _TrayIcon._instance is not None:
        _TrayIcon._instance.destroy()
