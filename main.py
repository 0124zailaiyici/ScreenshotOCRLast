import tkinter as tk
import sys
import os
import threading
import socket
import queue
import ctypes
from PIL import Image
from hotkey_listener import HotkeyListener
from tray_app import TrayApp
from screenshot_overlay import select_region
from ocr_window import show_ocr_window
from pin_window import show_pin_window
from config import config_manager
from translator import translator
from ui_theme import theme_manager
from ui_icons import icons


ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\ScreenshotOCR_SingleInstance_Mutex"
IPC_PORT = 49152


class ScreenshotOCRApp:

    def __init__(self):
        self._check_single_instance()
        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )
        self._screenshot_lock = threading.Lock()

        # 1. 热键监听 — 回调直接在同线程创建 Tk 截图会话（与原始代码一致）
        self.hotkey = HotkeyListener(callback=self._on_screenshot_trigger)

        # 2. 系统托盘
        self.tray = TrayApp(
            on_exit_callback=self._on_exit,
            on_screenshot_callback=self._on_screenshot_trigger
        )

        # 3. 持久化 Tk 线程 — 仅用于显示钉住窗口
        #    必须在 _start_ipc_server() **之前**建好：IPC 线程一启动就可能收到
        #    "screenshot" 消息并回调 _on_screenshot_trigger，而它要用 self._pin_queue。
        #    若队列还没建，会抛 AttributeError，并被 _start_ipc_server 里那个包着整个
        #    while 循环的 except 吞掉 —— 后果是 IPC 服务线程**永久退出**，
        #    之后第二个实例再启动就唤不出截图了。
        self._pin_root = None
        self._pin_queue = queue.Queue()
        self._pin_ready = threading.Event()
        self._pin_thread = threading.Thread(target=self._pin_loop, daemon=True)
        self._pin_thread.start()
        self._pin_ready.wait()

        # 4. IPC 监听
        self._start_ipc_server()

    # ---- 单实例检测 ----

    def _check_single_instance(self):
        self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect(('127.0.0.1', IPC_PORT))
                    s.sendall(b"screenshot")
                sys.exit(0)
            except Exception:
                ctypes.windll.kernel32.CloseHandle(self.mutex)
                self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)

    def _start_ipc_server(self):
        def _run():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', IPC_PORT))
                    s.listen()
                    while True:
                        conn, _ = s.accept()
                        with conn:
                            if conn.recv(1024) == b"screenshot":
                                self._on_screenshot_trigger()
                except Exception:
                    pass
        threading.Thread(target=_run, daemon=True).start()

    # ---- 持久化 Tk 线程（仅钉住窗口） ----

    def _pin_loop(self):
        root = tk.Tk()
        root.withdraw()
        self._pin_root = root
        self._pin_ready.set()

        def _poll():
            try:
                while True:
                    fn = self._pin_queue.get_nowait()
                    try:
                        fn()
                    except Exception as e:
                        print(f"钉住队列异常: {e}")
            except queue.Empty:
                pass
            root.after(50, _poll)

        root.after(50, _poll)
        try:
            root.mainloop()
        except Exception as e:
            print(f"钉住 Tk 线程退出: {e}")


    def _on_screenshot_trigger(self):
        if not self._screenshot_lock.acquire(blocking=False):
            # 锁仍被持有。绝大多数情况下这是**正常**的：截图选区与 OCR 窗口
            # 会一直持有锁到会话结束（用户可能开着 OCR 窗口读文字、等翻译），
            # 此时必须静默忽略，与旧行为保持一致。
            #
            # 唯一可以安全回收的情形是消费队列的 Tk 线程已经死亡 —— 那时队列
            # 不会再被处理，锁确实永久泄漏。
            #
            # 绝不能按时间阈值回收：threading.Lock 没有属主概念，释放一个
            # 仍被合法持有的锁会让两个截图会话并发执行，并使后续的 release
            # 抛 "release unlocked lock"，互斥彻底失效。
            if self._pin_thread is not None and self._pin_thread.is_alive():
                return
            print("Tk 线程已退出，回收遗留的截图会话锁")
            try:
                self._screenshot_lock.release()
            except RuntimeError:
                pass
            if not self._screenshot_lock.acquire(blocking=False):
                return

        try:
            self._pin_queue.put(self._do_screenshot)
        except Exception as e:
            print(f"截图任务入队失败: {e}")
            try:
                self._screenshot_lock.release()
            except RuntimeError:
                pass

    def _do_screenshot(self):
        """在 Tk 线程中执行截图"""
        try:
            theme_manager.update(
                is_dark=config_manager.is_dark_mode(),
                accent_color=config_manager.get_system_accent_color()
            )

            # 用隐藏的 Toplevel 作为会话容器，生命周期绑定整个截图流程
            session = tk.Toplevel(self._pin_root)
            session.withdraw()

            def on_selection(action, image, coords):
                if not image:
                    _end_session()
                    return

                if action == "ocr":
                    win = show_ocr_window(image, coords=coords, master=session)
                    win.root.bind("<Destroy>", lambda e: _end_session(), True)
                elif action == "pin":
                    show_pin_window(image, coords=coords, master=self._pin_root)
                    _end_session()
                elif action == "copy":
                    from clipboard_manager import clipboard_manager
                    if clipboard_manager.copy_image(image):
                        try:
                            self.tray.notify("复制成功", "图片已复制到剪贴板")
                        except Exception:
                            pass
                    _end_session()
                else:
                    _end_session()

            def _end_session():
                try:
                    if session.winfo_exists():
                        session.destroy()
                except Exception:
                    pass

            select_region(on_selection, master=session)

            # 一直阻塞到所有子窗口关闭（OCR 窗口关闭时销毁 session）
            self._pin_root.wait_window(session)
        except Exception as e:
            print(f"截图会话出错: {e}")
        finally:
            icons.clear_cache()
            self._screenshot_lock.release()

    def _check_exit(self, root):
        def _do():
            try:
                children = [c for c in root.winfo_children()
                           if c.winfo_exists() and isinstance(c, tk.Toplevel)]
                if not children:
                    root.destroy()
            except Exception:
                pass
        root.after(100, _do)

    # ---- 恢复持久化钉住窗口 ----

    def _restore_pinned_windows(self):
        for item in config_manager.get_pinned_items():
            try:
                if os.path.exists(item["path"]):
                    img = Image.open(item["path"])
                    self._pin_queue.put(lambda img=img, item=item: show_pin_window(
                        img, coords=item.get("coords"),
                        master=self._pin_root,
                        pin_id=item["id"],
                        scale=item.get("scale", 1.0)
                    ))
            except Exception as e:
                print(f"恢复钉住窗口失败: {e}")

    # ---- 退出 ----

    def _on_exit(self):
        self.hotkey.stop()
        sys.exit(0)

    def run(self):
        # 显式迁移旧版写在 CWD 的翻译历史（不在模块导入期做，避免副作用）
        translator.migrate_legacy_history()
        self._restore_pinned_windows()
        self.hotkey.start(config_manager.get("hotkey"))
        print("ScreenshotOCR 已常驻系统托盘 (Alt+X 触发)")
        self.tray.run()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = ScreenshotOCRApp()
    app.run()
