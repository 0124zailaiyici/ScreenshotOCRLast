"""把 ScreenshotOCR 装到本用户目录，并创建开始菜单与桌面快捷方式。

为什么不用打包成安装程序（Inno Setup / NSIS）
---------------------------------------------
本程序是**单文件绿色 exe**，配置存在 ``%APPDATA%\\ScreenshotOCR``，exe 放哪都能跑。
所以"安装"这件事本质上只有三步：**把 exe 放个固定的地方、建两个快捷方式、
留一个能干净卸掉的入口**。为此引入一整套安装程序框架（还要额外维护 .iss/.nsi
脚本、多一个几十 MB 的构建产物）并不划算。

设计取舍
--------
- **装到本用户目录**（``%LOCALAPPDATA%\\Programs``），全程**不需要管理员权限**，
  也不会往 Program Files 写东西。单用户工具没必要提权。
- **不设开机自启**：这是用户明确选的。托盘工具确实需要常驻才能用热键，但那是
  用户的决定，不替他做。
- **卸载脚本里的路径写成绝对值**：桌面可能被 OneDrive 重定向到别处，卸载脚本
  自己再去解析一次容易出错，不如生成时就把真实路径写死。
- **不动用户数据**：卸载只删程序与快捷方式，``%APPDATA%\\ScreenshotOCR``
  （配置、钉住图片、翻译历史）保留 —— 重装后设置还在。
"""
import argparse
import os
import shutil
import subprocess
import sys

APP_NAME = "ScreenshotOCR"
APP_DISPLAY_NAME = "ScreenshotOCR 截图识字"
APP_VERSION = "1.4.1"
PUBLISHER = "ScreenshotOCR"

#: 快捷方式的文件名。
#:
#: **必须是这个中英混排的形式**：Windows 开始菜单是按**文件名**索引的，只叫
#: ``ScreenshotOCR.lnk`` 的话搜「截图」一个字都搜不到（Description 不参与
#: 索引）。带上中文才能中英两种搜法都命中。
SHORTCUT_NAME = "ScreenshotOCR 截图识字"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_EXE = os.path.join(BASE_DIR, "dist", f"{APP_NAME}.exe")

#: 卸载信息的注册表位置（HKCU = 本用户，不需要管理员）
#:
#: **注意别写成 ``r"...\Uninstall\\" + APP_NAME``** —— 原始字符串末尾的 ``\\``
#: 是**两个**反斜杠，拼出来就是 ``...\Uninstall\\ScreenshotOCR``。winreg 会容忍
#: 它，但 ``reg delete`` 不会，卸载时登记项就删不掉（实测踩过）。
UNINSTALL_KEY = (
    "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APP_NAME
)

#: 自启项（本脚本不写，留个常量方便日后需要时定位）
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _install_dir():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise SystemExit("找不到 %LOCALAPPDATA%，无法确定安装位置")
    return os.path.join(local, "Programs", APP_NAME)


def _start_menu_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("找不到 %APPDATA%，无法确定开始菜单位置")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")


def _desktop_dir():
    """取真实桌面路径。

    **不能拼 ``%USERPROFILE%\\Desktop``** —— 开了 OneDrive 桌面同步的机器上，
    真实桌面是 ``%USERPROFILE%\\OneDrive\\桌面``，拼出来的快捷方式用户看不见。
    问 shell 拿才是可靠的。
    """
    import ctypes
    from ctypes import wintypes

    CSIDL_DESKTOPDIRECTORY = 0x0010
    SHGFP_TYPE_CURRENT = 0
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(
        None, CSIDL_DESKTOPDIRECTORY, None, SHGFP_TYPE_CURRENT, buf
    )
    if not buf.value:
        raise SystemExit("无法获取桌面路径")
    return buf.value


def _create_shortcut(path, target, description, icon=None, workdir=None):
    """用 WScript.Shell 建 .lnk（pywin32 已随项目安装）。"""
    import pythoncom
    from win32com.client import Dispatch

    pythoncom.CoInitialize()
    shell = link = None
    try:
        shell = Dispatch("WScript.Shell")
        link = shell.CreateShortCut(path)
        link.TargetPath = target
        link.Description = description
        link.IconLocation = icon or f"{target},0"
        if workdir:
            link.WorkingDirectory = workdir
        link.Save()
    finally:
        # **必须先丢掉 COM 对象的引用再 CoUninitialize**：否则它们会在 COM 已经
        # 反初始化之后才被 GC 释放，每次调用都会往 stderr 吐一行
        # "Win32 exception occurred releasing IUnknown"（实测踩过）。
        del link, shell
        pythoncom.CoUninitialize()


def _write_uninstaller(install_dir, shortcuts):
    """生成 ``卸载.cmd``。

    **为什么要先把自己复制到 %TEMP% 再重新启动**：批处理删不掉自己所在的目录
    （文件被 cmd 占着）。常见的绕法是
    ``start "" cmd /c "timeout /t 2 & rd /s /q "C:\\路径""`` —— 但那个**嵌套引号
    在 cmd 里极不可靠**：内层引号会和外层配对，``rd`` 拿到的路径是断的，目录
    根本删不掉（第一版就是这么写的，测出来才发现）。

    换个思路就简单了：先把自身复制到 %TEMP% 并以那里为家重新跑一遍，于是
    ``rd`` 的目标变成了一个**普通目录**，引号只有一层，怎么写都对。
    """
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "",
        "rem 从 %TEMP% 里的副本执行，这样安装目录不是自己所在的目录",
        f'if /i not "%~dp0"=="%TEMP%\\" (',
        f'    copy /y "%~f0" "%TEMP%\\_screenshotocr_uninstall.cmd" >nul',
        "    rem **必须写成 cmd /c**：直接 start 一个 .cmd，Windows 会用 cmd /K 跑，",
        "    rem 脚本结束后留下一个不关的黑窗口（实测踩过）",
        f'    start "" /min cmd /c "%TEMP%\\_screenshotocr_uninstall.cmd"',
        "    exit /b",
        ")",
        "",
        f"echo 正在卸载 {APP_DISPLAY_NAME} ...",
        "timeout /t 2 >nul",
        "",
        "rem 先结束正在运行的实例，否则 exe 删不掉",
        f'taskkill /f /im "{APP_NAME}.exe" >nul 2>&1',
        "timeout /t 1 >nul",
        "",
        "rem 删除快捷方式",
    ]
    for shortcut in shortcuts:
        lines.append(f'del "{shortcut}" >nul 2>&1')

    lines += [
        "",
        "rem 删除「应用和功能」里的登记项",
        f'reg delete "HKCU\\{UNINSTALL_KEY}" /f >nul 2>&1',
        "",
        "rem 删除程序目录。此时脚本跑在 %TEMP%，目标目录没被占用，引号只有一层",
        f'rd /s /q "{install_dir}"',
        "",
        "echo 已卸载。",
        "echo 配置与历史记录保留在 %APPDATA%\\ScreenshotOCR，如需彻底清理请手动删除。",
        "timeout /t 3 >nul",
        'del "%~f0" >nul 2>&1',
    ]

    path = os.path.join(install_dir, "卸载.cmd")
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write("\n".join(lines))
    return path


def _register_uninstaller(install_dir, uninstaller):
    """在「设置 → 应用 → 已安装的应用」里登记一项（HKCU，不需要管理员）。"""
    import winreg

    exe = os.path.join(install_dir, f"{APP_NAME}.exe")
    values = {
        "DisplayName": APP_DISPLAY_NAME,
        "DisplayVersion": APP_VERSION,
        "Publisher": PUBLISHER,
        "DisplayIcon": f"{exe},0",
        "InstallLocation": install_dir,
        "UninstallString": f'"{uninstaller}"',
        "QuietUninstallString": f'"{uninstaller}"',
        "NoModify": 1,
        "NoRepair": 1,
    }
    key = winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE
    )
    try:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ if isinstance(value, str)
                              else winreg.REG_DWORD, value)
    finally:
        winreg.CloseKey(key)


def _wait_for_exit(timeout=15.0):
    """等 ScreenshotOCR 进程真的消失。

    ``taskkill`` 是**异步**的：它返回时进程只是"收到了终止信号"，文件句柄还没
    释放。紧接着复制 exe 会撞上 ``PermissionError: [Errno 13]``（实测踩过 ——
    第一次安装成功是因为旧实例跑的是 ``dist\\`` 里的另一个文件，不冲突；
    覆盖安装时必现）。
    """
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["tasklist", "/fi", f"imagename eq {APP_NAME}.exe", "/nh"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if APP_NAME.lower() not in (result.stdout or "").lower():
            return True
        time.sleep(0.3)
    return False


def _stop_running():
    """结束正在运行的实例，否则覆盖不了 exe。

    **只结束进程名为 ScreenshotOCR 的** —— 不能按窗口标题或路径模糊匹配，
    那可能误杀用户的其它程序。
    """
    subprocess.run(
        ["taskkill", "/f", "/im", f"{APP_NAME}.exe"],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return _wait_for_exit()


def install(start_after=True):
    if not os.path.exists(SOURCE_EXE):
        raise SystemExit(f"找不到 {SOURCE_EXE}\n请先运行 build_exe.py 打包。")

    install_dir = _install_dir()
    target_exe = os.path.join(install_dir, f"{APP_NAME}.exe")

    print(f"安装到: {install_dir}")
    _stop_running()
    os.makedirs(install_dir, exist_ok=True)
    shutil.copy2(SOURCE_EXE, target_exe)
    print(f"  已复制 {APP_NAME}.exe（{os.path.getsize(target_exe) / 1024 / 1024:.2f} MB）")

    start_menu_link = os.path.join(_start_menu_dir(), f"{SHORTCUT_NAME}.lnk")
    desktop_link = os.path.join(_desktop_dir(), f"{SHORTCUT_NAME}.lnk")
    description = "截图识字：Alt+X 截图，可钉住 / 识别文字 / 复制"

    for link in (start_menu_link, desktop_link):
        _create_shortcut(link, target_exe, description, workdir=install_dir)
        print(f"  已创建快捷方式 {link}")

    uninstaller = _write_uninstaller(
        install_dir, [start_menu_link, desktop_link]
    )
    print(f"  已生成 {uninstaller}")
    _register_uninstaller(install_dir, uninstaller)
    print("  已在「应用和功能」中登记（可从这里卸载）")

    if start_after:
        subprocess.Popen([target_exe], cwd=install_dir)
        print("  已启动")

    print("\n完成。以后从开始菜单搜索「截图」或双击桌面图标即可打开。")
    print("注意：没设开机自启，重启后需要自己打开一次，Alt+X 才生效。")
    return 0


def uninstall():
    install_dir = _install_dir()
    print(f"从 {install_dir} 卸载 ...")
    _stop_running()

    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        print("  已删除「应用和功能」登记项")
    except FileNotFoundError:
        pass

    for link in (
        os.path.join(_start_menu_dir(), f"{SHORTCUT_NAME}.lnk"),
        os.path.join(_desktop_dir(), f"{SHORTCUT_NAME}.lnk"),
    ):
        if os.path.exists(link):
            os.remove(link)
            print(f"  已删除 {link}")

    if os.path.isdir(install_dir):
        shutil.rmtree(install_dir, ignore_errors=True)
        print(f"  已删除 {install_dir}")

    print("\n完成。配置与历史记录保留在 %APPDATA%\\ScreenshotOCR。")
    return 0


def main():
    parser = argparse.ArgumentParser(description="安装 / 卸载 ScreenshotOCR")
    parser.add_argument("--uninstall", action="store_true", help="卸载")
    parser.add_argument("--no-start", action="store_true", help="安装后不自动启动")
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("本脚本仅支持 Windows")
    return uninstall() if args.uninstall else install(start_after=not args.no_start)


if __name__ == "__main__":
    sys.exit(main())
