import tkinter as tk
import sys
import os
import threading
import socket
import ctypes
from hotkey_listener import HotkeyListener
from tray_app import TrayApp
from screenshot_overlay import select_region
from ocr_window import show_ocr_window
from pin_window import show_pin_window
from config import config_manager
from ui_theme import theme_manager
from ui_icons import icons

# Windows API Constants
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\ScreenshotOCR_SingleInstance_Mutex"
IPC_PORT = 49152  # 随机选择一个非占用端口

class ScreenshotOCRApp:
    """ScreenshotOCR 主程序类"""

    def __init__(self):
        self._check_single_instance()
        # 初始化主题
        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )
        # 截图会话并发锁，防止快速多次按热键创建多个 Tk 实例
        self._screenshot_lock = threading.Lock()

        # 1. 初始化热键监听器
        self.hotkey = HotkeyListener(callback=self._on_screenshot_trigger)

        # 2. 初始化系统托盘
        self.tray = TrayApp(
            on_exit_callback=self._on_exit,
            on_screenshot_callback=self._on_screenshot_trigger
        )

        # 3. 启动 IPC 监听线程
        self._start_ipc_server()

    def _check_single_instance(self):
        """使用 Mutex + IPC 双重检测单实例"""
        self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_error = ctypes.windll.kernel32.GetLastError()

        if last_error == ERROR_ALREADY_EXISTS:
            # 尝试 IPC 连接验证旧实例是否还活着
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect(('127.0.0.1', IPC_PORT))
                    s.sendall(b"screenshot")
                print("程序已在运行，正在唤醒现有实例...")
                sys.exit(0)
            except Exception:
                # IPC 连接失败 → 旧实例已死，释放残留 Mutex 后继续启动
                ctypes.windll.kernel32.CloseHandle(self.mutex)
                self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
                print("检测到残留的互斥锁，已清除，继续启动...")

    def _start_ipc_server(self):
        """启动简单的本地 Socket 服务端接收指令"""
        def server_thread():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', IPC_PORT))
                    s.listen()
                    while True:
                        conn, addr = s.accept()
                        with conn:
                            data = conn.recv(1024)
                            if data == b"screenshot":
                                # 收到指令，触发截图
                                self._on_screenshot_trigger()
                except Exception as e:
                    print(f"IPC Server 出错: {e}")

        threading.Thread(target=server_thread, daemon=True).start()

    def _on_screenshot_trigger(self):
        """当热键或菜单触发截图时"""
        # 每次截图刷新主题（适应系统主题变更）
        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )
        # 防止重复触发：如果已有截图会话进行中，忽略本次热键
        if not self._screenshot_lock.acquire(blocking=False):
            return

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
                    win = show_ocr_window(image, coords=coords, master=root)
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
        finally:
            # 清除图标缓存（Tk 根窗口已销毁，旧 PhotoImage 引用失效）
            icons.clear_cache()
            self._screenshot_lock.release()

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
