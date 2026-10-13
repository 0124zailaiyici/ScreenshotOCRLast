"""自绘控件库。

Tk 没有 ``border-radius``，所有圆角都得用 Canvas 画；``tk.Scrollbar`` 一定带上下箭头，
``ttk.Scrollbar`` 在 Windows 上受原生主题限制、做不出细圆角滑块。这些"原生做不到"的件
集中放在这里，避免每个窗口各写一份。

设计约束
--------
- 所有尺寸参数都走 :func:`ui_theme.px` 换算，保证不同 DPI 下观感一致。
- 颜色一律从 ``theme_manager`` 取，不要在这里写死。
"""

import tkinter as tk

from ui_theme import (
    FONT_BUTTON,
    RADIUS_M,
    SPACE_MD,
    px,
    theme_manager,
)


def round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """在 Canvas 上画圆角矩形，返回 item id。

    用 ``smooth=True`` 的多边形逼近圆角 —— 这是 Tk 里最省事、视觉上也可接受的做法
    （Tk 没有原生的圆角图元）。
    """
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedCard(tk.Frame):
    """圆角卡片容器：Canvas 负责画底与描边，内容放进 ``body``。

    ``body`` 会从卡片边缘内缩 ``padding``。**padding 必须 >= radius**，否则直角的内容
    控件会把圆角盖掉。这个约束在 ``__init__`` 里会被自动修正。
    """

    def __init__(self, master, *, radius=RADIUS_M, padding=SPACE_MD,
                 card_bg=None, outer_bg=None, border=None, **kw):
        """``width=1, height=1`` 是刻意设置的，不要删。

        Tk 的 Canvas 默认请求尺寸是 **570x400**，而 Canvas 的请求尺寸会一路传播到外层
        Frame。于是包着卡片的容器会"虚报"自己要 396px 高，在窗口不够高时把空间吃光，
        排在它后面打包的控件（实测是状态栏）会被压成 0 高度、``winfo_ismapped()`` 变 0。
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
        self._hover = False
        self._drag = None
        self._redraw()

    def _on_press(self, event):
        top, thumb_h = self._thumb_geom
        if thumb_h and top <= event.y <= top + thumb_h:
            self._drag = (event.y, self._first)
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
                font=None, padx=12, pady=6, image=None, compound="left",
                anchor="center", border=None, border_hover=None, **kw):
    """扁平按钮。

    ``tk.Button`` 即使 ``relief="flat"`` 在 Windows 上**仍会画出立体边框**，必须同时
    设置 ``bd=0`` 与 ``highlightthickness=0``；悬停反馈要自己绑 ``<Enter>``/``<Leave>``。

    传 ``border`` 可以给按钮加一圈 1px 描边（用 highlight 环实现，因为 ``bd`` 会带回
    立体感）。次要操作加描边后辨识度明显提高，否则在深色底上灰字会显得像被禁用。

    返回的按钮带一个 ``set_bg(color)`` 方法：外部改底色（例如"已复制"变绿）后，
    悬停离开时会回到**新**底色而不是初始底色。
    """
    theme = theme_manager.theme
    bg = theme.bg_chrome if bg is None else bg
    fg = theme.text_primary if fg is None else fg
    hover_bg = theme.bg_hover if hover_bg is None else hover_bg

    btn = tk.Button(
        master, text=text, command=command, image=image, compound=compound,
        bg=bg, fg=fg, activebackground=hover_bg, activeforeground=fg,
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
            btn.configure(bg=hover_bg)
            if border and border_hover:
                btn.configure(highlightbackground=border_hover,
                              highlightcolor=border_hover)

    def _leave(_event):
        btn.configure(bg=state["bg"])
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
