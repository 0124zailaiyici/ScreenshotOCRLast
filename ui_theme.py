"""主题系统：颜色令牌、字体、间距。

三条必须遵守的规则
------------------
1. **字体必须含中日韩字形**。原来用 ``Segoe UI``，它没有中文字形，Tk 只能逐字回退到别的
   字体，于是中英文混排时字重、字距、基线都不一致（截图里中文明显比英文粗）。改用
   ``Microsoft YaHei UI`` —— 它同时含拉丁与中日韩字形，也是 Windows 11 中文界面的默认字体。

2. **字号一律传正数（点）**。本程序是 DPI 感知的（``main.py`` 里 ``SetProcessDPIAware()``），
   Tk 会把点按 ``tk scaling`` 换算成物理像素，所以在 150% 缩放的屏幕上会自动放大。传负数
   表示「像素」，那样在高 DPI 屏上反而会显得偏小。实测本机 ``tk scaling = 2.0``（150%）。

3. **间距一律走 :func:`px`**。``padx``/``pady``/``width`` 这类参数的单位是物理像素，
   直接写 12 在 150% 屏上只有 8 个逻辑像素，观感会偏挤。:func:`px` 把设计稿上的逻辑像素
   换算成当前 DPI 下的物理像素，保证不同缩放下观感一致。

UI 代码只引用 ``theme.xxx``，**不要写死色值**，否则深色/浅色切换一定会漏。
"""

from dataclasses import dataclass

# ---------------------------------------------------------------- 字体

# 必须同时含拉丁与中日韩字形。改这个值前请先确认字体在系统里真实存在，
# 否则 Tk 会静默回退，又变回"中英文混排不一致"。
FONT_FAMILY = "Microsoft YaHei UI"
FONT_MONO = "Cascadia Mono"

FONT_H1 = (FONT_FAMILY, 24, "bold")
FONT_H2 = (FONT_FAMILY, 18, "bold")
FONT_BODY = (FONT_FAMILY, 14)
FONT_TEXT = (FONT_FAMILY, 12)          # OCR 正文（阅读主体）
FONT_SMALL = (FONT_FAMILY, 11)
FONT_BUTTON = (FONT_FAMILY, 10)
FONT_BUTTON_SM = (FONT_FAMILY, 9)
FONT_META = (FONT_FAMILY, 9)           # 状态栏、次要元信息

# ---------------------------------------------------------------- 间距（逻辑像素）

SPACE_XXS = 2
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# ---------------------------------------------------------------- 圆角（逻辑像素）

RADIUS_S = 4
RADIUS_M = 8
RADIUS_L = 12

# ---------------------------------------------------------------- 语义色

COLOR_SUCCESS = "#107C10"
COLOR_SUCCESS_DARK = "#4CC38A"
COLOR_ERROR = "#D13438"
COLOR_ERROR_DARK = "#F1707B"
COLOR_PRIMARY_DEFAULT = "#0078D4"


# ---------------------------------------------------------------- DPI 工具


def dpi_scale(widget) -> float:
    """当前显示器的缩放系数（1.0 = 100%）。取不到时保守返回 1.0。"""
    try:
        return max(1.0, widget.winfo_fpixels("1i") / 96.0)
    except Exception:
        return 1.0


def px(widget, value: float) -> int:
    """把设计稿上的逻辑像素换算成当前 DPI 下的物理像素。

    所有传给 Tk 的 ``padx``/``pady``/``width``/``height``/``spacing*`` 都应该过这个函数，
    否则在高 DPI 屏上间距会按比例缩水。
    """
    return max(1, int(round(value * dpi_scale(widget))))


# ---------------------------------------------------------------- 颜色工具


def hex_to_rgb(color: str):
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def rgb_to_hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def blend(color_a: str, color_b: str, t: float) -> str:
    """在 color_a 与 color_b 之间线性插值，t=0 取 a、t=1 取 b。"""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = hex_to_rgb(color_a)
    rb, gb, bb = hex_to_rgb(color_b)
    return rgb_to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def lighten(color: str, amount: float) -> str:
    return blend(color, "#FFFFFF", amount)


def darken(color: str, amount: float) -> str:
    return blend(color, "#000000", amount)


def mix_toward(color: str, target: str, amount: float) -> str:
    """把 color 朝 target 混，用于生成"悬停/按下"这类同色系变体。"""
    return blend(color, target, amount)


def relative_luminance(color: str) -> float:
    """粗略相对亮度（0~1），用于决定压在强调色上的文字该用黑还是白。"""
    r, g, b = hex_to_rgb(color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def readable_on(background: str, light: str = "#FFFFFF", dark: str = "#1A1A1A") -> str:
    """在给定背景色上选一个可读的前景色。"""
    return dark if relative_luminance(background) > 0.6 else light


# ---------------------------------------------------------------- 主题令牌


@dataclass(frozen=True)
class Theme:
    """不可变的主题色值集合。

    新增字段时必须同时更新 ``LIGHT`` 与 ``DARK``（frozen dataclass 无默认值）。
    """

    # 窗口与表面
    bg_primary: str
    bg_surface: str
    bg_toolbar: str
    bg_chrome: str          # 顶部操作栏
    bg_card: str            # 文本卡片
    bg_status: str          # 底部状态栏
    bg_hover: str
    bg_pressed: str
    bg_input: str

    # 文字
    text_primary: str
    text_secondary: str
    text_tertiary: str      # 更弱：状态栏、单位
    text_disabled: str
    text_inverse: str

    # 描边
    border_default: str
    border_card: str        # 卡片描边（比 border_default 更淡）
    divider: str            # 工具栏里的竖向分隔线

    # 滚动条
    sb_thumb: str
    sb_thumb_hover: str

    # 覆盖层
    overlay_color: str
    overlay_alpha: float

    # 语义色（随明暗切换，保证对比度）
    success: str
    error: str


LIGHT = Theme(
    bg_primary="#F3F3F3",
    bg_surface="#FFFFFF",
    bg_toolbar="#FFFFFF",
    bg_chrome="#FFFFFF",
    bg_card="#FFFFFF",
    bg_status="#F7F7F7",
    bg_hover="#EAEAEA",
    bg_pressed="#DCDCDC",
    bg_input="#FFFFFF",
    text_primary="#1A1A1A",
    text_secondary="#5A5A5A",
    text_tertiary="#8A8A8A",
    text_disabled="#B0B0B0",
    text_inverse="#FFFFFF",
    border_default="#D6D6D6",
    border_card="#E4E4E4",
    divider="#E0E0E0",
    sb_thumb="#C6C6C6",
    sb_thumb_hover="#A6A6A6",
    overlay_color="#F3F3F3",
    overlay_alpha=0.3,
    success=COLOR_SUCCESS,
    error=COLOR_ERROR,
)

DARK = Theme(
    bg_primary="#202020",
    bg_surface="#2B2B2B",
    bg_toolbar="#262626",
    bg_chrome="#262626",
    bg_card="#2B2B2B",
    bg_status="#1B1B1B",
    bg_hover="#333333",
    bg_pressed="#404040",
    bg_input="#2B2B2B",
    text_primary="#F2F2F2",
    text_secondary="#A8A8A8",
    text_tertiary="#6E6E6E",
    text_disabled="#5A5A5A",
    text_inverse="#1A1A1A",
    border_default="#3D3D3D",
    border_card="#3A3A3A",
    divider="#3A3A3A",
    sb_thumb="#4A4A4A",
    sb_thumb_hover="#5E5E5E",
    overlay_color="#000000",
    overlay_alpha=0.4,
    success=COLOR_SUCCESS_DARK,
    error=COLOR_ERROR_DARK,
)


class ThemeManager:
    """主题管理器单例。

    除了基础的明暗主题，还负责从系统强调色派生出按钮需要的几种变体
    （悬停、按下、可读前景色），这样 UI 代码不必自己做颜色运算。
    """

    def __init__(self):
        self._is_dark = False
        self._accent_color = COLOR_PRIMARY_DEFAULT
        self._theme = LIGHT
        self._recompute_accent()

    # ---------------------------------------------------------- 基础访问

    @property
    def is_dark(self) -> bool:
        return self._is_dark

    @property
    def accent_color(self) -> str:
        return self._accent_color

    @property
    def theme(self) -> Theme:
        return self._theme

    def update(self, is_dark: bool, accent_color: str):
        self._is_dark = bool(is_dark)
        self._accent_color = accent_color or COLOR_PRIMARY_DEFAULT
        self._theme = DARK if self._is_dark else LIGHT
        self._recompute_accent()

    # ---------------------------------------------------------- 强调色派生

    def _recompute_accent(self):
        accent = self._accent_color
        if self._is_dark:
            # 深色底上把强调色提亮一点，否则压在白字上会糊
            self._accent = lighten(accent, 0.10)
            self._accent_hover = lighten(accent, 0.24)
            self._accent_pressed = lighten(accent, 0.02)
            self._accent_soft = blend(self._theme.bg_card, accent, 0.18)
            self._accent_border = blend(self._theme.bg_card, accent, 0.45)
            self._accent_text = lighten(accent, 0.38)
        else:
            self._accent = accent
            self._accent_hover = darken(accent, 0.10)
            self._accent_pressed = darken(accent, 0.22)
            self._accent_soft = blend(self._theme.bg_card, accent, 0.10)
            self._accent_border = blend(self._theme.bg_card, accent, 0.35)
            self._accent_text = darken(accent, 0.20)
        self._accent_fg = readable_on(self._accent)

    @property
    def accent(self) -> str:
        """强调色本体（用作主按钮底色）。"""
        return self._accent

    @property
    def accent_hover(self) -> str:
        return self._accent_hover

    @property
    def accent_pressed(self) -> str:
        return self._accent_pressed

    @property
    def accent_soft(self) -> str:
        """强调色的低饱和底（用作"已选中"的浅色块）。"""
        return self._accent_soft

    @property
    def accent_border(self) -> str:
        return self._accent_border

    @property
    def accent_text(self) -> str:
        """强调色的文字版本 —— 在卡片底上可读。"""
        return self._accent_text

    @property
    def accent_fg(self) -> str:
        """压在 accent 底色上的前景色。"""
        return self._accent_fg

    # ---------------------------------------------------------- 便利方法

    def c(self, light_val, dark_val):
        """按当前明暗返回不同的值。"""
        return dark_val if self._is_dark else light_val


theme_manager = ThemeManager()
