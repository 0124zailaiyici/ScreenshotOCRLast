"""自绘控件库。

Tk 没有 ``border-radius``，所有圆角都得用 Canvas 画；``tk.Scrollbar`` 一定带上下箭头，
``ttk.Scrollbar`` 在 Windows 上受原生主题限制、做不出细圆角滑块。这些"原生做不到"的件
集中放在这里，避免每个窗口各写一份。

设计约束
--------
- 所有尺寸参数都走 :func:`ui_theme.px` 换算，保证不同 DPI 下观感一致。
- 颜色一律从 ``theme_manager`` 取，不要在这里写死。
"""

import math
import tkinter as tk
from tkinter import font as tkfont

from ui_theme import (
    FONT_BUTTON,
    RADIUS_M,
    SPACE_MD,
    px,
    theme_manager,
)


def round_rect(canvas, x1, y1, x2, y2, r, steps=8, **kwargs):
    """在 Canvas 上画圆角矩形，返回 item id。

    **不要把这里退回 ``create_polygon(..., smooth=True)`` 的写法。**

    Tk 的 ``smooth=True`` 是 B 样条，曲线**不经过**给定的点，圆角量由相邻点的
    间距决定，而不是由我们传进来的 ``r`` 决定。实测（真实渲染后逐像素数）：

        请求半径      左上挖掉   右上   左下   右下
        r= 4            35       18     18      0
        r= 8            36       19     19      1
        r=12            38       21     21      3
        r=20            47       30     30     12

    两个结论：① 圆角深度几乎**不随半径变化**（r 从 4 到 20，左上只从 35 变到 47），
    所以它根本不是"半径 r 的圆角"；② 四个角**互不一致**，右下角基本是直角 ——
    视觉上就是一个"上面圆、下面方"的破窗口。

    改成把四个圆角显式采样成圆弧点、``smooth=False``，形状就是精确的：
    同样实测挖掉量随半径正常增长（r=4/8/12/20 对应 36/45/60/106），四角一致。
    每个角 ``steps+1`` 个点，8 段在这个尺度下已经看不出棱角。
    """
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    if r <= 0:
        return canvas.create_polygon(x1, y1, x2, y1, x2, y2, x1, y2, **kwargs)

    def arc(cx, cy, a0, a1):
        return [(cx + r * math.cos(a0 + (a1 - a0) * i / steps),
                 cy + r * math.sin(a0 + (a1 - a0) * i / steps))
                for i in range(steps + 1)]

    points = []
    points += arc(x1 + r, y1 + r, math.pi, math.pi * 1.5)          # 左上
    points += arc(x2 - r, y1 + r, math.pi * 1.5, math.pi * 2)      # 右上
    points += arc(x2 - r, y2 - r, 0.0, math.pi * 0.5)              # 右下
    points += arc(x1 + r, y2 - r, math.pi * 0.5, math.pi)          # 左下
    return canvas.create_polygon([c for p in points for c in p],
                                 smooth=False, **kwargs)


class RoundedCard(tk.Frame):
    """圆角卡片容器：Canvas 负责画底与描边，内容放进 ``body``。

    ``body`` 会从卡片边缘内缩 ``padding``。**padding 必须 >= radius**，否则直角的内容
    控件会把圆角盖掉。这个约束在 ``__init__`` 里会被自动修正。
    """

    def __init__(self, master, *, radius=RADIUS_M, padding=SPACE_MD,
                 card_bg=None, outer_bg=None, border=None, **kw):
        """``width=1, height=1`` 是刻意设置的，不要删。

        Tk 的 Canvas 默认请求尺寸很大 —— 实测 **382x268**（100% DPI），并且随显示器缩放
        线性放大（150% 缩放下约 573x402）。这个请求尺寸会一路传播到外层 Frame，于是
        包着卡片的容器会"虚报"自己要几百像素高，在窗口不够高时把空间吃光，排在它后面
        打包的控件（实测是状态栏）会被压成 0 高度、``winfo_ismapped()`` 变 0。

        把请求尺寸压到 1x1 后，卡片的实际大小完全由 ``pack(fill=..., expand=...)``
        决定，不再干扰兄弟控件的分配。需要按内容自适应时用 :meth:`fit_to_content`。
        """
        theme = theme_manager.theme
        outer_bg = outer_bg or theme.bg_primary
        card_bg = card_bg or theme.bg_card
        border = border or theme.border_card

        super().__init__(master, bg=outer_bg, bd=0, highlightthickness=0, **kw)

        self._radius = px(self, radius)
        # 内缩量不能小于圆角半径，否则内容会盖住圆角
        self._pad = max(px(self, padding), self._radius)
        self._card_bg = card_bg
        self._outer_bg = outer_bg
        self._border = border

        self.canvas = tk.Canvas(self, bg=outer_bg, bd=0, highlightthickness=0,
                                width=1, height=1)
        self.canvas.pack(fill="both", expand=True)

        self.body = tk.Frame(self.canvas, bg=card_bg, bd=0, highlightthickness=0)
        self._win = self.canvas.create_window(
            self._pad, self._pad, window=self.body, anchor="nw"
        )
        self.canvas.bind("<Configure>", self._on_configure)

    @property
    def padding(self) -> int:
        """内容相对卡片边缘的内缩量（物理像素）。"""
        return self._pad

    def fit_to_content(self):
        """把卡片收缩到刚好包住内容，返回 ``(宽, 高)``。

        默认情况下 Canvas 不参与几何传播，``RoundedCard`` 只能被父容器拉伸（OCR 窗口
        就是这样用的）。浮动工具栏需要反过来——由内容决定窗口多大——所以显式测量一次。
        """
        self.body.update_idletasks()
        w = self.body.winfo_reqwidth() + self._pad * 2
        h = self.body.winfo_reqheight() + self._pad * 2
        self.canvas.configure(width=w, height=h)
        return w, h

    def _on_configure(self, event):
        self.canvas.delete("card_bg")
        # 0.5 偏移让 1px 描边落在像素中心，避免糊成 2px
        round_rect(
            self.canvas, 0.5, 0.5, event.width - 0.5, event.height - 0.5,
            self._radius, fill=self._card_bg, outline=self._border,
            width=1, tags="card_bg",
        )
        self.canvas.tag_lower("card_bg")
        self.canvas.itemconfigure(
            self._win,
            width=max(1, event.width - self._pad * 2),
            height=max(1, event.height - self._pad * 2),
        )


class ThinScrollbar(tk.Canvas):
    """自绘细滚动条：无箭头按钮，滑块是圆角胶囊，内容不满一屏时自动隐藏。

    接法与 ``tk.Scrollbar`` 一致::

        sb = ThinScrollbar(parent, command=text.yview)
        text.configure(yscrollcommand=sb.set)
    """

    def __init__(self, master, *, command=None, thickness=6, thumb_color=None,
                 thumb_hover=None, track_color=None, min_thumb=28, **kw):
        theme = theme_manager.theme
        self._thickness = px(master, thickness)
        track_color = track_color or theme.bg_card

        super().__init__(master, width=self._thickness, bg=track_color,
                         bd=0, highlightthickness=0, **kw)

        self._command = command
        self._thumb_color = thumb_color or theme.sb_thumb
        self._thumb_hover = thumb_hover or theme.sb_thumb_hover
        self._min_thumb = px(self, min_thumb)
        self._first = 0.0
        self._last = 1.0
        self._drag = None
        self._hover = False
        self._thumb_geom = (0, 0)

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ------------------------------------------------------------ 对外接口

    def attach(self, widget):
        """把滚动条接到一个支持 ``yview`` / ``yscrollcommand`` 的控件上。"""
        widget.configure(yscrollcommand=self.set)
        self._command = widget.yview
        return self

    def set(self, first, last):
        """由目标控件的 ``yscrollcommand`` 调用。"""
        try:
            self._first = float(first)
            self._last = float(last)
        except (TypeError, ValueError):
            return
        self._redraw()

    # ------------------------------------------------------------ 绘制

    def _visible_fraction(self) -> float:
        return max(0.0, min(1.0, self._last - self._first))

    def _redraw(self):
        self.delete("all")
        height = self.winfo_height()
        if height <= 1:
            return
        visible = self._visible_fraction()
        if visible >= 0.999:
            self._thumb_geom = (0, 0)
            return  # 内容没超出一屏，不画滑块

        thumb_h = max(self._min_thumb, int(height * visible))
        travel = max(1, height - thumb_h)
        denom = max(1e-9, 1.0 - visible)
        top = int(travel * (self._first / denom))
        top = max(0, min(travel, top))

        color = self._thumb_hover if self._hover else self._thumb_color
        w = self._thickness
        round_rect(self, 0, top, w, top + thumb_h, w / 2.0,
                   fill=color, outline=color)
        self._thumb_geom = (top, thumb_h)

    # ------------------------------------------------------------ 交互

    def _on_enter(self, _event):
        self._hover = True
        self._redraw()

    def _on_leave(self, _event):
        # 注意：**不要**在这里清 ``_drag``。滚动条只有 thickness 像素宽（150% DPI 下 9px），
        # 垂直拖动时指针稍一横向漂移就会离开控件、触发 <Leave>，清掉 _drag 会让拖动中断。
        # 拖动只由 <ButtonRelease-1> 结束（拖动期间已 grab，见 _on_press）。
        self._hover = False
        self._redraw()

    def _on_press(self, event):
        top, thumb_h = self._thumb_geom
        if thumb_h and top <= event.y <= top + thumb_h:
            self._drag = (event.y, self._first)
            # 抓住指针：否则指针一离开这几像素宽的区域，<B1-Motion> 就不再送到这里，
            # 拖动会卡住（要等指针回到条上才继续）。grab 之后事件全部路由到本控件，
            # 拖到窗口任意位置都跟手。
            try:
                self.grab_set()
            except tk.TclError:
                pass          # 控件尚未映射等情况下 grab 会失败，退化为原来的行为
        else:
            self._drag = None
            self._page_to(event.y)

    def _on_motion(self, event):
        if not self._drag or not self._command:
            return
        y0, first0 = self._drag
        height = self.winfo_height()
        visible = self._visible_fraction()
        thumb_h = max(self._min_thumb, int(height * visible))
        travel = max(1, height - thumb_h)
        delta = (event.y - y0) / travel * max(0.0, 1.0 - visible)
        self._move_to(first0 + delta)

    def _on_release(self, _event):
        if self._drag is not None:
            try:
                self.grab_release()
            except tk.TclError:
                pass
        self._drag = None

    def _page_to(self, y):
        """点击轨道空白处：让滑块中心跳到点击位置。"""
        height = max(1, self.winfo_height())
        visible = self._visible_fraction()
        self._move_to(y / height - visible / 2.0)

    def _move_to(self, first):
        if not self._command:
            return
        visible = self._visible_fraction()
        first = max(0.0, min(max(0.0, 1.0 - visible), first))
        self._command("moveto", first)


def flat_button(master, text="", *, command=None, bg=None, fg=None, hover_bg=None,
                hover_fg=None, font=None, padx=12, pady=6, image=None, compound="left",
                anchor="center", border=None, border_hover=None, **kw):
    """扁平按钮。

    ``tk.Button`` 即使 ``relief="flat"`` 在 Windows 上**仍会画出立体边框**，必须同时
    设置 ``bd=0`` 与 ``highlightthickness=0``；悬停反馈要自己绑 ``<Enter>``/``<Leave>``。

    传 ``border`` 可以给按钮加一圈 1px 描边（用 highlight 环实现，因为 ``bd`` 会带回
    立体感）。次要操作加描边后辨识度明显提高，否则在深色底上灰字会显得像被禁用。

    传 ``hover_fg`` 可以让悬停时前景色也变化 —— 关闭按钮（✕）这类纯文字按钮只换底色
    不够明显。

    返回的按钮带一个 ``set_bg(color)`` 方法：外部改底色（例如"已复制"变绿）后，
    悬停离开时会回到**新**底色而不是初始底色。
    """
    theme = theme_manager.theme
    bg = theme.bg_chrome if bg is None else bg
    fg = theme.text_primary if fg is None else fg
    hover_bg = theme.bg_hover if hover_bg is None else hover_bg
    hover_fg = fg if hover_fg is None else hover_fg

    btn = tk.Button(
        master, text=text, command=command, image=image, compound=compound,
        bg=bg, fg=fg, activebackground=hover_bg, activeforeground=hover_fg,
        disabledforeground=theme.text_disabled,
        relief="flat", bd=0, highlightthickness=0, takefocus=0,
        font=font or FONT_BUTTON,
        padx=px(master, padx), pady=px(master, pady),
        cursor="hand2", anchor=anchor, **kw
    )
    state = {"bg": bg}

    if border:
        width = px(master, 1)
        btn.configure(highlightthickness=width, highlightbackground=border,
                      highlightcolor=border)

    def _enter(_event):
        if str(btn["state"]) != "disabled":
            btn.configure(bg=hover_bg, fg=hover_fg)
            if border and border_hover:
                btn.configure(highlightbackground=border_hover,
                              highlightcolor=border_hover)

    def _leave(_event):
        btn.configure(bg=state["bg"], fg=fg)
        if border:
            btn.configure(highlightbackground=border, highlightcolor=border)

    def set_bg(color):
        state["bg"] = color
        btn.configure(bg=color)

    btn.bind("<Enter>", _enter, add="+")
    btn.bind("<Leave>", _leave, add="+")
    btn.set_bg = set_bg
    return btn


def vdivider(master, *, color=None, height=18, width=1):
    """工具栏里的竖向分隔线。"""
    theme = theme_manager.theme
    return tk.Frame(master, bg=color or theme.divider,
                    width=px(master, width), height=px(master, height))


def hdivider(master, *, color=None, thickness=1):
    """横向分隔线。"""
    theme = theme_manager.theme
    return tk.Frame(master, bg=color or theme.divider,
                    height=px(master, thickness))


class SegmentedControl(tk.Frame):
    """分段选择器（例如"中文 | EN"）。

    选中项用强调色实心填充，未选中项在悬停时轻微提亮。
    """

    def __init__(self, master, options, *, on_change=None, font=None, bg=None, **kw):
        theme = theme_manager.theme
        outer_bg = bg or theme.bg_primary
        super().__init__(master, bg=outer_bg, bd=0, highlightthickness=0, **kw)
        self._on_change = on_change
        self._value = options[0] if options else None
        self._buttons = {}
        self._disabled = False

        pad = px(self, 2)
        inner = tk.Frame(self, bg=theme.bg_hover, bd=0, highlightthickness=0)
        inner.pack(padx=0, pady=0)
        self._inner = inner

        for opt in options:
            btn = tk.Button(
                inner, text=opt, command=lambda o=opt: self.set(o),
                font=font or FONT_BUTTON, relief="flat", bd=0,
                highlightthickness=0, takefocus=0, cursor="hand2",
                padx=px(inner, 10), pady=px(inner, 4),
                bg=theme.bg_hover, fg=theme.text_secondary,
                activebackground=theme.bg_pressed, activeforeground=theme.text_primary,
            )
            btn.pack(side="left", padx=pad, pady=pad)
            btn.bind("<Enter>", lambda _e, b=btn: self._hover(b, True), add="+")
            btn.bind("<Leave>", lambda _e, b=btn: self._hover(b, False), add="+")
            self._buttons[opt] = btn

        self._refresh()

    @property
    def value(self):
        return self._value

    def set(self, value, notify=True):
        if value not in self._buttons or value == self._value:
            return
        self._value = value
        self._refresh()
        if notify and self._on_change:
            self._on_change(value)

    def set_disabled(self, disabled: bool):
        """整体禁用（例如翻译请求进行中），避免用户连点叠加请求。"""
        self._disabled = bool(disabled)
        for btn in self._buttons.values():
            btn.configure(state="disabled" if disabled else "normal",
                          cursor="arrow" if disabled else "hand2")
        self._refresh()

    def _hover(self, btn, entering):
        if self._disabled or self._buttons.get(self._value) is btn:
            return
        theme = theme_manager.theme
        btn.configure(bg=theme.bg_pressed if entering else theme.bg_hover)

    def _refresh(self):
        theme = theme_manager.theme
        for opt, btn in self._buttons.items():
            if opt == self._value:
                btn.configure(bg=theme_manager.accent, fg=theme_manager.accent_fg,
                              activebackground=theme_manager.accent_hover,
                              activeforeground=theme_manager.accent_fg)
            else:
                btn.configure(bg=theme.bg_hover, fg=theme.text_secondary,
                              activebackground=theme.bg_pressed,
                              activeforeground=theme.text_primary)
        if self._disabled:
            for btn in self._buttons.values():
                btn.configure(bg=theme.bg_hover, fg=theme.text_disabled)


class DragGrip(tk.Canvas):
    """拖动暗示手柄：几根短横线。

    无边框窗口（``overrideredirect``）没有标题栏，需要在操作栏上放一个"这里可以拖"
    的视觉提示 —— 否则用户根本不知道窗口能拖。拖动本身由窗口自己绑事件，
    这个控件只负责"看起来像能拖"。

    ``width`` / ``height`` 是物理像素，所以尺寸全部过 :func:`ui_theme.px`。
    """

    def __init__(self, master, *, bg=None, color=None, lines=3, **kw):
        theme = theme_manager.theme
        bg = bg or theme.bg_chrome
        color = color or theme.text_tertiary

        line_w = px(master, 13)
        thickness = max(1, px(master, 1.5))
        gap = px(master, 3)
        height = lines * thickness + (lines - 1) * gap

        super().__init__(master, width=line_w, height=height, bg=bg,
                         bd=0, highlightthickness=0, **kw)
        for i in range(lines):
            y = i * (thickness + gap) + thickness / 2.0
            self.create_line(0, y, line_w, y, fill=color, width=thickness)


class ContextMenu:
    """自绘的右键菜单。

    为什么不用 ``tk.Menu``
    ----------------------
    Tk 在 Windows 上自绘的弹出菜单不受系统深色主题控制，会弹出一个浅灰方块 ——
    在这个从头到尾都是自绘（圆角卡片、细滚动条、无边框窗口）的界面里，它会是
    唯一一个不搭的东西。所以这里同样用 Canvas 画。

    菜单项
    ------
    ``items`` 是 ``(文案, 回调)`` 的序列；元素为 ``None`` 表示一条分隔线。
    回调在**菜单关闭之后**才执行，避免回调里又弹窗/销毁窗口时和 grab 打架。

    关闭时机
    --------
    1. 点中某一项；
    2. 在菜单矩形之外点击（``grab_set`` 会把应用内的点击重定向到本窗口，
       所以即便点在别的窗口上，事件也会送到这里、坐标落在矩形外）；
    3. 按 Esc；
    4. 焦点离开（点到别的程序去了 —— 本地 grab 管不到应用外，靠这条兜底）。

    第 4 条要求菜单拿到过焦点，所以 ``popup`` 里会 ``focus_force()`` 一次。
    """

    #: 抠圆角用的透明色键，必须是界面上绝不会出现的颜色（与截图工具栏同一个值）
    TRANSPARENT_KEY = "#FF00FE"

    def __init__(self, master, items, *, font=None):
        self.master = master
        self.items = list(items)
        self.font = font or FONT_BUTTON

        self._win = None
        self._canvas = None
        self._rows = []
        self._hover = -1
        self._closed = True

    # ---- 布局 ----

    def _measure(self):
        """算出行高、总尺寸，并记录每一行的 y 区间。

        文案宽度用真实字体度量（``tkfont.Font.measure``），不是猜的 —— 中文和
        拉丁字符宽度差很多，按字符数估算会得到长短不一的菜单。
        """
        theme = theme_manager.theme
        font = tkfont.Font(root=self.master, font=self.font)
        pad_x = px(self.master, 14)
        row_pad = px(self.master, 7)
        outer_pad = px(self.master, 5)
        line_h = font.metrics("linespace")
        sep_h = px(self.master, 7)

        rows = []
        y = outer_pad
        widest = 0
        for item in self.items:
            if item is None:
                rows.append({"kind": "sep", "y": y, "h": sep_h})
                y += sep_h
                continue
            label, command = item
            widest = max(widest, font.measure(label))
            rows.append({"kind": "item", "label": label, "command": command,
                         "y": y, "h": line_h + 2 * row_pad})
            y += line_h + 2 * row_pad

        self._rows = rows
        self._font = font
        self._pad_x = pad_x
        self._row_pad = row_pad
        self._width = widest + 2 * pad_x
        self._height = y + outer_pad
        self._radius = RADIUS_M
        self._bg = theme.bg_card
        self._border = theme.border_card
        self._hover_bg = theme.bg_hover
        self._divider = theme.divider
        self._fg = theme.text_primary

    def _redraw(self):
        c = self._canvas
        c.delete("all")
        w, h = self._width, self._height
        round_rect(c, 0, 0, w - 1, h - 1, self._radius,
                   fill=self._bg, outline=self._border)

        inset = px(self.master, 3)
        for index, row in enumerate(self._rows):
            if row["kind"] == "sep":
                y = row["y"] + row["h"] / 2
                c.create_line(self._pad_x, y, w - self._pad_x, y,
                              fill=self._divider)
                continue
            if index == self._hover:
                round_rect(c, inset, row["y"] + px(self.master, 1),
                           w - inset, row["y"] + row["h"] - px(self.master, 1),
                           max(1, self._radius - 2), fill=self._hover_bg)
            c.create_text(self._pad_x, row["y"] + row["h"] / 2, anchor="w",
                          text=row["label"], fill=self._fg, font=self.font)

    def _row_at(self, y):
        for index, row in enumerate(self._rows):
            if row["kind"] == "sep":
                continue
            if row["y"] <= y < row["y"] + row["h"]:
                return index
        return -1

    # ---- 交互 ----

    def _on_motion(self, event):
        index = self._row_at(event.y)
        if index != self._hover:
            self._hover = index
            self._redraw()

    def _on_click(self, event):
        index = self._row_at(event.y)
        # 点在菜单矩形之外也算"选中了菜单本身"，此时应当关闭而不是执行任何一项
        if index < 0:
            self.close()
            return
        command = self._rows[index].get("command")
        self.close()
        if command:
            command()

    def _on_escape(self, _event):
        self.close()

    def _on_focus_out(self, _event):
        self.close()

    # ---- 显示 / 关闭 ----

    def popup(self, x, y):
        """在屏幕坐标 ``(x, y)`` 处弹出。超出屏幕时会往回收。"""
        self._measure()

        win = tk.Toplevel(self.master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        transparent = True
        try:
            win.attributes("-transparentcolor", self.TRANSPARENT_KEY)
        except tk.TclError:
            transparent = False

        bg = self.TRANSPARENT_KEY if transparent else self._bg
        win.configure(bg=bg)
        canvas = tk.Canvas(win, width=self._width, height=self._height,
                           bg=bg, bd=0, highlightthickness=0)
        canvas.pack()
        self._win = win
        self._canvas = canvas

        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = max(0, min(x, screen_w - self._width))
        y = max(0, min(y, screen_h - self._height))

        # 先隐藏、一次性设好尺寸+位置、再显示 —— overrideredirect 窗口在映射前
        # 设置的位置会被丢弃（同 ocr_window / screenshot_overlay 的处理）。
        win.withdraw()
        win.geometry(f"{self._width}x{self._height}+{x}+{y}")
        win.deiconify()

        self._redraw()
        self._closed = False

        # grab 让应用内的点击都回到本窗口（包括点在别的窗口上的），
        # focus_force 让点到别的程序时能收到 FocusOut 兜底。
        win.bind("<Motion>", self._on_motion)
        win.bind("<Button-1>", self._on_click)
        win.bind("<Escape>", self._on_escape)
        win.bind("<FocusOut>", self._on_focus_out)
        try:
            win.grab_set()
        except tk.TclError:
            pass
        try:
            win.focus_force()
        except tk.TclError:
            pass
        return self

    def close(self):
        if self._closed:
            return
        self._closed = True
        win = self._win
        self._win = None
        self._canvas = None
        if win is None:
            return
        try:
            win.grab_release()
        except tk.TclError:
            pass
        try:
            win.destroy()
        except tk.TclError:
            pass

    @property
    def is_open(self):
        return not self._closed


def show_context_menu(master, items, x, y, *, font=None):
    """一次性弹出一个右键菜单，返回菜单对象（已打开）。"""
    return ContextMenu(master, items, font=font).popup(x, y)

