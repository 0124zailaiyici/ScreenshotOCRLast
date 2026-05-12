import ctypes
import threading
import time
from ctypes import wintypes

# Win32 API Constants
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_CODES = {
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
}


class HotkeyListener:
    """全局热键监听器：基于 Windows Native RegisterHotKey API"""

    def __init__(self, callback, error_callback=None):
        self.callback = callback
        self.error_callback = error_callback
        self._running = False
        self._thread = None
        self._current_hotkey = ""
        self._hotkey_id = 1

    def _parse_hotkey(self, hotkey_str):
        parts = [p.strip().lower() for p in hotkey_str.split('+')]
        modifiers = MOD_NOREPEAT
        key_code = 0
        for part in parts:
            if part == '<ctrl>' or part == 'ctrl':
                modifiers |= MOD_CONTROL
            elif part == '<shift>' or part == 'shift':
                modifiers |= MOD_SHIFT
            elif part == '<alt>' or part == 'alt':
                modifiers |= MOD_ALT
            elif part == '<win>' or part == 'win':
                modifiers |= MOD_WIN
            elif part.startswith('f') and part[1:].isdigit():
                key_code = VK_CODES.get(part, 0)
            elif len(part) == 1:
                key_code = ord(part.upper())
        return modifiers, key_code

    def _loop(self, modifiers, key_code, hotkey_str):
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, self._hotkey_id, modifiers, key_code):
            err = ctypes.windll.kernel32.GetLastError()
            print(f"RegisterHotKey failed for '{hotkey_str}', error={err}")
            if self.error_callback:
                self.error_callback(hotkey_str, err)
            return

        self._running = True
        self._current_hotkey = hotkey_str
        msg = wintypes.MSG()
        try:
            while self._running:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0:
                    break
                if ret == -1:
                    break
                if msg.message == WM_HOTKEY:
                    if self.callback:
                        threading.Thread(target=self.callback, daemon=True).start()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)
            self._running = False

    def start(self, hotkey_str="f1"):
        if self._running:
            self.stop()
        modifiers, key_code = self._parse_hotkey(hotkey_str)
        if key_code == 0:
            print(f"Invalid hotkey format: {hotkey_str}")
            return
        self._thread = threading.Thread(
            target=self._loop, args=(modifiers, key_code, hotkey_str), daemon=True
        )
        self._thread.start()

    def stop(self):
        if self._running and self._thread:
            self._running = False
            ctypes.windll.user32.PostThreadMessageW(self._thread.ident, 0, 0, 0)

    @property
    def current_hotkey(self):
        return self._current_hotkey