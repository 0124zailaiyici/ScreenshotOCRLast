from dataclasses import dataclass, field

# ---- 字体常量 ----
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"

FONT_H1 = (FONT_FAMILY, 24, "bold")
FONT_H2 = (FONT_FAMILY, 18, "bold")
FONT_BODY = (FONT_FAMILY, 14)
FONT_SMALL = (FONT_FAMILY, 12)
FONT_BUTTON = (FONT_FAMILY, 10)
FONT_BUTTON_SM = (FONT_FAMILY, 9)

# ---- 间距常量 ----
SPACE_XXS = 2
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# ---- 圆角常量 ----
RADIUS_S = 4
RADIUS_M = 8
RADIUS_L = 12

# ---- 语义色 ----
COLOR_SUCCESS = "#107C10"
COLOR_ERROR = "#D13438"
COLOR_PRIMARY_DEFAULT = "#0078D4"


@dataclass(frozen=True)
class Theme:
    """不可变的主题色值集合"""
    bg_primary: str
    bg_surface: str
    bg_toolbar: str
    bg_hover: str
    bg_pressed: str
    bg_input: str
    text_primary: str
    text_secondary: str
    text_disabled: str
    text_inverse: str
    border_default: str
    overlay_color: str
    overlay_alpha: float


LIGHT = Theme(
    bg_primary="#F3F3F3",
    bg_surface="#FFFFFF",
    bg_toolbar="#FFFFFF",
    bg_hover="#E5E5E5",
    bg_pressed="#D0D0D0",
    bg_input="#FFFFFF",
    text_primary="#000000",
    text_secondary="#333333",
    text_disabled="#999999",
    text_inverse="#FFFFFF",
    border_default="#CCCCCC",
    overlay_color="#F3F3F3",
    overlay_alpha=0.3,
)

DARK = Theme(
    bg_primary="#202020",
    bg_surface="#2B2B2B",
    bg_toolbar="#2B2B2B",
    bg_hover="#3D3D3D",
    bg_pressed="#505050",
    bg_input="#1A1A1A",
    text_primary="#FFFFFF",
    text_secondary="#CCCCCC",
    text_disabled="#666666",
    text_inverse="#000000",
    border_default="#444444",
    overlay_color="#000000",
    overlay_alpha=0.4,
)


class ThemeManager:
    """主题管理器单例"""

    def __init__(self):
        self._is_dark = False
        self._accent_color = COLOR_PRIMARY_DEFAULT
        self._theme = LIGHT

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
        self._is_dark = is_dark
        self._accent_color = accent_color or COLOR_PRIMARY_DEFAULT
        self._theme = DARK if is_dark else LIGHT

    # 便利方法：提供浅色/深色下的不同值
    def c(self, light_val, dark_val):
        return dark_val if self._is_dark else light_val


theme_manager = ThemeManager()
