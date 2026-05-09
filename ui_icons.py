from PIL import Image, ImageDraw, ImageTk


class IconProvider:
    """缓存 PIL 生成的图标 PhotoImage，防止 Tkinter GC 回收"""

    def __init__(self, size=24):
        self._size = size
        self._cache = {}

    def _make_key(self, icon_type, color):
        return (icon_type, color)

    def get_pin(self, color):
        key = self._make_key("pin", color)
        if key not in self._cache:
            self._cache[key] = self._draw_pin(color)
        return self._cache[key]

    def get_search(self, color):
        key = self._make_key("search", color)
        if key not in self._cache:
            self._cache[key] = self._draw_search(color)
        return self._cache[key]

    def get_clipboard(self, color):
        key = self._make_key("clipboard", color)
        if key not in self._cache:
            self._cache[key] = self._draw_clipboard(color)
        return self._cache[key]

    def get_checkmark(self, color="#107C10"):
        key = self._make_key("checkmark", color)
        if key not in self._cache:
            self._cache[key] = self._draw_checkmark(color)
        return self._cache[key]

    def clear_cache(self):
        self._cache.clear()

    # ---- 内部绘制方法（48x48 双倍尺寸 -> 缩放到 _size） ----

    def _render(self, draw_func):
        """在 2x 画布上绘制，缩放到目标尺寸"""
        s = self._size * 2
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw_func(draw, s)
        if self._size != s:
            img = img.resize((self._size, self._size), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _draw_pin(self, color):
        def draw(dc, s):
            # 图钉头部（圆）
            dc.ellipse([s * 0.3, s * 0.08, s * 0.7, s * 0.48], fill=color)
            # 高光反光
            dc.ellipse([s * 0.35, s * 0.14, s * 0.48, s * 0.28], fill="white")
            # 针身
            dc.line([(s * 0.5, s * 0.44), (s * 0.5, s * 0.76)], fill=color, width=max(2, s // 12))
            # 针尖
            dc.ellipse([s * 0.44, s * 0.72, s * 0.56, s * 0.84], fill=color)
        return self._render(draw)

    def _draw_search(self, color):
        def draw(dc, s):
            # 镜片（大圆）
            dc.ellipse([s * 0.14, s * 0.14, s * 0.68, s * 0.68], outline=color, width=max(2, s // 12))
            # 手柄（45 度线）
            dc.line([(s * 0.6, s * 0.6), (s * 0.84, s * 0.84)], fill=color, width=max(2, s // 10))
        return self._render(draw)

    def _draw_clipboard(self, color):
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
        return self._render(draw)

    def _draw_checkmark(self, color):
        def draw(dc, s):
            w = max(2, s // 10)
            # 勾号两笔：左下到中，中到右上
            dc.line([(s * 0.18, s * 0.52), (s * 0.4, s * 0.76)], fill=color, width=w)
            dc.line([(s * 0.4, s * 0.76), (s * 0.82, s * 0.24)], fill=color, width=w)
        return self._render(draw)


icons = IconProvider()
