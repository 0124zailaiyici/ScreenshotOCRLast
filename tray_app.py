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

    def _create_image(self, width=64, height=64, color1=None, color2=None):
        """生成相机形状的托盘图标，深色/浅色模式自适应"""
        if color1 is None:
            color1 = "#202020" if config_manager.is_dark_mode() else "white"
        if color2 is None:
            color2 = config_manager.get_system_accent_color()

        image = Image.new('RGBA', (width, height), color1)
        dc = ImageDraw.Draw(image)

        # 相机机身（圆角矩形）
        dc.rounded_rectangle([8, 18, 56, 52], radius=8, fill=color2)

        # 取景器凸起
        dc.rectangle([22, 12, 42, 18], fill=color2)

        # 外层镜头环
        dc.ellipse([18, 24, 46, 48], fill=color1, outline=color2, width=3)

        # 内层镜头
        dc.ellipse([24, 30, 40, 42], fill=color2)

        # 镜头高光反光
        dc.ellipse([20, 26, 26, 30], fill="white")

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
