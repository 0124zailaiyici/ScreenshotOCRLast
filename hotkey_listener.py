import ctypes
import threading
from ctypes import wintypes

# Win32 API Constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

VK_CODES = {
    'ctrl': 0x11, 'shift': 0x10, 'alt': 0x12, 'win': 0x5B,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
}

# WH_KEYBOARD_LL flags
LLKHF_ALTDOWN = 0x20


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]


class HotkeyListener:
    """全局热键监听器：基于 WH_KEYBOARD_LL 低层键盘钩子"""

    def __init__(self, callback, error_callback=None):
        self.callback = callback
        self.error_callback = error_callback
        self._running = False
        self._thread = None
        self._current_hotkey = ""
        self._hook = None
        self._hook_proc = None  # keep reference to prevent GC

    def _get_modifiers_state(self, kb_flags=0):
        """检查当前按下的修饰键（优先用 hook flags 检测 Alt）"""
        user32 = ctypes.windll.user32
        mods = 0
        if kb_flags & LLKHF_ALTDOWN:
            mods |= MOD_ALT
        elif user32.GetAsyncKeyState(VK_CODES['alt']) & 0x8000:
            mods |= MOD_ALT
        if user32.GetAsyncKeyState(VK_CODES['ctrl']) & 0x8000:
            mods |= MOD_CONTROL
        if user32.GetAsyncKeyState(VK_CODES['shift']) & 0x8000:
            mods |= MOD_SHIFT
        if user32.GetAsyncKeyState(VK_CODES['win']) & 0x8000:
            mods |= MOD_WIN
        return mods

    def _parse_hotkey(self, hotkey_str):
        parts = [p.strip().lower() for p in hotkey_str.split('+')]
        required_mods = 0
        key_code = 0
        for part in parts:
            if part == '<alt>' or part == 'alt':
                required_mods |= MOD_ALT
            elif part == '<ctrl>' or part == 'ctrl':
                required_mods |= MOD_CONTROL
            elif part == '<shift>' or part == 'shift':
                required_mods |= MOD_SHIFT
            elif part == '<win>' or part == 'win':
                required_mods |= MOD_WIN
            elif part.startswith('f') and part[1:].isdigit():
                key_code = VK_CODES.get(part, 0)
            elif len(part) == 1:
                key_code = ord(part.upper())
        return required_mods, key_code

    def _hook_callback(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if self._current_hotkey:
                required_mods, target_vk = self._parse_hotkey(self._current_hotkey)
                if kb.vkCode == target_vk:
                    current_mods = self._get_modifiers_state(kb.flags)
                    if current_mods == required_mods:
                        threading.Thread(target=self.callback, daemon=True).start()
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _run(self, hotkey_str):
        user32 = ctypes.windll.user32

        # Create the hook procedure
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self._hook_proc = HOOKPROC(self._hook_callback)

        # Install the hook
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            ctypes.windll.kernel32.GetModuleHandleW(None),
            0
        )
        if not self._hook:
            err = ctypes.windll.kernel32.GetLastError()
            print(f"SetWindowsHookEx failed, error={err}")
            if self.error_callback:
                self.error_callback(hotkey_str, err)
            return

        self._running = True
        self._current_hotkey = hotkey_str
        msg = wintypes.MSG()
        try:
            while self._running:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._running = False

    def start(self, hotkey_str="<alt>+x"):
        if self._running:
            self.stop()
        if not hotkey_str:
            return
        self._thread = threading.Thread(
            target=self._run, args=(hotkey_str,), daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        self._current_hotkey = ""
        if self._thread and self._thread.is_alive():
            ctypes.windll.user32.PostThreadMessageW(self._thread.ident, 0, 0, 0)
            self._thread = None

    @property
    def current_hotkey(self):
        return self._current_hotkey