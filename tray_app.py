import pystray
from PIL import Image, ImageDraw
import threading
from config import config_manager

class TrayApp:
    """系统托盘应用：管理右键菜单和通知"""

    def __init__(self, on_exit_callback, on_screenshot_callback):
        self.on_exit = on_exit_callback
        self.on_screenshot = on_screenshot_callback
        self.icon = None

    def _create_image(self, width=64, height=64, color1="white", color2="#0078D4"):
        """生成默认的托盘图标 (如果没有本地文件)"""
        image = Image.new('RGB', (width, height), color1)
        dc = ImageDraw.Draw(image)
        # 绘制一个简单的截图/相机形状
        dc.rectangle([10, 20, 54, 50], outline=color2, width=4)
        dc.ellipse([25, 28, 39, 42], outline=color2, width=3)
        return image

    def _on_screenshot_click(self, icon, item):
        """点击菜单触发截图"""
        if self.on_screenshot:
            self.on_screenshot()

    def _on_exit_click(self, icon, item):
        """点击退出"""
        icon.stop()
        if self.on_exit:
            self.on_exit()

    def notify(self, title, message):
        """发送系统通知"""
        if config_manager.get("notification_enabled") and self.icon:
            self.icon.notify(message, title)

    def run(self):
        """运行托盘主循环"""
        menu = pystray.Menu(
            pystray.MenuItem("立即截图 (Ctrl+Shift+A)", self._on_screenshot_click),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_exit_click)
        )
        
        self.icon = pystray.Icon(
            "ScreenshotOCR",
            self._create_image(),
            "ScreenshotOCR",
            menu
        )
        
        # 托盘图标运行在自己的循环中
        self.icon.run()

    def run_async(self):
        """在后台线程运行托盘"""
        threading.Thread(target=self.run, daemon=True).start()
