import tkinter as tk
from PIL import Image, ImageTk
import random

class PinWindow:
    """钉住浮窗：无边框置顶，支持滚轮缩放和鼠标拖拽"""
    
    # 静态变量，用于追踪所有活跃的钉住窗口，以便进行重叠检测
    active_windows = []

    def __init__(self, image, coords=None, master=None):
        """
        :param image: 截图图片
        :param coords: 截图时的原始坐标 (x1, y1, x2, y2)
        :param master: 父窗口
        """
        self.original_image = image
        self.coords = coords
        self.current_scale = 1.0
        
        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()
            
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 1.0)
        
        # 显示图片的 Label
        self.label = tk.Label(self.root, bd=0, bg="white")
        self.label.pack()
        
        # 初始显示
        self._update_display(first_time=True)
        
        # 记录到活跃窗口列表
        PinWindow.active_windows.append(self)
        
        # 绑定事件
        self.label.bind("<ButtonPress-1>", self._start_drag)
        self.label.bind("<B1-Motion>", self._do_drag)
        self.label.bind("<MouseWheel>", self._on_zoom)
        self.root.bind("<Button-3>", self._on_close)  # 右键关闭
        self.root.bind("<Escape>", self._on_close)

        # 拖拽相关
        self._drag_start_x = 0
        self._drag_start_y = 0

    def _on_close(self, event=None):
        """关闭窗口并从活跃列表中移除"""
        if self in PinWindow.active_windows:
            PinWindow.active_windows.remove(self)
        self.root.destroy()

    def _update_display(self, first_time=False):
        """根据缩放比例更新图片显示"""
        w, h = self.original_image.size
        new_w = int(w * self.current_scale)
        new_h = int(h * self.current_scale)
        
        # 防止缩放过小
        if new_w < 20 or new_h < 20: return
            
        resized_img = self.original_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized_img)
        self.label.config(image=self.tk_image)
        
        if first_time and self.coords:
            # 初始定位：基于原始坐标，加入微调和重叠检测
            self._apply_initial_position(new_w, new_h)
        else:
            # 缩放时保持位置
            curr_x = self.root.winfo_x()
            curr_y = self.root.winfo_y()
            self.root.geometry(f"{new_w}x{new_h}+{curr_x}+{curr_y}")

    def _apply_initial_position(self, width, height):
        """
        应用初始位置算法：
        1. 保持在原坐标 ±10px 范围内
        2. 边界检测：确保不超出屏幕
        3. 重叠检测：避开已有的钉住窗口
        """
        x1, y1, x2, y2 = self.coords
        
        # 1. 基础位置 (原位置) + 轻微偏移 (±10px)
        target_x = x1 + random.randint(-10, 10)
        target_y = y1 + random.randint(-10, 10)
        
        # 2. 边界检测
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        target_x = max(0, min(target_x, screen_w - width))
        target_y = max(0, min(target_y, screen_h - height))
        
        # 3. 重叠检测与微调 (简单策略：如果重叠，则向右下方偏移)
        max_attempts = 5
        for _ in range(max_attempts):
            overlapping = False
            for win in PinWindow.active_windows:
                if win == self: continue
                
                # 获取其他窗口的位置
                other_x = win.root.winfo_x()
                other_y = win.root.winfo_y()
                other_w = win.root.winfo_width()
                other_h = win.root.winfo_height()
                
                # 经典的 AABB 重叠检测
                if (target_x < other_x + other_w and
                    target_x + width > other_x and
                    target_y < other_y + other_h and
                    target_y + height > other_y):
                    overlapping = True
                    break
            
            if overlapping:
                # 发现重叠，尝试向右下方移动 20px
                target_x += 20
                target_y += 20
                # 再次边界检测
                target_x = max(0, min(target_x, screen_w - width))
                target_y = max(0, min(target_y, screen_h - height))
            else:
                break
        
        self.root.geometry(f"{width}x{height}+{target_x}+{target_y}")

    def _start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _do_drag(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_start_x)
        y = self.root.winfo_y() + (event.y - self._drag_start_y)
        self.root.geometry(f"+{x}+{y}")

    def _on_zoom(self, event):
        """滚轮缩放"""
        if event.delta > 0:
            self.current_scale *= 1.1
        else:
            self.current_scale *= 0.9
        self._update_display()

# 导出函数
def show_pin_window(image, coords=None, master=None):
    return PinWindow(image, coords=coords, master=master)
