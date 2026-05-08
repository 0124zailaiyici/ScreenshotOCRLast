from pynput import keyboard
import queue
import threading

class HotkeyListener:
    """全局热键监听器：基于 pynput 和线程安全队列"""

    def __init__(self, callback):
        """
        :param callback: 热键触发时的回调函数
        """
        self.callback = callback
        self.queue = queue.Queue()
        self.listener = None
        self._running = False

    def _on_activate(self):
        """热键激活时的内部处理"""
        # 将触发事件放入队列，由主线程或工作线程消费，避免阻塞监听线程
        self.queue.put(True)
        if self.callback:
            # 在新线程中执行回调，确保不阻塞 pynput 监听
            threading.Thread(target=self.callback, daemon=True).start()

    def start(self, hotkey_str="<ctrl>+<shift>+a"):
        """启动监听"""
        if self._running:
            return
            
        try:
            # pynput.keyboard.GlobalHotKeys 方便处理组合键
            self.listener = keyboard.GlobalHotKeys({
                hotkey_str: self._on_activate
            })
            self.listener.start()
            self._running = True
            print(f"已启动热键监听: {hotkey_str}")
        except Exception as e:
            print(f"启动热键监听失败: {e}")

    def stop(self):
        """停止监听"""
        if self.listener:
            self.listener.stop()
            self._running = False

# 示例用法 (通常在 main.py 中初始化)
