from pynput import keyboard
import queue
import threading

class HotkeyListener:
    """全局热键监听器：基于 pynput 和线程安全队列"""

    def __init__(self, callback):
        self.callback = callback
        self.queue = queue.Queue()
        self.listener = None
        self._running = False

    def _on_activate(self):
        self.queue.put(True)
        if self.callback:
            threading.Thread(target=self.callback, daemon=True).start()

    def start(self, hotkey_str="<alt>+x"):
        if self._running:
            return
        try:
            self.listener = keyboard.GlobalHotKeys({
                hotkey_str: self._on_activate
            })
            self.listener.start()
            self._running = True
            print(f"已启动热键监听: {hotkey_str}")
        except Exception as e:
            print(f"启动热键监听失败: {e}")

    def stop(self):
        if self.listener:
            self.listener.stop()
            self._running = False

    @property
    def current_hotkey(self):
        return getattr(self.listener, '_hotkey_str', '') if self.listener else ''

    @current_hotkey.setter
    def current_hotkey(self, value):
        pass