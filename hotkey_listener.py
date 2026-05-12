import ctypes
import threading
import time

user32 = ctypes.windll.user32

VK_CODES = {
    'ctrl': 0x11,
    'shift': 0x10,
    'alt': 0x12,
    'win': 0x5B,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
}


class HotkeyListener:
    """全局热键监听器：基于 GetAsyncKeyState 轮询（兼容无钩子环境）"""

    def __init__(self, callback, error_callback=None):
        self.callback = callback
        self.error_callback = error_callback
        self._running = False
        self._thread = None
        self._current_hotkey = ""

    def _parse_hotkey(self, hotkey_str):
        parts = [p.strip().lower() for p in hotkey_str.split('+')]
        modifiers = set()
        key_char = None
        for part in parts:
            if part in ('ctrl', 'shift', 'alt', 'win'):
                modifiers.add(part)
            elif part.startswith('f') and part[1:].isdigit():
                key_char = part.lower()
            elif len(part) == 1:
                key_char = part.upper()
        return modifiers, key_char

    def _is_key_down(self, vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def _run(self, hotkey_str):
        target_mods, target_char = self._parse_hotkey(hotkey_str)
        if not target_char:
            return

        mod_codes = [VK_CODES[m] for m in target_mods if m in VK_CODES]
        char_code = VK_CODES.get(target_char.lower(), ord(target_char.upper()) if len(target_char) == 1 else 0)

        self._running = True
        self._current_hotkey = hotkey_str
        was_pressed = False

        while self._running:
            all_mods_down = all(self._is_key_down(vk) for vk in mod_codes)
            char_down = self._is_key_down(char_code) if char_code else True

            if all_mods_down and char_down:
                if not was_pressed:
                    was_pressed = True
                    threading.Thread(target=self.callback, daemon=True).start()
                    time.sleep(0.15)
            else:
                was_pressed = False
            time.sleep(0.05)

    def start(self, hotkey_str="f1"):
        if self._running:
            self.stop()
        self._running = True
        self._thread = threading.Thread(target=self._run, args=(hotkey_str,), daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._current_hotkey = ""

    @property
    def current_hotkey(self):
        return self._current_hotkey