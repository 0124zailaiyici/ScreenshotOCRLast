import tkinter as tk
import sys
import os
from hotkey_listener import HotkeyListener
from tray_app import TrayApp
from screenshot_overlay import select_region
from ocr_window import show_ocr_window
from pin_window import show_pin_window
from config import config_manager

class ScreenshotOCRApp:
    """ScreenshotOCR 主程序类"""

    def __init__(self):
        # 1. 初始化热键监听器
        self.hotkey = HotkeyListener(callback=self._on_screenshot_trigger)
        
        # 2. 初始化系统托盘
        self.tray = TrayApp(
            on_exit_callback=self._on_exit,
            on_screenshot_callback=self._on_screenshot_trigger
        )

    def _on_screenshot_trigger(self):
        """当热键或菜单触发截图时"""
        # 在工作线程中创建 Tk 根窗口，作为本次截图会话的生命周期管理器
        try:
            root = tk.Tk()
            root.withdraw()  # 隐藏主窗口
            
            def on_selection(action, image, coords):
                if not image:
                    # 使用 after 确保在主循环中安全销毁
                    root.after(10, root.destroy)
                    return

                if action == "ocr":
                    win = show_ocr_window(image, master=root)
                    win.root.bind("<Destroy>", lambda e: self._check_exit(root))
                elif action == "pin":
                    win = show_pin_window(image, coords=coords, master=root)
                    win.root.bind("<Destroy>", lambda e: self._check_exit(root))
                elif action == "copy":
                    from clipboard_manager import clipboard_manager
                    if clipboard_manager.copy_image(image):
                        self.tray.notify("复制成功", "图片已复制到剪贴板")
                    root.after(10, root.destroy)
                else:
                    root.after(10, root.destroy)

            # 启动截图覆盖层 (传入 root 确保它在同一个主循环中)
            select_region(on_selection, master=root)
            
            # 如果配置了自动复制，则在选区完成后立即执行 (由 select_region 触发的 image 对象存在时)
            # 但由于 select_region 是异步回调模式，我们在 on_selection 中处理
            
            # 运行主循环，直到 root.destroy() 被调用
            root.mainloop()
        except Exception as e:
            print(f"截图会话出错: {e}")

    def _check_exit(self, root):
        """检查是否还有活跃的 Toplevel 窗口，如果没有则销毁 root"""
        # 延迟检查，因为 <Destroy> 触发时窗口可能还在 winfo_children 中
        def _do_check():
            try:
                # 过滤掉已经被销毁的窗口
                children = [c for c in root.winfo_children() if c.winfo_exists() and isinstance(c, tk.Toplevel)]
                if not children:
                    root.destroy()
            except Exception:
                pass
        root.after(100, _do_check)

    def _on_exit(self):
        """退出程序"""
        print("正在退出...")
        self.hotkey.stop()
        sys.exit(0)

    def run(self):
        """启动应用"""
        # 1. 启动热键监听
        self.hotkey.start(config_manager.get("hotkey"))
        
        # 2. 启动托盘 (阻塞主线程)
        print("ScreenshotOCR 已常驻系统托盘 (Ctrl+Shift+A 触发)")
        self.tray.run()

if __name__ == "__main__":
    # Windows 下确保 DPI 适配
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = ScreenshotOCRApp()
    app.run()
