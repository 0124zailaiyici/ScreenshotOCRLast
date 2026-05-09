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

class HotkeyListener:
    """全局热键监听器：基于 Windows Native RegisterHotKey API"""

    def __init__(self, callback, error_callback=None):
        self.callback = callback
        self.error_callback = error_callback
        self._running = False
        self._thread = None
        self._hotkey_id = 1
        self.current_hotkey = ""
        
    def _parse_hotkey(self, hotkey_str):
        """将字符串格式 (如 <ctrl>+<shift>+a) 转换为 Win32 修饰符和键码"""
        modifiers = MOD_NOREPEAT
        key_code = 0
        
        parts = hotkey_str.lower().split('+')
        for part in parts:
            part = part.strip()
            if part == '<ctrl>':
                modifiers |= MOD_CONTROL
            elif part == '<shift>':
                modifiers |= MOD_SHIFT
            elif part == '<alt>':
                modifiers |= MOD_ALT
            elif part == '<win>':
                modifiers |= MOD_WIN
            elif len(part) == 1:
                key_code = ord(part.upper())
            elif part.startswith('f') and part[1:].isdigit():
                key_code = 0x6F + int(part[1:])
                
        return modifiers, key_code

    def _loop(self, modifiers, key_code, hotkey_str):
        """热键消息循环线程"""
        user32 = ctypes.windll.user32
        
        if not user32.RegisterHotKey(None, self._hotkey_id, modifiers, key_code):
            error_code = ctypes.windll.kernel32.GetLastError()
            if self.error_callback:
                self.error_callback(hotkey_str, error_code)
            return

        self._running = True
        self.current_hotkey = hotkey_str
        msg = wintypes.MSG()
        try:
            while self._running:
                if user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == WM_HOTKEY:
                        if self.callback:
                            threading.Thread(target=self.callback, daemon=True).start()
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)
            self._running = False

    def start(self, hotkey_str="<alt>+<shift>+s"):
        """启动监听"""
        if self._running:
            self.stop()
            
        modifiers, key_code = self._parse_hotkey(hotkey_str)
        if key_code == 0:
            print(f"无效的热键格式: {hotkey_str}")
            return
            
        self._thread = threading.Thread(target=self._loop, args=(modifiers, key_code, hotkey_str), daemon=True)
        self._thread.start()

    def stop(self):
        """停止监听"""
        if self._running and self._thread:
            self._running = False
            ctypes.windll.user32.PostThreadMessageW(self._thread.ident, 0, 0, 0)
