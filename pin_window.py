import tkinter as tk
from PIL import Image, ImageTk
import random
import os
import uuid
import ctypes
from config import config_manager

class PinWindow:
    """钉住浮窗：无边框置顶，支持滚轮缩放和鼠标拖拽"""
    
    # 静态变量，用于追踪所有活跃的钉住窗口
    active_windows = []

    def __init__(self, image, coords=None, master=None, pin_id=None, scale=1.0):
        """
        :param image: 截图图片
        :param coords: 截图时的原始坐标 (x1, y1, x2, y2)
        :param master: 父窗口
        :param pin_id: 持久化 ID
        :param scale: 初始缩放比例
        """
        self.original_image = image
        self.coords = coords
        self.current_scale = scale
        self.pin_id = pin_id or str(uuid.uuid4())
        
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
        
        # 强制置顶定时器 (防止被其他 TOPMOST 窗口覆盖)
        self._ensure_topmost()

        # 拖拽相关
        self._drag_start_x = 0
        self._drag_start_y = 0
        
        # 保存持久化状态
        self._save_state()

    def _ensure_topmost(self):
        """强制窗口置顶"""
        try:
            if self.root.winfo_exists():
                # 使用 Win32 API 强制置顶
                hwnd = self.root.winfo_id()
                # 某些情况下 winfo_id 返回的是容器 ID，需要获取父级句柄
                parent_hwnd = ctypes.windll.user32.GetParent(hwnd)
                target_hwnd = parent_hwnd if parent_hwnd else hwnd
                ctypes.windll.user32.SetWindowPos(target_hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
                self.root.after(2000, self._ensure_topmost)
        except Exception:
            pass

    def _save_state(self):
        """将窗口状态保存到配置"""
        if not self.pin_id: return
        
        # 确保目录存在
        save_dir = os.path.join(config_manager.base_path, "assets", "pinned")
        os.makedirs(save_dir, exist_ok=True)
        
        img_path = os.path.join(save_dir, f"{self.pin_id}.png")
        if not os.path.exists(img_path):
            self.original_image.save(img_path)
            
        pinned_items = config_manager.get("pinned_items") or []
        # 更新或添加
        item_data = {
            "id": self.pin_id,
            "path": img_path,
            "coords": self.coords,
            "scale": self.current_scale,
            "pos": [self.root.winfo_x(), self.root.winfo_y()]
        }
        
        # 过滤掉旧的同 ID 项
        new_items = [i for i in pinned_items if i.get("id") != self.pin_id]
        new_items.append(item_data)
        config_manager.set("pinned_items", new_items)

    def _on_close(self, event=None):
        """关闭窗口并从活跃列表中移除，同时清理持久化数据"""
        if self in PinWindow.active_windows:
            PinWindow.active_windows.remove(self)
            
        # 清理配置
        pinned_items = config_manager.get("pinned_items") or []
        new_items = [i for i in pinned_items if i.get("id") != self.pin_id]
        config_manager.set("pinned_items", new_items)
        
        # 清理文件
        img_path = os.path.join(config_manager.base_path, "assets", "pinned", f"{self.pin_id}.png")
        if os.path.exists(img_path):
            try: os.remove(img_path)
            except: pass
            
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
        
        if first_time:
            self._apply_initial_position(new_w, new_h)
        else:
            # 缩放时保持中心位置
            curr_x = self.root.winfo_x()
            curr_y = self.root.winfo_y()
            self.root.geometry(f"{new_w}x{new_h}+{curr_x}+{curr_y}")
            self._save_state()

    def _apply_initial_position(self, width, height):
        # 1. 如果是恢复的窗口，直接使用保存的位置
        pinned_items = config_manager.get("pinned_items") or []
        for item in pinned_items:
            if item.get("id") == self.pin_id and "pos" in item:
                self.root.geometry(f"{width}x{height}+{item['pos'][0]}+{item['pos'][1]}")
                return

        # 2. 否则按坐标计算
        if not self.coords:
            self.root.geometry(f"{width}x{height}+100+100")
            return
            
        x1, y1, x2, y2 = self.coords
        target_x = x1 + random.randint(-10, 10)
        target_y = y1 + random.randint(-10, 10)
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        target_x = max(0, min(target_x, screen_w - width))
        target_y = max(0, min(target_y, screen_h - height))
        
        # 重叠检测
        for _ in range(5):
            overlapping = False
            for win in PinWindow.active_windows:
                if win == self: continue
                other_x, other_y = win.root.winfo_x(), win.root.winfo_y()
                other_w, other_h = win.root.winfo_width(), win.root.winfo_height()
                if (target_x < other_x + other_w and target_x + width > other_x and
                    target_y < other_y + other_h and target_y + height > other_y):
                    overlapping = True
                    break
            if overlapping:
                target_x += 20
                target_y += 20
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
        self._save_state()

    def _on_zoom(self, event):
        if event.delta > 0: self.current_scale *= 1.1
        else: self.current_scale *= 0.9
        self._update_display()

def show_pin_window(image, coords=None, master=None, pin_id=None, scale=1.0):
    return PinWindow(image, coords=coords, master=master, pin_id=pin_id, scale=scale)

def restore_pinned_windows(master=None):
    """从配置中恢复所有钉住的窗口"""
    items = config_manager.get("pinned_items") or []
    for item in items:
        try:
            if os.path.exists(item["path"]):
                img = Image.open(item["path"])
                show_pin_window(
                    img, 
                    coords=item.get("coords"), 
                    master=master, 
                    pin_id=item["id"],
                    scale=item.get("scale", 1.0)
                )
        except Exception as e:
            print(f"恢复钉住窗口失败: {e}")
