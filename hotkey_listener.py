import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C


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
            if part == '<ctrl>':
                modifiers.add('ctrl')
            elif part == '<shift>':
                modifiers.add('shift')
            elif part == '<alt>':
                modifiers.add('alt')
            elif part == '<win>':
                modifiers.add('win')
            elif len(part) == 1:
                key_char = part.upper()
        return modifiers, key_char

    def _is_key_down(self, vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def _run(self, hotkey_str):
        mod_codes = []
        char_code = 0

        target_mods, target_char = self._parse_hotkey(hotkey_str)
        if not target_mods and not target_char:
            return

        if 'ctrl' in target_mods:
            mod_codes.append(VK_CONTROL)
        if 'shift' in target_mods:
            mod_codes.append(VK_SHIFT)
        if 'alt' in target_mods:
            mod_codes.append(VK_MENU)
        if 'win' in target_mods:
            mod_codes.append(VK_LWIN)
        if target_char:
            char_code = ord(target_char)

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

    def start(self, hotkey_str="<ctrl>+<shift>+s"):
        if self._running:
            self.stop()

        target_mods, target_char = self._parse_hotkey(hotkey_str)
        if not target_mods and not target_char:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(hotkey_str,),
            daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        self._current_hotkey = ""

    @property
    def current_hotkey(self):
        return self._current_hotkey