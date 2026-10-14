"""OCR 识别窗口。

布局（自上而下）
----------------
1. **操作栏** —— 主操作「复制」用强调色实心，次要操作「重新识别」用描边式；
   右侧是「翻译至 [原文|中文|EN]」分段选择器。
2. **文本卡片** —— 圆角卡片包住正文；Tk 的 ``tk.Scrollbar`` 一定带上下箭头，
   所以滚动条用 :class:`ui_widgets.ThinScrollbar` 自绘。
3. **状态栏** —— 字数、识别耗时、当前显示的是原文还是译文。

线程模型（沿用全局约定，不要改）
--------------------------------
OCR 在后台线程跑，只往 ``self.result`` 这个普通 dict 里写；主线程用 ``after`` 轮询。
**后台线程绝不能碰任何 Tkinter 对象。**
"""

import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

from clipboard_manager import clipboard_manager
from config import config_manager
from ocr_engine import OcrError, create_ocr_engine
from translator import translator
from ui_icons import icons
from ui_theme import (
    FONT_BUTTON,
    FONT_BUTTON_SM,
    FONT_META,
    FONT_TEXT,
    RADIUS_M,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    COLOR_SUCCESS,
    dpi_scale,
    px,
    theme_manager,
)
from ui_widgets import (
    DragGrip,
    RoundedCard,
    SegmentedControl,
    ThinScrollbar,
    flat_button,
)

# 正文行距：在字体自身 linespace 之上再补的比例。
# Tk 的 Text 没有 line-height，只能用 spacing* 模拟，而这三个参数语义不同：
#   spacing1 = 逻辑行**上方**留白      spacing3 = 逻辑行**下方**留白
#   spacing2 = 同一逻辑行**折行之间**的留白
# OCR 结果里绝大多数是硬换行（各自是独立逻辑行），但长行也会折行。若只设 spacing1/3，
# 折行处会紧贴上一行、而换行处很松，同一段文字里出现两种行距。
# 因此统一成：spacing1=0（避免首行上方多出空隙）、spacing2=spacing3=extra，
# 这样"逻辑行边界"和"折行"得到的间距完全一致。
TEXT_LINE_EXTRA_RATIO = 0.30

# 窗口尺寸的设计稿尺寸（逻辑像素），实际会按 DPI 缩放。
WIN_MIN_W, WIN_MAX_W = 300, 600
WIN_MIN_H, WIN_MAX_H = 200, 500
WIN_CHROME_H = 80          # 除图片外要额外留出的高度（操作栏 + 状态栏 + 边距）
WIN_BAR_H = 46             # 顶部操作栏高度（它同时兼任拖动条）

# 抠窗口圆角用的透明色键。必须是界面上绝不会出现的颜色。
# 与截图工具栏（screenshot_overlay._TRANSPARENT_KEY）同一套做法。
_TRANSPARENT_KEY = "#FF00FE"

# 分段选择器的显示文案 -> 内部语言代码
LANG_LABELS = {"原文": "raw", "中文": "zh", "EN": "en"}


class OcrWindow:
    """OCR 识别窗口：主题化界面、图标按钮、即时翻译交互"""

    def __init__(self, image, coords=None, master=None):
        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )

        self.image = image
        self.coords = coords
        self.img_width, self.img_height = image.size

        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()

        self.root.title("OCR 识别")
        # 标题栏不显示（无边框），但任务栏 / Alt+Tab 里仍然靠它标识窗口，别删。

        self._scale = dpi_scale(self.root)
        self._make_frameless()

        self.result = {"done": False, "text": "", "error": None, "error_kind": None}
        self.translations = {}
        self.current_lang = "raw"

        self._started_at = time.monotonic()
        self._elapsed = None
        self._polling = False

        self._setup_ui()

        # 尺寸必须在 UI 建好之后才算：操作栏的宽度是**实测**出来的，不是猜的。
        # （旧实现把下限写死成 300 逻辑像素，操作栏里多一个 ✕ 之后就不准了。）
        self.root.update_idletasks()
        win_w, win_h = self._compute_window_size()

        # 先隐藏、一次性设好尺寸+位置、再显示。
        #
        # 不能先 geometry("WxH") 再 geometry("+X+Y")：**overrideredirect 窗口在映射前
        # 设置的位置会被丢弃**。实测构造完 geometry() 是 '1x1+0+0'，映射后变成
        # '624x323+0+0' —— 尺寸生效了、位置没了，窗口永远出现在屏幕左上角。
        # （无边框之前的版本没这个问题，是加 overrideredirect 时引入的。）
        self.root.withdraw()
        self.root.geometry(f"{win_w}x{win_h}+{self._target_x(win_w)}+{self._target_y(win_h)}")
        self.root.deiconify()

        self.root.attributes("-topmost", True)
        # 无边框窗口默认拿不到键盘焦点 —— 不强制抢一次的话，
        # Text 里的 Ctrl+C / 拖选全都失效，用户会以为程序卡了。
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

        self._set_text("正在识别…")
        self._set_status("正在识别…")

        self._polling = True
        threading.Thread(target=self._do_ocr, daemon=True).start()
        self._poll_result()

    # ------------------------------------------------------------------ 无边框窗口

    def _make_frameless(self):
        """去掉原生标题栏，改用自绘操作栏（兼任拖动条 + 关闭按钮）。

        圆角靠 ``-transparentcolor`` 抠：把一个绝不使用的颜色声明为透明色，圆角卡片
        四个角露出的就是它，窗口看起来就是圆角的。与截图工具栏同一套做法。
        老系统不支持透明色时退回直角外观，功能不受影响。
        """
        self.root.overrideredirect(True)
        self._transparent = True
        try:
            self.root.config(bg=_TRANSPARENT_KEY)
            self.root.attributes("-transparentcolor", _TRANSPARENT_KEY)
        except tk.TclError:
            self._transparent = False
        self._outer_bg = (_TRANSPARENT_KEY if self._transparent
                          else theme_manager.theme.border_default)

    def _on_close(self):
        """自绘的 ✕：没有原生标题栏，关闭只能自己接。

        ``main._do_screenshot`` 给 ``win.root`` 绑了 ``<Destroy>`` 来结束截图会话，
        所以这里只要销毁窗口，锁和会话容器都会被正确回收。
        """
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ 拖动

    def _start_drag(self, event):
        self._drag_origin = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _on_drag(self, event):
        if not self._drag_origin:
            return
        dx, dy = self._drag_origin
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    # ------------------------------------------------------------------ 几何

    def _compute_window_size(self):
        """按 DPI 换算窗口尺寸。

        截图坐标与图片尺寸都是**物理像素**，而设计稿上的 300/600/200/500 是逻辑像素。
        不做换算的话，在 150% 缩放的屏幕上窗口会显得比设计稿小一圈，加上按点缩放的
        字号后会非常拥挤。

        宽度下限取**实测的操作栏宽度**，而不是写死的常数：操作栏里放了
        「拖动手柄 + 复制 + 重新识别 + 原文|中文|EN + ✕」，写死的下限一旦小于实际
        需求，按钮就会被 packer 挤成 1x1（踩过一次：状态栏整条消失）。
        """
        s = self._scale
        max_w = int(WIN_MAX_W * s)
        max_h = int(WIN_MAX_H * s)
        min_h = int(WIN_MIN_H * s)
        chrome_h = int(WIN_CHROME_H * s)

        # 圆角外壳会给内容加一圈内缩。上限是**窗口整体**的尺寸，外壳也算在里面 ——
        # 否则窗口会比设计稿大出一圈（实测 600 → 616），"不超过 600 逻辑像素"这个
        # 约定就破了。
        inset = self.shell.padding * 2 if getattr(self, "shell", None) else 0

        content_min_w = max(int(WIN_MIN_W * s), self._bar_required_width())
        content_max_w = max(content_min_w, max_w - inset)
        content_w = max(content_min_w, min(self.img_width, content_max_w))

        content_max_h = max(min_h, max_h - inset)
        content_h = max(min_h, min(self.img_height + chrome_h, content_max_h))

        return content_w + inset, content_h + inset

    def _bar_required_width(self):
        """操作栏真正需要的宽度（物理像素）。

        **不能用 ``self.bar.winfo_reqwidth()``** —— ``bar`` 设了 ``pack_propagate(False)``
        （为了固定高度），于是它不再按子控件报告宽度，实测恒为 **1**。必须问里面那层
        会传播尺寸的 ``row``，再加上 ``row`` 两侧的 padx。

        这个下限是真的会生效的：操作栏里是「手柄 + 复制 + 重新识别 + 原文|中文|EN + ✕」，
        实测需要 641 物理像素。下限给小了 packer 会把最后打包的分段控件挤小
        （实测 245 → 180，文字被裁），这就是之前踩过的"空间被超额订阅"。
        """
        row = getattr(self, "_bar_row", None)
        if row is None:
            return 0
        return row.winfo_reqwidth() + px(row, SPACE_SM) * 2

    def _target_x(self, win_w):
        """窗口左上角的 x：左边缘与选区对齐，横向只收拢、不翻转。"""
        screen_w = self.root.winfo_screenwidth()
        if not self.coords:
            return max(0, (screen_w - win_w) // 2)
        x1 = self.coords[0]
        return max(0, min(x1, screen_w - win_w))

    def _target_y(self, win_h):
        """窗口左上角的 y：默认落在选区**正下方**，下方放不下才翻到上方。

        旧实现摆在选区**右侧**（``target_x = x2 + gap``）。窗口最宽 900 物理像素，
        一靠屏幕右边就整块翻到选区左侧 —— 右边缘贴着选区、左边缘却甩出去近千像素，
        用户的感觉是"窗口跑到别处去了"。改成向下展开：视线自然往下走，横向也不跳。
        """
        screen_h = self.root.winfo_screenheight()
        if not self.coords:
            return max(0, (screen_h - win_h) // 2)
        _x1, y1, _x2, y2 = self.coords
        gap = px(self.root, 10)
        target_y = y2 + gap
        if target_y + win_h > screen_h:
            target_y = y1 - win_h - gap
        return max(0, min(target_y, screen_h - win_h))

    # ------------------------------------------------------------------ 界面

    def _setup_ui(self):
        theme = theme_manager.theme
        root = self.root

        # ---------------- 圆角外壳 ----------------
        # 无边框窗口本身是方的；四个角靠 -transparentcolor 抠出来（见 _make_frameless）。
        # 内容放进 card_bg = bg_chrome 的外壳里，于是四周露出一圈操作栏同色的"边框"，
        # 顶部操作栏和它自然接上，看不出接缝。
        self.shell = RoundedCard(
            root, radius=RADIUS_M, padding=SPACE_XS,
            card_bg=theme.bg_chrome, outer_bg=self._outer_bg,
            border=theme.border_default,
        )
        self.shell.pack(fill="both", expand=True)
        shell = self.shell.body

        # ---------------- 顶部操作栏（兼任拖动条） ----------------
        bar = tk.Frame(shell, bg=theme.bg_chrome, height=px(root, WIN_BAR_H))
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        self.bar = bar

        row = tk.Frame(bar, bg=theme.bg_chrome)
        row.pack(fill="both", expand=True, padx=px(root, SPACE_SM))
        self._bar_row = row      # _bar_required_width() 要问它（bar 自己恒报 1）

        # 拖动手柄：整条操作栏都能拖，手柄只是给用户"这里可以拖"的暗示。
        # 无边框窗口没有标题栏，不给拖动手段的话窗口就钉死在原地了。
        self.grip = DragGrip(row, bg=theme.bg_chrome,
                             color=theme.text_tertiary)
        self.grip.pack(side="left", padx=(0, px(root, SPACE_XS)))

        # 复制：主操作，强调色实心
        clip_icon = icons.get_clipboard(theme_manager.accent_fg, master=bar)
        self.btn_copy = flat_button(
            row, text=" 复制", image=clip_icon, compound="left",
            command=self._copy_all,
            bg=theme_manager.accent, fg=theme_manager.accent_fg,
            hover_bg=theme_manager.accent_hover,
            padx=14, pady=5,
        )
        self.btn_copy._icon_ref = clip_icon
        self.btn_copy.pack(side="left")

        # 重新识别：次要操作。必须加描边 —— 深色底上纯灰字会显得像被禁用了。
        refresh_icon = icons.get_refresh(theme.text_secondary, master=bar)
        self.btn_retry = flat_button(
            row, text=" 重新识别", image=refresh_icon, compound="left",
            command=self._retry_ocr,
            bg=theme.bg_chrome, fg=theme.text_primary,
            hover_bg=theme.bg_hover,
            border=theme.border_default, border_hover=theme.text_tertiary,
            padx=12, pady=5,
        )
        self.btn_retry._icon_ref = refresh_icon
        self.btn_retry.pack(side="left", padx=(px(root, SPACE_XS), 0))

        # 关闭：没有原生标题栏，必须自己提供一个
        self.btn_close = flat_button(
            row, text="✕", command=self._on_close,
            bg=theme.bg_chrome, fg=theme.text_secondary,
            hover_bg=theme.bg_hover, hover_fg=theme.text_primary,
            padx=10, pady=5,
        )
        self.btn_close.pack(side="right")

        # 翻译目标：原文 / 中文 / EN
        # 注意：这里**不放**"翻译至"标签 —— 620 物理像素（约 413 逻辑像素）的窗口宽度
        # 放不下"复制 + 重新识别 + 标签 + 三段选择器"，实测标签会被 packer 挤成 1x1。
        # 三个分段（原文/中文/EN）本身已经说明了用途。
        self.lang_seg = SegmentedControl(
            row, list(LANG_LABELS.keys()),
            on_change=self._on_lang_change, font=FONT_BUTTON, bg=theme.bg_chrome,
        )
        self.lang_seg.pack(side="right", padx=(0, px(root, SPACE_XS)))

        # 整条操作栏（含手柄和空白处）都能拖动窗口。
        # 只绑在 bar / row / grip 上 —— 绑到按钮上会抢走点击。
        self._drag_origin = None
        for widget in (bar, row, self.grip):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)

        # ---------------- 状态栏 ----------------
        # 固定高度的"外框"先于会 expand 的内容区打包 —— 这是 Tk packer 的惯用法：
        # 空间不够时按调用顺序分配，排在最后的控件可能一个像素都分不到。
        #
        # 但**顺序本身不是根因**。真正的坑在 RoundedCard：Tk 的 Canvas 默认请求尺寸很大
        # （实测 382x268 @100% DPI，随缩放线性放大；150% 下约 573x402），会一路传播上来
        # 让内容区虚报几百像素高。窗口不够高时（实测 620x419），
        # bar(75) + content(396) + status(42) = 513 已经超出窗口，最后打包的状态栏就被
        # 压成 0 高度、winfo_ismapped() 变 0。已在 RoundedCard 里把 Canvas 的请求尺寸
        # 压到 1x1；这里再保持"先固定、后弹性"的顺序作为双保险。
        status = tk.Frame(shell, bg=theme.bg_status, height=px(root, 28))
        status.pack(side="bottom", fill="x")
        status.pack_propagate(False)

        self.lbl_status = tk.Label(
            status, text="", bg=theme.bg_status, fg=theme.text_tertiary,
            font=FONT_META, anchor="w",
        )
        self.lbl_status.pack(side="left", fill="both", expand=True,
                             padx=px(root, SPACE_MD + 2))

        self.lbl_view = tk.Label(
            status, text="", bg=theme.bg_status, fg=theme.text_tertiary,
            font=FONT_META, anchor="e",
        )
        self.lbl_view.pack(side="right", padx=px(root, SPACE_MD + 2))

        # ---------------- 文本卡片 ----------------
        content = tk.Frame(shell, bg=theme.bg_primary)
        content.pack(side="top", fill="both", expand=True,
                     padx=px(root, SPACE_MD), pady=px(root, SPACE_MD))

        self.card = RoundedCard(
            content, radius=RADIUS_M, padding=SPACE_MD,
            card_bg=theme.bg_card, outer_bg=theme.bg_primary,
            border=theme.border_card,
        )
        self.card.pack(fill="both", expand=True)

        body = self.card.body
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.text_area = tk.Text(
            body, font=FONT_TEXT, wrap=tk.WORD,
            bg=theme.bg_card, fg=theme.text_primary,
            insertbackground=theme_manager.accent_text,
            selectbackground=theme_manager.accent_soft,
            selectforeground=theme.text_primary,
            relief="flat", bd=0, highlightthickness=0, takefocus=0,
            padx=px(body, SPACE_XS), pady=px(body, 2),
            cursor="xterm",
            **self._line_spacing(),
        )
        self.text_area.grid(row=0, column=0, sticky="nsew")
        self.text_area.tag_configure("error", foreground=theme.error)

        self.scrollbar = ThinScrollbar(
            body, thickness=6, track_color=theme.bg_card,
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(px(body, SPACE_XS), 0))
        self.scrollbar.attach(self.text_area)

    def _line_spacing(self):
        """把行距撑到「linespace + 30%」。

        Tk 的 Text 没有 line-height 属性，行距只能靠 spacing1/2/3 模拟。三者的语义
        见模块顶部注释 —— 关键是**折行与硬换行必须得到同样的间距**，否则同一段文字里
        会出现两种行距。
        """
        try:
            linespace = tkfont.Font(
                family=FONT_TEXT[0], size=FONT_TEXT[1]
            ).metrics("linespace")
        except Exception:
            return {}
        extra = int(linespace * TEXT_LINE_EXTRA_RATIO)
        if extra <= 0:
            return {}
        return {"spacing1": 0, "spacing2": extra, "spacing3": extra}

    # ------------------------------------------------------------------ 文本与状态

    def _set_text(self, text, tag=None):
        self.text_area.delete("1.0", tk.END)
        if text:
            self.text_area.insert(tk.END, text, tag or ())
        self.text_area.yview_moveto(0.0)

    def _set_status(self, text, view=None):
        self.lbl_status.config(text=text)
        self.lbl_view.config(text=view if view is not None else "")

    def _update_status(self):
        """识别完成后刷新状态栏：字数 + 耗时 + 当前显示的是哪种文本。"""
        text = self.result.get("text") or ""
        chars = len("".join(text.split()))
        parts = [f"{chars} 字"]
        if self._elapsed is not None:
            parts.append(f"识别耗时 {self._elapsed:.2f}s")
        view = {"raw": "原文", "zh": "中文", "en": "EN"}.get(self.current_lang, "")
        self._set_status(" · ".join(parts), view)

    # ------------------------------------------------------------------ OCR

    def _do_ocr(self):
        """后台线程：只写 self.result，绝不碰 Tkinter。"""
        started = time.monotonic()
        try:
            engine = create_ocr_engine(config_manager.get("ocr_backend"))
            if not engine.is_available():
                self.result["error"] = "Tesseract 未安装或不在环境变量中"
                self.result["error_kind"] = "not_found"
                self.result["done"] = True
                return

            text = engine.recognize(self.image)
            self.result["text"] = text
            self.result["elapsed"] = time.monotonic() - started
            self.result["done"] = True
        except OcrError as e:
            self.result["error"] = str(e)
            self.result["error_kind"] = e.kind
            self.result["done"] = True
        except Exception as e:
            self.result["error"] = str(e)
            self.result["error_kind"] = "other"
            self.result["done"] = True

    def _retry_ocr(self):
        """重新识别同一张图（识别错了不用重新截图）。"""
        self.result.update(done=False, text="", error=None, error_kind=None, elapsed=None)
        self.translations.clear()
        self.current_lang = "raw"
        self._elapsed = None
        self.lang_seg.set("原文", notify=False)
        self._set_text("正在识别…")
        self._set_status("正在识别…")

        threading.Thread(target=self._do_ocr, daemon=True).start()
        self._resume_polling()

    def _resume_polling(self):
        """确保只有一个轮询链在跑，避免重试时叠加出多个。"""
        if self._polling:
            return
        self._polling = True
        self.root.after(100, self._poll_result)

    def _poll_result(self):
        if not self.root.winfo_exists():
            self._polling = False
            return

        if not self.result["done"]:
            self.root.after(100, self._poll_result)
            return

        self._polling = False

        if self.result["error"]:
            self._show_error()
            return

        self._elapsed = self.result.get("elapsed")
        self.current_lang = "raw"
        self._set_text(self.result["text"])
        self._update_status()

    def _show_error(self):
        theme = theme_manager.theme
        error_msg = self.result["error"]
        kind = self.result.get("error_kind") or "other"

        if kind == "not_found":
            hint = (
                "原因：系统未找到 Tesseract 引擎。\n"
                "解决办法：\n"
                "1. 前往 https://github.com/UB-Mannheim/tesseract/wiki 下载并安装。\n"
                "2. 若已安装，请在下方对话框中手动指定 tesseract.exe 路径。"
            )
        elif kind == "lang_pack":
            hint = (
                "原因：缺少识别语言包。\n"
                "解决办法：\n"
                "1. 重新运行 Tesseract 安装程序，勾选所需语言数据（中文需勾选 Chinese）。\n"
                "2. 或把对应的 .traineddata 文件放入 tessdata 目录。"
            )
        else:
            hint = "请检查 Tesseract 安装与配置后重试。"

        self._set_text(f"识别失败: {error_msg}\n\n{hint}", tag="error")
        self._set_status("识别失败")

        # 只有确实找不到引擎时才引导用户重新指定路径，
        # 否则（例如缺语言包）弹路径选择框会误导用户。
        if kind != "not_found":
            return

        if messagebox.askyesno(
            "Tesseract 路径错误",
            f"{error_msg}\n是否现在手动指定 tesseract.exe 路径？"
        ):
            path = filedialog.askopenfilename(
                title="选择 tesseract.exe",
                filetypes=[("Executable", "*.exe")]
            )
            if path:
                config_manager.set("tesseract_path", path)
                self.result.update(done=False, error=None, error_kind=None)
                self._set_text("正在识别…")
                self._set_status("正在识别…")
                threading.Thread(target=self._do_ocr, daemon=True).start()
                self._resume_polling()

    # ------------------------------------------------------------------ 复制

    def _copy_all(self):
        text = self.text_area.get("1.0", tk.END).strip()
        if not text or text == "正在识别…" or not self.result.get("text"):
            return

        if clipboard_manager.copy_text(text):
            ck_icon = icons.get_checkmark("#FFFFFF", master=self.btn_copy)
            self.btn_copy.config(image=ck_icon, text=" 已复制")
            self.btn_copy.set_bg(COLOR_SUCCESS)
            self.btn_copy._icon_ref = ck_icon
            self.root.after(1500, self._restore_copy_button)

    def _restore_copy_button(self):
        clip_icon = icons.get_clipboard(theme_manager.accent_fg, master=self.btn_copy)
        self.btn_copy.config(image=clip_icon, text=" 复制")
        self.btn_copy.set_bg(theme_manager.accent)
        self.btn_copy._icon_ref = clip_icon

    # ------------------------------------------------------------------ 翻译

    def _on_lang_change(self, label):
        lang = LANG_LABELS.get(label, "raw")
        if lang == "raw":
            self.current_lang = "raw"
            self._set_text(self.result.get("text") or "")
            self._update_status()
            return
        self._trigger_translate(lang)

    def _sync_lang_ui(self):
        for label, lang in LANG_LABELS.items():
            if lang == self.current_lang:
                self.lang_seg.set(label, notify=False)
                return

    def _trigger_translate(self, target):
        if not self.result["done"] or self.result["error"]:
            self._sync_lang_ui()
            return
        original_text = self.result["text"]
        if not original_text.strip():
            self._sync_lang_ui()
            return
        if self.current_lang == target:
            return
        if target in self.translations:
            self._update_text_area(self.translations[target], target)
            return

        self.lang_seg.set_disabled(True)

        def _on_success(res):
            self.root.after(0, lambda: self._handle_translate_success(res, target))

        def _on_error(err):
            self.root.after(0, lambda: self._handle_translate_error(err, target, original_text))

        translator.translate_async(
            original_text, _on_success,
            error_callback=_on_error, to_lang=target
        )

    def _handle_translate_success(self, res, target):
        self.translations[target] = res
        self.lang_seg.set_disabled(False)
        self._update_text_area(res, target)

    def _handle_translate_error(self, err, target, original_text):
        self.lang_seg.set_disabled(False)
        is_same_lang_error = any(
            msg in err.lower() for msg in [
                "target and source languages are the same",
                "same language", "should not be same", "identical"
            ]
        )
        if is_same_lang_error:
            hint = f"[原文已是{'中文' if target == 'zh' else '英文'}，无需翻译]\n\n{original_text}"
            self.translations[target] = hint
            self._update_text_area(hint, target)
        else:
            # 翻译失败：把分段控件退回实际显示的文本，不要让它停在失败的目标语言上
            self._sync_lang_ui()
            messagebox.showerror("翻译失败", err)

    def _update_text_area(self, text, lang):
        self.current_lang = lang
        self._set_text(text)
        self._sync_lang_ui()
        self._update_status()


def show_ocr_window(image, coords=None, master=None):
    return OcrWindow(image, coords=coords, master=master)
