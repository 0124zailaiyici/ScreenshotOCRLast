"""集成测试：OCR 窗口的几何、按钮可见性与异步翻译行为。

全部使用会话级共享 Tk root（见 conftest.tk_root），并且用 stub_ocr
替换真实识别引擎 —— 测试不依赖本机 Tesseract，也不访问网络。
"""
import time

import pytest
from PIL import Image

from ocr_window import OcrWindow


def test_ocr_window_clamps_large_image(tk_root, stub_ocr):
    """超大截图区域应被限制在 600x500 以内"""
    win = OcrWindow(Image.new('RGB', (2000, 2000)), master=tk_root)
    try:
        win.root.update()
        assert win.root.winfo_width() <= 600
        assert win.root.winfo_height() <= 500
    finally:
        win.root.destroy()


def test_ocr_window_enforces_min_size(tk_root, stub_ocr):
    """极小的截图区域也必须保证按钮可见"""
    win = OcrWindow(Image.new('RGB', (100, 100)), master=tk_root)
    try:
        win.root.update()
        assert win.root.winfo_width() >= 300
        assert win.root.winfo_height() >= 180
    finally:
        win.root.destroy()


def test_copy_button_visible_on_first_screen(tk_root, stub_ocr):
    """复制按钮必须在首屏可见，且文案正确"""
    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        win.root.update()
        assert win.btn_copy.winfo_ismapped()
        assert "复制" in win.btn_copy.cget("text")
    finally:
        win.root.destroy()


def test_translate_click_does_not_block_ui(tk_root, stub_ocr, monkeypatch):
    """点击翻译必须立即返回，网络请求交给后台线程"""
    import ocr_window

    dispatched = {}

    def fake_translate_async(text, callback, error_callback=None, **kwargs):
        dispatched["text"] = text
        dispatched["to_lang"] = kwargs.get("to_lang")

    monkeypatch.setattr(ocr_window.translator, "translate_async", fake_translate_async)

    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        win.result["text"] = "Hello"
        win.result["done"] = True
        win.root.update()

        start = time.perf_counter()
        win._trigger_translate("zh")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.05, "翻译触发必须是异步的，不能阻塞 UI"
        assert dispatched["text"] == "Hello"      # 确认真的派发了任务
        assert dispatched["to_lang"] == "zh"
    finally:
        win.root.destroy()


def test_translate_ignored_before_ocr_finishes(tk_root, stub_ocr, monkeypatch):
    """识别尚未完成时点击翻译应被忽略，不应发出请求"""
    import ocr_window

    calls = []
    monkeypatch.setattr(ocr_window.translator, "translate_async",
                        lambda *a, **k: calls.append(1))

    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        win.result["done"] = False
        win.result["error"] = None
        win.root.update()

        win._trigger_translate("zh")
        assert calls == []
    finally:
        win.root.destroy()


def test_translate_result_is_cached(tk_root, stub_ocr, monkeypatch):
    """同一目标语言翻译过一次后应命中缓存，不重复请求"""
    import ocr_window

    calls = []
    monkeypatch.setattr(ocr_window.translator, "translate_async",
                        lambda *a, **k: calls.append(1))

    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        win.result["text"] = "Hello"
        win.result["done"] = True
        win.translations["zh"] = "你好"
        win.root.update()

        win._trigger_translate("zh")

        assert calls == []                                  # 未再次请求
        assert win.text_area.get("1.0", "end").strip() == "你好"
    finally:
        win.root.destroy()


def test_icon_cache_is_keyed_on_the_calling_widget_root():
    """回归防护：图标缓存必须跟随**调用方控件所属的 root** 失效。

    旧实现用 ``tkinter._default_root`` 判断「root 是否变了」，但该变量只在
    它为 None 时才被新 root 覆盖。两个 root 并存时它不会变化，缓存不会失效，
    旧句柄被配置给新解释器的控件就会抛
    ``TclError: image "pyimageN" doesn't exist``。

    这里刻意**不创建真实 Tk 解释器**：同一进程内并存 3 个以上解释器会让 Tcl
    找不到 init.tcl（实测不稳定），测试本身必须保持确定性。
    """
    from ui_icons import IconProvider

    class FakeWidget:
        """_sync 只需要控件能报出自己所属的 root"""

        def __init__(self, root):
            self._root_obj = root

        def _root(self):
            return self._root_obj

    provider = IconProvider()
    root_a, root_b = object(), object()

    provider._cache_root = root_a
    provider._cache[("pin", "#000000")] = "cached-for-a"

    # 同一个 root：缓存必须保留，否则每次取图标都要重画
    assert provider._sync(FakeWidget(root_a)) is root_a
    assert provider._cache == {("pin", "#000000"): "cached-for-a"}

    # root 变化：缓存必须清空，绝不能把失效句柄交给新解释器
    assert provider._sync(FakeWidget(root_b)) is root_b
    assert provider._cache == {}
    assert provider._cache_root is root_b


def test_icon_sync_requires_a_root(monkeypatch):
    """没有任何 Tk root 时必须给出明确错误，而不是让 PIL 抛难懂的异常"""
    import tkinter

    from ui_icons import IconProvider

    monkeypatch.setattr(tkinter, "_default_root", None)
    with pytest.raises(RuntimeError):
        IconProvider()._sync(None)
