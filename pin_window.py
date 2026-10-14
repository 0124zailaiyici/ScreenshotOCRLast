import tkinter as tk
from PIL import Image, ImageTk
import random
import os
import uuid
import ctypes
from config import config_manager
from ui_theme import theme_manager
from ui_widgets import show_context_menu

class PinWindow:
    """钉住浮窗：无边框置顶，支持滚轮缩放、鼠标拖拽、右键菜单"""
    
    # 静态变量，用于追踪所有活跃的钉住窗口
    active_windows = []

    def __init__(self, image, coords=None, master=None, pin_id=None, scale=1.0,
                 notify=None):
        """
        :param image: 截图图片
        :param coords: 截图时的原始坐标 (x1, y1, x2, y2)
        :param master: 父窗口
        :param pin_id: 持久化 ID
        :param scale: 初始缩放比例
        :param notify: 可选的 ``notify(标题, 正文)`` 回调，用于操作反馈
        """
        self.original_image = image
        self.coords = coords
        self.current_scale = scale
        self.pin_id = pin_id or str(uuid.uuid4())
        self.notify = notify
        self._menu = None
        
        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()
            
        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )

        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 1.0)
        self.root.config(bg=theme_manager.theme.border_default)

        # 显示图片的 Label（主题表面色背景 + 1px 内边距露边框色）
        self.label = tk.Label(self.root, bd=0, bg=theme_manager.theme.bg_surface)
        self.label.pack(padx=1, pady=1)
        
        # 初始显示
        self._update_display(first_time=True)
        
        # 记录到活跃窗口列表
        PinWindow.active_windows.append(self)
        
        # 绑定事件
        self.label.bind("<ButtonPress-1>", self._start_drag)
        self.label.bind("<B1-Motion>", self._do_drag)
        self.label.bind("<MouseWheel>", self._on_zoom)
        # 右键弹菜单，不再直接关闭 —— 旧行为下钉住的图既没法复制也没法重新
        # 识别，只能重新截一次。关闭收进菜单里。
        self.root.bind("<Button-3>", self._on_context_menu)
        self.root.bind("<Escape>", self._on_close)
        
        # 强制置顶定时器 (防止被其他 TOPMOST 窗口覆盖)
        self._topmost_job = None
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
                # 菜单打开时不要抢置顶：这条定时器每 2 秒把本窗口抬到
                # HWND_TOPMOST，会把刚弹出来的菜单盖住。让菜单自己待在最上面。
                if self._menu is not None and self._menu.is_open:
                    self._topmost_job = self.root.after(500, self._ensure_topmost)
                    return
                # 使用 Win32 API 强制置顶
                hwnd = self.root.winfo_id()
                # 某些情况下 winfo_id 返回的是容器 ID，需要获取父级句柄
                parent_hwnd = ctypes.windll.user32.GetParent(hwnd)
                target_hwnd = parent_hwnd if parent_hwnd else hwnd
                ctypes.windll.user32.SetWindowPos(target_hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
                self._topmost_job = self.root.after(2000, self._ensure_topmost)
        except Exception:
            pass

    def _save_state(self):
        """将窗口状态保存到配置"""
        if not self.pin_id: return
        
        # 确保目录存在
        save_dir = os.path.join(config_manager.data_dir, "pinned")
        os.makedirs(save_dir, exist_ok=True)
        
        img_path = os.path.join(save_dir, f"{self.pin_id}.png")
        if not os.path.exists(img_path):
            self.original_image.save(img_path)
            
        item_data = {
            "id": self.pin_id,
            "path": img_path,
            "coords": self.coords,
            "scale": self.current_scale,
            "pos": [self.root.winfo_x(), self.root.winfo_y()]
        }

        pinned_items = config_manager.get_pinned_items()
        new_items = [i for i in pinned_items if i.get("id") != self.pin_id]
        new_items.append(item_data)
        config_manager.set_pinned_items(new_items)

    def _on_close(self, event=None):
        """关闭窗口并从活跃列表中移除，同时清理持久化数据"""
        if self in PinWindow.active_windows:
            PinWindow.active_windows.remove(self)

        # 菜单可能正开着并持有 grab，先关掉再销毁窗口
        if self._menu is not None:
            try:
                self._menu.close()
            except Exception:
                pass
            self._menu = None

        # 取消置顶定时器，避免窗口销毁后回调仍被反复触发
        if self._topmost_job is not None:
            try:
                self.root.after_cancel(self._topmost_job)
            except Exception:
                pass
            self._topmost_job = None

        # 清理配置（线程安全）
        pinned_items = config_manager.get_pinned_items()
        new_items = [i for i in pinned_items if i.get("id") != self.pin_id]
        config_manager.set_pinned_items(new_items)
        
        # 清理文件
        img_path = os.path.join(config_manager.data_dir, "pinned", f"{self.pin_id}.png")
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
        # 显式绑定到本窗口所属的 Tk root，避免依赖全局默认 root 导致句柄错配
        self.tk_image = ImageTk.PhotoImage(resized_img, master=self.root)
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
        for item in config_manager.get_pinned_items():
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

    # ---- 右键菜单 ----

    def _on_context_menu(self, event):
        """在鼠标位置弹出右键菜单。

        刻意只放三条：复制图片、识别文字、取消钉住。它们对应钉住之后真正会想做
        的事 —— 钉住是为了"等会儿还要用"，那就得能把它拿走（复制）、或者把它
        里面的字拿出来（识别）。
        """
        # 已经开着就不要再叠一个（连点右键会叠出多层菜单）
        if self._menu is not None and self._menu.is_open:
            return

        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )
        items = [
            ("复制图片", self._copy_image),
            ("识别文字…", self._re_ocr),
            None,  # 分隔线：把「取消钉住」这个不可逆操作和上面两条隔开
            ("取消钉住", self._on_close),
        ]
        self._menu = show_context_menu(self.root, items,
                                       event.x_root, event.y_root)

    def _copy_image(self):
        """把**原始分辨率**的截图复制到剪贴板。

        用 ``original_image`` 而不是 ``label`` 上正在显示的那张：后者是滚轮缩放
        过的，直接复制出去画质会掉。
        """
        from clipboard_manager import clipboard_manager

        ok = clipboard_manager.copy_image(self.original_image)
        if self.notify:
            try:
                if ok:
                    self.notify("复制成功", "图片已复制到剪贴板")
                else:
                    self.notify("复制失败", "无法写入剪贴板")
            except Exception:
                pass

    def _re_ocr(self):
        """用原始截图重新识别，打开识字窗口。

        钉住窗口一直留着 ``original_image``（原始分辨率），所以不需要重新截屏。
        """
        from ocr_window import show_ocr_window

        try:
            # 挂在钉住窗口的**父**窗口下，而不是钉住窗口本身 —— 否则关掉钉住会
            # 顺手把识字窗口一起销毁。
            parent = self.root.master or self.root
            show_ocr_window(self.original_image, coords=self.coords, master=parent)
        except Exception as e:
            print(f"从钉住窗口打开识字窗口失败: {e}")
            if self.notify:
                try:
                    self.notify("识别失败", str(e))
                except Exception:
                    pass

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

def show_pin_window(image, coords=None, master=None, pin_id=None, scale=1.0,
                    notify=None):
    return PinWindow(image, coords=coords, master=master, pin_id=pin_id,
                     scale=scale, notify=notify)

def restore_pinned_windows(master=None, notify=None):
    """从配置中恢复所有钉住的窗口"""
    for item in config_manager.get_pinned_items():
        try:
            if os.path.exists(item["path"]):
                img = Image.open(item["path"])
                show_pin_window(
                    img,
                    coords=item.get("coords"),
                    master=master,
                    pin_id=item["id"],
                    scale=item.get("scale", 1.0),
                    notify=notify
                )
        except Exception as e:
            print(f"恢复钉住窗口失败: {e}")
