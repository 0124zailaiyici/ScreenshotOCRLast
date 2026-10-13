import tkinter

from PIL import Image, ImageDraw, ImageTk


class IconProvider:
    """缓存 PIL 生成的图标 PhotoImage，防止 Tkinter GC 回收。

    PhotoImage 隶属于创建它的 Tk 解释器：把属于解释器 A 的句柄配置给
    解释器 B 的控件，会抛 ``TclError: image "pyimageN" doesn't exist``。

    这里**不能**用 ``tkinter._default_root`` 判断「root 是否变了」——
    该变量只在它为 None 时才被新 root 覆盖，所以「第一个 root 仍存活时
    又创建了第二个 root」这一情形下它不会变化，缓存也就不会失效。
    因此改为以**调用方控件所属的 root**（``master._root()``）为准。
    """

    def __init__(self, size=24):
        self._size = size
        self._cache = {}
        self._cache_root = None

    def _make_key(self, icon_type, color):
        return (icon_type, color)

    def _sync(self, master):
        """返回 master 所属的 Tk root；与缓存所属 root 不一致时清空缓存"""
        root = master._root() if master is not None else tkinter._default_root
        if root is None:
            raise RuntimeError("创建图标前必须先存在 Tk root")
        if root is not self._cache_root:
            self._cache.clear()
            self._cache_root = root
        return root

    def get_pin(self, color, master=None):
        root = self._sync(master)
        key = self._make_key("pin", color)
        if key not in self._cache:
            self._cache[key] = self._draw_pin(color, root)
        return self._cache[key]

    def get_search(self, color, master=None):
        root = self._sync(master)
        key = self._make_key("search", color)
        if key not in self._cache:
            self._cache[key] = self._draw_search(color, root)
        return self._cache[key]

    def get_clipboard(self, color, master=None):
        root = self._sync(master)
        key = self._make_key("clipboard", color)
        if key not in self._cache:
            self._cache[key] = self._draw_clipboard(color, root)
        return self._cache[key]

    def get_checkmark(self, color="#107C10", master=None):
        root = self._sync(master)
        key = self._make_key("checkmark", color)
        if key not in self._cache:
            self._cache[key] = self._draw_checkmark(color, root)
        return self._cache[key]

    def get_refresh(self, color, master=None):
        root = self._sync(master)
        key = self._make_key("refresh", color)
        if key not in self._cache:
            self._cache[key] = self._draw_refresh(color, root)
        return self._cache[key]

    def clear_cache(self):
        self._cache.clear()
        self._cache_root = None

    # ---- 内部绘制方法（48x48 双倍尺寸 -> 缩放到 _size） ----

    @staticmethod
    def _line_round(dc, p1, p2, color, width):
        """带圆头的线段。

        PIL 的 ``line`` 是平头（butt cap），端点显得生硬；在两个端点各补一个圆
        就得到圆头效果，和现代图标集的观感一致。
        """
        dc.line([p1, p2], fill=color, width=width)
        r = width / 2.0
        for (x, y) in (p1, p2):
            dc.ellipse([x - r, y - r, x + r, y + r], fill=color)

    def _render(self, draw_func, master):
        """在 2x 画布上绘制，缩放到目标尺寸，并绑定到指定的 Tk root"""
        s = self._size * 2
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw_func(draw, s)
        if self._size != s:
            img = img.resize((self._size, self._size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img, master=master)

    def _draw_pin(self, color, master):
        def draw(dc, s):
            # 钉帽（圆）
            dc.ellipse([s * 0.30, s * 0.10, s * 0.70, s * 0.50], fill=color)
            # 高光反光
            dc.ellipse([s * 0.36, s * 0.16, s * 0.48, s * 0.30], fill="white")
            # 钉身（上宽下窄的梯形）—— 没有这一层的话，圆头 + 细针看起来像气球
            dc.polygon(
                [(s * 0.24, s * 0.50), (s * 0.76, s * 0.50),
                 (s * 0.60, s * 0.68), (s * 0.40, s * 0.68)],
                fill=color,
            )
            # 针（圆头）
            self._line_round(dc, (s * 0.50, s * 0.66), (s * 0.50, s * 0.90),
                             color, max(2, s // 14))
        return self._render(draw, master)

    def _draw_search(self, color, master):
        def draw(dc, s):
            w = max(2, s // 12)
            # 镜片（大圆）
            dc.ellipse([s * 0.14, s * 0.14, s * 0.68, s * 0.68],
                       outline=color, width=w)
            # 手柄（45 度线，圆头）
            self._line_round(dc, (s * 0.60, s * 0.60), (s * 0.84, s * 0.84),
                             color, max(2, s // 10))
        return self._render(draw, master)

    def _draw_clipboard(self, color, master):
        def draw(dc, s):
            # 主体（圆角矩形）
            dc.rounded_rectangle(
                [s * 0.2, s * 0.3, s * 0.8, s * 0.9],
                radius=s * 0.08, outline=color, width=max(2, s // 12)
            )
            # 顶部夹子
            dc.rounded_rectangle(
                [s * 0.32, s * 0.12, s * 0.68, s * 0.36],
                radius=s * 0.06, outline=color, width=max(2, s // 12)
            )
            # 内部横线
            for y_ratio in [0.5, 0.62, 0.74]:
                y = int(s * y_ratio)
                dc.line([(s * 0.3, y), (s * 0.7, y)], fill=color, width=max(2, s // 16))
        return self._render(draw, master)

    def _draw_checkmark(self, color, master):
        def draw(dc, s):
            w = max(2, s // 10)
            # 勾号两笔：左下到中，中到右上（圆头）
            self._line_round(dc, (s * 0.18, s * 0.52), (s * 0.40, s * 0.76), color, w)
            self._line_round(dc, (s * 0.40, s * 0.76), (s * 0.82, s * 0.24), color, w)
        return self._render(draw, master)

    def _draw_refresh(self, color, master):
        """刷新/重新识别：右上留缺口的圆弧 + 切向箭头。"""
        import math

        def draw(dc, s):
            w = max(2, s // 11)
            pad = s * 0.20
            cx = cy = s / 2.0
            r = (s - pad * 2) / 2.0
            start_deg, end_deg = 318.0, 238.0

            # 圆弧：从 318° 顺时针画到 238°，缺口落在正上方偏右
            dc.arc([pad, pad, s - pad, s - pad],
                   start=start_deg, end=end_deg, fill=color, width=w)

            # 箭头：贴在圆弧起点，方向取该点的顺时针切向
            th = math.radians(start_deg)
            x = cx + r * math.cos(th)
            y = cy + r * math.sin(th)
            ux, uy = -math.sin(th), math.cos(th)      # 单位切向
            nx, ny = -uy, ux                          # 单位法向
            length = s * 0.21
            half = s * 0.10
            tip = (x + ux * length * 0.45, y + uy * length * 0.45)
            b1 = (x - ux * length * 0.55 + nx * half,
                  y - uy * length * 0.55 + ny * half)
            b2 = (x - ux * length * 0.55 - nx * half,
                  y - uy * length * 0.55 - ny * half)
            dc.polygon([tip, b1, b2], fill=color)

        return self._render(draw, master)


icons = IconProvider()
