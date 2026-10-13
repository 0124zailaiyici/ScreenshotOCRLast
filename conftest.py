"""共享测试夹具。

Tkinter 有两条硬约束，测试必须尊重：

1. 同一进程内反复创建并销毁 Tk root 会留下失效的 Tcl 解释器，导致
   ``TclError: invalid command name "tcl_findLibrary"``。因此整个测试会话
   共用一个隐藏 Tk root，各用例只创建 Toplevel。
2. 缓存的 PhotoImage 隶属于创建它的解释器。``ui_icons`` 现在会在 root
   变化时自动失效缓存，测试不应再依赖手动 ``clear_cache()``。

配置方面：``ConfigManager`` 默认读写 ``%APPDATA%/ScreenshotOCR``，也就是
用户真实配置。测试一律通过 ``isolated_config`` 夹具重定向到临时目录，
既不污染用户数据，也不再依赖用户当前的热键等设置。
"""
import tkinter

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """整个测试会话共用的隐藏 Tk root"""
    root = tkinter.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tkinter.TclError:
        pass


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """把 config_manager 重定向到临时目录。

    多个模块用 ``from config import config_manager`` 绑定了引用，
    必须逐个替换，否则钉住窗口等测试仍会写入用户真实配置。
    """
    from config import ConfigManager
    import config as config_module
    import ocr_engine
    import pin_window

    cm = ConfigManager(config_dir=str(tmp_path / "ScreenshotOCR"))
    monkeypatch.setattr(config_module, "config_manager", cm)
    monkeypatch.setattr(ocr_engine, "config_manager", cm)
    monkeypatch.setattr(pin_window, "config_manager", cm)
    return cm


@pytest.fixture
def stub_ocr(monkeypatch):
    """替换 OCR 引擎，使 UI 测试不依赖本机是否安装 Tesseract"""
    class _StubEngine:
        name = "stub"

        def is_available(self):
            return True

        def recognize(self, image):
            return "stub text"

    import ocr_window
    monkeypatch.setattr(ocr_window, "create_ocr_engine", lambda *a, **k: _StubEngine())
    return _StubEngine
