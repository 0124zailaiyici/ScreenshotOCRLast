import tkinter as tk
from PIL import Image, ImageTk, ImageGrab
from config import config_manager
from clipboard_manager import clipboard_manager

class ScreenshotOverlay:
    """全屏截图覆盖层：处理区域选择和浮动工具栏"""

    def __init__(self, on_select_callback, master=None):
        """
        :param on_select_callback: 选区完成后的回调 (action, image, region)
        :param master: 父窗口 (Tk 实例)
        """
        self.on_select = on_select_callback
        # 如果没有传入 master，则创建新的 Tk 实例
        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()
        
        # 设置 DPI 感知，确保坐标匹配
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # 获取系统主题配置
        self.accent_color = config_manager.get_system_accent_color()
        self.is_dark = config_manager.is_dark_mode()
        
        # 窗口基本设置：无边框、置顶、全屏
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        # 1. 背景适配优化：根据系统深色/浅色模式动态调整遮罩色值和透明度
        overlay_color = "black" if self.is_dark else "#F3F3F3"
        overlay_alpha = 0.4 if self.is_dark else 0.3
        self.root.attributes("-alpha", overlay_alpha)
        
        self.root.config(cursor="cross")
        
        # 获取全屏尺寸
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{self.screen_width}x{self.screen_height}+0+0")

        # 画布：绘制遮罩和选区
        self.canvas = tk.Canvas(self.root, cursor="cross", bg=overlay_color, 
                               highlightthickness=0, width=self.screen_width, height=self.screen_height)
        self.canvas.pack(fill="both", expand=True)

        # 状态变量
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.toolbar = None
        self.selection_img = None
        self.selection_coords = None

        # 绑定事件
        self.root.bind("<ButtonPress-1>", self._on_button_press)
        self.root.bind("<B1-Motion>", self._on_mouse_drag)
        self.root.bind("<ButtonRelease-1>", self._on_button_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def _on_button_press(self, event):
        """鼠标按下：开始选取"""
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.canvas.delete(self.rect_bg_id) # 删除外层描边
        if self.toolbar:
            self.toolbar.destroy()
            self.toolbar = None
            
        # 1. 选区框优化：采用“双层描边”方案，确保在任何背景下均清晰可见
        # 外层：白色实线 (作为背景)
        self.rect_bg_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, 
                                                       outline="white", width=3)
        # 内层：系统主题色虚线 (核心指示)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, 
                                                    outline=self.accent_color, width=1, dash=(4, 4))

    def _on_mouse_drag(self, event):
        """鼠标拖拽：更新矩形大小"""
        self.canvas.coords(self.rect_bg_id, self.start_x, self.start_y, event.x, event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_button_release(self, event):
        """鼠标松开：完成选取并显示工具栏"""
        end_x, end_y = event.x, event.y
        x1, y1 = min(self.start_x, end_x), min(self.start_y, end_y)
        x2, y2 = max(self.start_x, end_x), max(self.start_y, end_y)
        
        if x2 - x1 < 5 or y2 - y1 < 5:  # 选区太小忽略
            return

        self.selection_coords = (x1, y1, x2, y2)
        # 截图保存到内存
        self.selection_img = ImageGrab.grab(bbox=(x1, y1, x2, y2), all_screens=True)
        
        # 只有在配置明确开启且用户没有点击其他按钮时，才自动复制？
        # 为了解决 Bug 1，我们这里不自动复制，改为在 _trigger 中根据 action 处理，
        # 或者在主流程中处理。
            
        self._show_toolbar(x2, y2)

    def _show_toolbar(self, x, y):
        """在选区右下角显示工具栏"""
        self.toolbar = tk.Toplevel(self.root)
        self.toolbar.overrideredirect(True)
        self.toolbar.attributes("-topmost", True)
        
        bg_color = "#FFFFFF" if not self.is_dark else "#2B2B2B"
        text_color = "#333333" if not self.is_dark else "#FFFFFF"
        hover_color = "#F0F0F0" if not self.is_dark else "#3D3D3D"
        
        self.toolbar.config(bg=bg_color, padx=5, pady=5)
        
        # 避让边缘逻辑
        if x + 150 > self.screen_width: x = self.screen_width - 160
        if y + 50 > self.screen_height: y = y - 60
        self.toolbar.geometry(f"+{x-120}+{y+5}")

        # 2. 功能图标色彩优化：基于 UI.md 色彩系统，改为常驻有色设计
        # 钉住 - 主色 (Blue)
        # 识字 - 成功色 (Green)
        # 复制 - 主色 (Blue)
        btn_base = {"bg": bg_color, "activebackground": hover_color, 
                    "font": ("Segoe UI", 10), "relief": "flat", "padx": 10}

        tk.Button(self.toolbar, text="📌 钉住", command=lambda: self._trigger("pin"), 
                  fg="#0078D4", activeforeground="#005A9E", **btn_base).pack(side="left")
        
        tk.Button(self.toolbar, text="🔍 识字", command=lambda: self._trigger("ocr"), 
                  fg="#107C10", activeforeground="#0B5A0B", **btn_base).pack(side="left")
        
        tk.Button(self.toolbar, text="📋 复制", command=lambda: self._trigger("copy"), 
                  fg="#0078D4", activeforeground="#005A9E", **btn_base).pack(side="left")

    def _trigger(self, action):
        """执行动作并关闭覆盖层"""
        if self.on_select:
            self.on_select(action, self.selection_img, self.selection_coords)
        
        # 安全销毁窗口：检查窗口是否仍然存在
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except tk.TclError:
            pass # 窗口可能已经被父窗口销毁

    def run(self):
        self.root.mainloop()

# 导出函数
def select_region(callback, master=None):
    overlay = ScreenshotOverlay(callback, master=master)
    if not master:
        overlay.run()
