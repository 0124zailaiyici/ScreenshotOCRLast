"""集成测试：OCR 窗口的几何、按钮可见性与异步翻译行为。

全部使用会话级共享 Tk root（见 conftest.tk_root），并且用 stub_ocr
替换真实识别引擎 —— 测试不依赖本机 Tesseract，也不访问网络。
"""
import time

import pytest
from PIL import Image

from ocr_window import OcrWindow


def test_ocr_window_clamps_large_image(tk_root, stub_ocr):
    """超大截图区域应被限制在上限内。

    上限是**逻辑像素**，实际窗口尺寸按 DPI 缩放 —— 在 150% 的屏幕上窗口会大 1.5 倍，
    否则按点缩放的字号配上不缩放的窗口会非常拥挤。
    """
    from ui_theme import dpi_scale

    scale = dpi_scale(tk_root)
    win = OcrWindow(Image.new('RGB', (4000, 4000)), master=tk_root)
    try:
        win.root.update()
        assert win.root.winfo_width() <= int(600 * scale) + 2
        assert win.root.winfo_height() <= int(500 * scale) + 2
        # 也必须真的撑到了上限附近，否则"没超"可能只是因为窗口根本没建起来
        assert win.root.winfo_width() >= int(600 * scale) - 2
    finally:
        win.root.destroy()


def test_ocr_window_enforces_min_size(tk_root, stub_ocr):
    """极小的截图区域也必须保证按钮可见"""
    from ui_theme import dpi_scale

    scale = dpi_scale(tk_root)
    win = OcrWindow(Image.new('RGB', (100, 100)), master=tk_root)
    try:
        win.root.update()
        assert win.root.winfo_width() >= int(300 * scale) - 2
        assert win.root.winfo_height() >= int(200 * scale) - 2
    finally:
        win.root.destroy()


def test_ocr_window_layout_is_not_over_subscribed(tk_root, stub_ocr):
    """回归防护：矮窗口下各区块的**请求高度总和**不得超过窗口高度。

    空间够时 Tk 的 packer 怎么排都没问题；一旦请求总和超出窗口，它就只能按打包顺序
    分配，排在最后的控件被压成 0 高度、``winfo_ismapped()`` 变 0 —— 界面上直接少一块
    （``winfo_exists()`` 仍是 1，所以只有断言 ismapped 才查得出来）。

    实测踩过一次：``RoundedCard`` 里的 Canvas 用了 Tk 的默认请求尺寸（很大），
    一路传播上来把内容区撑到 288px，矮窗口下整条状态栏消失。

    图片刻意选得很矮让窗口落到高度下限。**用高窗口测没有意义** —— 请求总和小于窗口
    高度时 bug 根本不触发，断言恒真。
    """
    win = OcrWindow(Image.new('RGB', (400, 60)), master=tk_root)
    try:
        win.root.update()
        bar = win.btn_copy.master.master
        content = win.card.master
        status = win.lbl_status.master
        requested = (bar.winfo_reqheight() + content.winfo_reqheight()
                     + status.winfo_reqheight())
        assert requested <= win.root.winfo_height(), (
            f"请求高度总和 {requested}px 超出窗口 {win.root.winfo_height()}px，"
            "必然有控件被挤掉 —— 检查是否有控件虚报请求尺寸"
            "（最常见的是 Canvas，Tk 的默认请求尺寸很大）"
        )
        assert win.lbl_status.winfo_ismapped(), "状态栏被挤掉了"
        assert win.lbl_status.winfo_height() > 10
        assert win.lbl_view.winfo_ismapped()
        assert win.text_area.winfo_ismapped(), "内容区也必须仍然可见"
    finally:
        win.root.destroy()


def test_ocr_window_uses_a_self_drawn_scrollbar(tk_root, stub_ocr):
    """回归防护：滚动条必须是自绘的。

    ``tk.Scrollbar`` 一定带上下箭头，是"原生 Python 模样"最刺眼的来源。
    """
    from ui_widgets import ThinScrollbar

    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        win.root.update()
        assert isinstance(win.scrollbar, ThinScrollbar)
        # 必须真的接上了：Text 的 yscrollcommand 要指向滚动条的 set
        assert win.text_area.cget("yscrollcommand") != ""

        win.text_area.insert("1.0", "\n".join(f"第 {i} 行" for i in range(200)))
        win.root.update()
        win.scrollbar.set(0.0, 0.2)
        assert win.scrollbar._thumb_geom[1] > 0, "内容超出后滑块必须出现"
    finally:
        win.root.destroy()


def test_ocr_window_text_has_uniform_line_spacing(tk_root, stub_ocr):
    """回归防护：折行与硬换行必须得到同样的行距。

    Tk 的 Text 没有 line-height，只能靠 spacing1/2/3 模拟，而三者语义不同：
    spacing1/3 只作用于**逻辑行**的上下，spacing2 才作用于同一逻辑行的**折行**之间。
    只设 spacing1/3 的话，长行折行处会紧贴上一行、硬换行处却很松，
    同一段文字里出现两种行距。
    """
    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        spacing = win._line_spacing()
        assert spacing.get("spacing2", 0) > 0, "折行间距必须设置，否则折行会紧贴上一行"
        assert spacing.get("spacing3", 0) > 0, "逻辑行间距必须设置"
        assert spacing.get("spacing1", 0) == 0, "首行上方不应多出空隙"
    finally:
        win.root.destroy()


def test_language_selector_defaults_to_raw(tk_root, stub_ocr):
    """回归防护：初始必须选中「原文」。

    识别完还没翻译时把「中文」标成选中，会让用户以为看到的是译文。
    """
    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        win.root.update()
        assert win.lang_seg.value == "原文"
        assert win.current_lang == "raw"
    finally:
        win.root.destroy()


def test_retry_button_resets_state_and_restarts(tk_root, stub_ocr):
    """「重新识别」必须清空译文缓存并把视图退回原文，再重新发起识别"""
    win = OcrWindow(Image.new('RGB', (400, 400)), master=tk_root)
    try:
        win.root.update()
        win.translations["zh"] = "旧译文"
        win.current_lang = "zh"
        win.result["done"] = True
        win.result["text"] = "旧文本"
        win.lang_seg.set("中文", notify=False)

        win._retry_ocr()

        assert win.translations == {}, "重新识别必须丢掉上一次的译文"
        assert win.current_lang == "raw"
        assert win.lang_seg.value == "原文", "视图必须退回原文"
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
