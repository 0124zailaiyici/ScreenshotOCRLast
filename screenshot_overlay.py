import tkinter as tk
from PIL import Image, ImageTk, ImageGrab
from config import config_manager
from ui_theme import theme_manager, FONT_BUTTON
from ui_icons import icons


class ScreenshotOverlay:
    """全屏截图覆盖层：真实画面 + 选区 + 浮动工具栏"""

    def __init__(self, on_select_callback, master=None):
        self.on_select = on_select_callback
        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()

        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # 截屏当前画面（在窗口显示前执行）
        self.full_screenshot = ImageGrab.grab(all_screens=True)

        # 刷新主题
        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )
        theme = theme_manager.theme

        # 窗口设置
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.config(cursor="cross")

        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{self.screen_width}x{self.screen_height}+0+0")

        # 真实截图作为画布背景（无暗化、无遮罩）
        self._bg_image = ImageTk.PhotoImage(self.full_screenshot)

        self.canvas = tk.Canvas(
            self.root, cursor="cross",
            highlightthickness=0,
            width=self.screen_width, height=self.screen_height
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self._bg_image, anchor="nw")

        # 状态变量
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.rect_bg_id = None
        self.toolbar = None
        self.selection_img = None       # 原始截图原图（传给回调）
        self.selection_coords = None

        # 事件绑定
        self.root.bind("<ButtonPress-1>", self._on_button_press)
        self.root.bind("<B1-Motion>", self._on_mouse_drag)
        self.root.bind("<ButtonRelease-1>", self._on_button_release)
        self.root.bind("<Escape>", lambda e: self._on_cancel())

    def _on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.canvas.delete(self.rect_bg_id)
        if self.toolbar:
            self.toolbar.destroy()
            self.toolbar = None

        self.rect_bg_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="white", width=3
        )
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline=theme_manager.accent_color, width=1, dash=(4, 4)
        )

    def _on_mouse_drag(self, event):
        self.canvas.coords(self.rect_bg_id, self.start_x, self.start_y, event.x, event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_button_release(self, event):
        end_x, end_y = event.x, event.y
        x1, y1 = min(self.start_x, end_x), min(self.start_y, end_y)
        x2, y2 = max(self.start_x, end_x), max(self.start_y, end_y)

        if x2 - x1 < 5 or y2 - y1 < 5:
            return

        self.selection_coords = (x1, y1, x2, y2)
        self.selection_img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
        self._show_toolbar(x2, y2)

    def _show_toolbar(self, x, y):
        """在选区右下角显示图标+文字的浮动工具栏"""
        theme = theme_manager.theme
        self.toolbar = tk.Toplevel(self.root)
        self.toolbar.overrideredirect(True)
        self.toolbar.attributes("-topmost", True)

        # 外框（border_default 色模拟 1px 边框）
        self.toolbar.config(bg=theme.border_default)

        # 内框（工具栏表面）
        inner = tk.Frame(self.toolbar, bg=theme.bg_toolbar)
        inner.pack(padx=1, pady=1)

        # 避让屏幕边缘（按钮宽度约 220px）
        toolbar_w = 220
        if x + toolbar_w > self.screen_width:
            x = self.screen_width - toolbar_w - 10
        if y + 50 > self.screen_height:
            y = y - 60
        self.toolbar.geometry(f"+{x-180}+{y+5}")

        btn_kw = {
            "bg": theme.bg_toolbar,
            "activebackground": theme.bg_hover,
            "font": FONT_BUTTON,
            "relief": "flat",
            "padx": 8,
            "cursor": "hand2",
        }

        # 鲜艳图标 + 自适应文字颜色
        text_color = theme.text_primary
        accent = theme_manager.accent_color
        green = "#107C10"

        # 图钉按钮
        pin_icon = icons.get_pin(accent)
        btn_pin = tk.Button(
            inner, image=pin_icon, text=" 钉住",
            compound="left", fg=text_color,
            command=lambda: self._trigger("pin"), **btn_kw
        )
        btn_pin._icon_ref = pin_icon
        btn_pin.pack(side="left")

        # 识字按钮
        search_icon = icons.get_search(green)
        btn_ocr = tk.Button(
            inner, image=search_icon, text=" 识字",
            compound="left", fg=text_color,
            command=lambda: self._trigger("ocr"), **btn_kw
        )
        btn_ocr._icon_ref = search_icon
        btn_ocr.pack(side="left")

        # 复制按钮
        clip_icon = icons.get_clipboard(accent)
        btn_copy = tk.Button(
            inner, image=clip_icon, text=" 复制",
            compound="left", fg=text_color,
            command=lambda: self._trigger("copy"), **btn_kw
        )
        btn_copy._icon_ref = clip_icon
        btn_copy.pack(side="left")

    def _on_cancel(self):
        """用户取消截图（按 Esc），通知主循环销毁 root 以释放锁"""
        if self.on_select:
            self.on_select(None, None, None)
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass

    def _trigger(self, action):
        if self.on_select:
            self.on_select(action, self.selection_img, self.selection_coords)
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()


def select_region(callback, master=None):
    overlay = ScreenshotOverlay(callback, master=master)
    if not master:
        overlay.run()
