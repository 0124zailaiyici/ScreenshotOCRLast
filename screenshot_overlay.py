import tkinter as tk
from PIL import Image, ImageTk, ImageGrab
from config import config_manager
from ui_theme import (
    FONT_BUTTON,
    RADIUS_M,
    SPACE_SM,
    px,
    theme_manager,
)
from ui_icons import icons
from ui_widgets import RoundedCard, flat_button, vdivider


class ScreenshotOverlay:
    """全屏截图覆盖层：真实画面 + 选区 + 浮动工具栏"""

    def __init__(self, on_select_callback, master=None):
        self.on_select = on_select_callback
        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()

        # 注意：这里**不要**再调 SetProcessDpiAwareness()。它只能在整个进程里生效一次，
        # 而 main.py 在 __main__ 里已经调过了；走到这里时 Tk 解释器已经存在，再调只会
        # 返回 E_ACCESSDENIED 并被下面的 except 吞掉 —— 看起来有用，其实完全无效。
        # 选区坐标与物理像素的对应关系由 main.py 那一次调用保证。

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

    # 抠圆角用的透明色键。必须是界面上绝不会出现的颜色。
    _TRANSPARENT_KEY = "#FF00FE"

    def _show_toolbar(self, x, y):
        """在选区右下角显示图标+文字的浮动工具栏。

        圆角靠 ``-transparentcolor`` 抠：把一个绝不使用的颜色声明为透明色，在 Canvas 上
        画圆角矩形，四个角露出的就是透明色，窗口看起来就是圆角的。
        """
        theme = theme_manager.theme
        accent = theme_manager.accent_color

        self.toolbar = tk.Toplevel(self.root)
        self.toolbar.overrideredirect(True)
        self.toolbar.attributes("-topmost", True)

        transparent = True
        try:
            self.toolbar.config(bg=self._TRANSPARENT_KEY)
            self.toolbar.attributes("-transparentcolor", self._TRANSPARENT_KEY)
        except tk.TclError:
            # 老系统不支持透明色时退回直角外观，功能不受影响
            transparent = False
            self.toolbar.config(bg=theme.border_default)
        outer_bg = self._TRANSPARENT_KEY if transparent else theme.bg_toolbar

        self._toolbar_card = RoundedCard(
            self.toolbar, radius=RADIUS_M, padding=SPACE_SM,
            card_bg=theme.bg_toolbar, outer_bg=outer_bg,
            border=theme.border_default,
        )
        self._toolbar_card.pack()
        row = self._toolbar_card.body

        # (动作, 文案, 图标方法名, 图标颜色)
        specs = [
            ("pin", "钉住", "get_pin", accent),
            ("ocr", "识字", "get_search", theme.success),
            ("copy", "复制", "get_clipboard", accent),
        ]
        for index, (action, label, icon_method, color) in enumerate(specs):
            if index:
                vdivider(row, height=16).pack(side="left", padx=px(row, 2))
            icon = getattr(icons, icon_method)(color, master=row)
            btn = flat_button(
                row, text=f" {label}", image=icon, compound="left",
                command=lambda a=action: self._trigger(a),
                bg=theme.bg_toolbar, fg=theme.text_primary,
                hover_bg=theme.bg_hover, padx=12, pady=3,
            )
            btn._icon_ref = icon
            btn.pack(side="left")

        self._place_toolbar(x, y)

    def _place_toolbar(self, x, y):
        """把工具栏摆到选区右下角，并避让屏幕边缘。

        尺寸必须实测（``fit_to_content``）—— 旧实现里写死了 ``toolbar_w = 220``，
        而实际宽度是 299，导致贴到屏幕右边时工具栏会有一部分跑到屏幕外。
        """
        self.toolbar.update_idletasks()
        w, h = self._toolbar_card.fit_to_content()
        gap = px(self.toolbar, 8)

        tx = x - w            # 右边缘与选区右边缘对齐
        ty = y + gap          # 默认落在选区下方
        if tx < 0:
            tx = 0
        if tx + w > self.screen_width:
            tx = max(0, self.screen_width - w - gap)
        if ty + h > self.screen_height:
            ty = y - h - gap  # 下方放不下就翻到选区上方
        if ty < 0:
            ty = 0
        self.toolbar.geometry(f"+{int(tx)}+{int(ty)}")

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
