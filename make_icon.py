"""生成程序图标 ``assets/app.ico``。

为什么需要它
------------
打包时没指定 ``--icon``，所以 EXE 一直用的是 PyInstaller 的默认图标 ——
装到开始菜单/桌面之后，那个默认图标会显得很不成样子。

这里复用**托盘图标的设计**（`tray_app.TrayApp._create_image` 画的那台相机），
所以任务栏、开始菜单、托盘三处的图形是一致的。区别只有一个：**背景透明**。
托盘图标是画在一个 64x64 实心方块上的（深色模式下就是一块深灰），装到开始
菜单里会是一个方块；程序图标用透明底在任何主题下都正常。

做法
----
按 64 为基准的原始坐标放大 16 倍画到 1024x1024，再交给 Pillow 用 LANCZOS
逐级缩小到各个尺寸。**先大后小**是图标的标准做法 —— 直接在小画布上画，
细线会糊成一团。
"""
import os
import sys

from PIL import Image, ImageDraw

#: 原始设计是按 64x64 画的，这里统一放大到这个倍数再缩小
SUPERSAMPLE = 16
BASE = 64
SIZES = [16, 24, 32, 48, 64, 128, 256]

#: 相机主体的颜色。用系统强调色会更好看，但强调色随用户设置变化，
#: 图标应当是固定的品牌资产 —— 所以钉死成项目主色（就是默认强调色的深色版）。
BODY = "#7B2D8E"
DARK = "#2B1B30"
HIGHLIGHT = "#FFFFFF"


def _scale(box):
    return [value * SUPERSAMPLE for value in box]


def build_image(size=BASE * SUPERSAMPLE):
    """画出透明底的相机图标。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)

    # 相机机身（圆角矩形）
    dc.rounded_rectangle(_scale([8, 18, 56, 52]), radius=8 * SUPERSAMPLE, fill=BODY)

    # 取景器凸起
    dc.rectangle(_scale([22, 12, 42, 18]), fill=BODY)

    # 外层镜头环：**填充透明**，让背景透过去，这样明暗两种主题下都自然
    dc.ellipse(_scale([18, 24, 46, 48]), fill=(0, 0, 0, 0),
               outline=BODY, width=3 * SUPERSAMPLE)

    # 内层镜头
    dc.ellipse(_scale([24, 30, 40, 42]), fill=DARK)

    # 镜头高光
    dc.ellipse(_scale([21, 27, 27, 31]), fill=HIGHLIGHT)

    return image


def main():
    base_path = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(base_path, "assets")
    os.makedirs(assets, exist_ok=True)
    target = os.path.join(assets, "app.ico")

    image = build_image()
    image.save(target, format="ICO", sizes=[(s, s) for s in SIZES])

    print(f"已生成 {target}")
    print(f"  源图 {image.width}x{image.height}，含尺寸 {SIZES}")
    print(f"  体积 {os.path.getsize(target) / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
