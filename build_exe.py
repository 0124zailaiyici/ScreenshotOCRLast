"""打包脚本：把 ScreenshotOCR 打成单文件 exe，并在打包后自检包内容。

自检的由来
----------
本项目的 EXE 体积曾在两次构建之间从 **36MB 掉到 29MB**，事后无法复原产物、
也就查不出究竟少了什么。体积变化本身无所谓，**静默少打模块才是问题** ——
最可疑的是 ``translators`` 的依赖树（``cryptography`` / ``lxml`` / ``qh3`` /
四套 HTTP 客户端，合计约 7MB），它们全是动态导入，最容易在分析时被漏掉，
而漏掉的后果是"翻译功能在 exe 里直接坏掉，但打包过程一切正常"。

所以构建结束后显式验证关键模块确实在 PYZ 里。宁可打包失败，也不要产出
一个看起来正常、用起来缺功能的包。
"""
import os
import sys

import PyInstaller.__main__

# 必须真的进入 PYZ 的模块。分三组：
#   1. 本项目自己的模块（新增模块后记得往这里加）
#   2. 直接依赖
#   3. translators 的依赖树 —— 全动态导入，是体积波动的来源，也是翻译功能的必要条件
REQUIRED_MODULES = [
    # 1. 本项目
    "main", "ocr_window", "screenshot_overlay", "pin_window", "tray_app",
    "ui_theme", "ui_widgets", "ui_icons", "config", "clipboard_manager",
    "hotkey_listener", "ocr_engine", "translator",
    # 2. 直接依赖
    "pystray", "pynput", "pytesseract", "PIL.ImageTk", "win32clipboard",
    # 3. translators 的依赖树（翻译功能必需，动态导入，最容易被漏）
    "translators", "cryptography", "lxml", "certifi",
    "requests", "aiohttp", "httpx", "niquests",
]

# 明确排除的包：出现了就说明 --exclude-module 没生效（pandas 会连带 numpy+OpenBLAS，
# 实测多占约 63MB 工作集）
FORBIDDEN_MODULES = ["pandas", "numpy", "matplotlib", "scipy", "torch"]


def _read_bundled_modules(exe_path):
    """读出 exe 里"模块存在"的证据名。

    **两类东西都要看，少看一类就会误报**：

    - **PYZ 模块**：纯 Python 模块，绝大多数在这里；
    - **顶层条目**：入口脚本 ``main`` 本身，以及原生扩展 —— PyInstaller 把
      ``.pyd`` / ``.dll`` 放在顶层，**不放进 PYZ**（例如
      ``win32\\win32clipboard.pyd``，而它是以 ``win32clipboard`` 这个名字被 import 的）。

    顶层条目会归一化成点分名字，并同时登记去掉扩展名、去掉包前缀的形态，
    这样 ``win32\\win32clipboard.pyd`` 能匹配到 ``win32clipboard``。
    """
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(exe_path)
    names = set()
    for name in reader.toc:
        if name.lower().endswith(".pyz"):
            names |= set(reader.open_embedded_archive(name).toc)
            continue
        norm = name.replace("\\", ".").replace("/", ".")
        names.add(norm)
        if "." in norm:
            base, _, ext = norm.rpartition(".")
            if ext.lower() in ("pyd", "dll", "so"):
                names.add(base)                    # win32.win32clipboard
                names.add(base.rpartition(".")[2])  # win32clipboard
    return names


def verify_build(exe_path):
    """打包后自检：关键模块在不在、该排除的在不在。

    :return: 通过返回 True
    """
    if not os.path.exists(exe_path):
        print("自检失败: 找不到产物 " + exe_path)
        return False

    size_mb = os.path.getsize(exe_path) / 1024 / 1024
    print("\n" + "=" * 30)
    print(f"打包完成！体积 {size_mb:.2f} MB")
    print(f"可执行文件位于: {exe_path}")
    print("你可以将该文件发送到桌面直接运行。")

    try:
        modules = _read_bundled_modules(exe_path)
    except Exception as e:
        print(f"\n自检失败: 无法读取包内容 ({e})")
        print("=" * 30)
        return False

    print(f"\n包内模块总数: {len(modules)}")
    missing = [m for m in REQUIRED_MODULES if m not in modules]
    forbidden = [m for m in FORBIDDEN_MODULES if m in modules]
    if missing:
        print("\n自检失败: 以下必需模块没有被打进包 ——")
        for m in missing:
            print(f"  - {m}")
        print("最可能的原因: 该模块是动态导入，PyInstaller 的静态分析没跟到。")
        print("处理方式: 在 params 里补 --hidden-import=<模块名>，然后重新打包。")
    if forbidden:
        print("\n自检失败: 以下模块本应被排除，却出现在包里 ——")
        for m in forbidden:
            print(f"  - {m}")
        print("处理方式: 检查 params 里的 --exclude-module 是否还有效。")

    if missing or forbidden:
        print("=" * 30)
        return False

    print("自检通过: 必需模块齐全，排除项也没漏进来。")
    print("=" * 30)
    return True


def build():
    # 确保在项目根目录运行
    base_path = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_path)
    exe_path = os.path.join(base_path, "dist", "ScreenshotOCR.exe")

    print("正在开始打包 ScreenshotOCR...")

    params = [
        'main.py',              # 主程序入口
        '--name=ScreenshotOCR', # 生成的 exe 名称
        '--onefile',            # 打包成单文件
        '--noconsole',          # 运行时不显示控制台
        '--clean',              # 打包前清理临时文件

        # 强制包含的关键动态库
        '--hidden-import=pystray',
        '--hidden-import=pynput',
        '--hidden-import=pytesseract',
        '--hidden-import=win32clipboard',
        '--hidden-import=translators',
        '--hidden-import=PIL.ImageTk',
        '--hidden-import=ui_theme',
        '--hidden-import=ui_widgets',
        '--hidden-import=ui_icons',

        # 排除不必要的超大库以减小体积
        '--exclude-module=matplotlib',
        '--exclude-module=notebook',
        '--exclude-module=pandas',
        '--exclude-module=scipy',
        '--exclude-module=torch',
        '--exclude-module=setuptools',
    ]

    try:
        PyInstaller.__main__.run(params)
    except Exception as e:
        print(f"打包失败: {e}")
        return False

    # PyInstaller 自己出错时是抛 SystemExit，所以走到这里只代表它没抛异常 ——
    # 包内容对不对必须自己验
    ok = verify_build(exe_path)
    if not ok:
        sys.exit(1)
    return True


if __name__ == "__main__":
    build()
