"""单元测试：配置、剪贴板、OCR 引擎契约。

这些用例全部是 hermetic 的 —— 不读写用户真实配置，不依赖本机
是否安装 Tesseract，也不访问网络。
"""
import json
import os

import pytest
from PIL import Image


# ---------- 配置 ----------

def test_config_defaults_are_stable(isolated_config):
    """默认配置项必须与文档一致"""
    assert isolated_config.get("hotkey") == "<alt>+x"
    assert isolated_config.get("ocr_backend") == "tesseract"
    assert isolated_config.get("ocr_lang") == "chi_sim+eng"
    assert isolated_config.get("notification_enabled") is True


def test_config_roundtrip_persists_to_disk(isolated_config):
    """写入的值必须真正落盘，并能被新实例读回"""
    isolated_config.set("test_key", "test_value")
    assert isolated_config.get("test_key") == "test_value"

    assert os.path.exists(isolated_config.config_path)
    with open(isolated_config.config_path, 'r', encoding='utf-8') as f:
        assert json.load(f)["test_key"] == "test_value"

    from config import ConfigManager
    reloaded = ConfigManager(config_dir=isolated_config.config_dir)
    assert reloaded.get("test_key") == "test_value"


def test_config_discards_corrupted_values(tmp_path):
    """被写坏类型的配置项必须被丢弃，而不是带进运行期引发崩溃"""
    from config import ConfigManager, CONFIG_FILE

    d = tmp_path / "ScreenshotOCR"
    d.mkdir(parents=True)
    (d / CONFIG_FILE).write_text(json.dumps({
        "hotkey": "<alt>+x",            # 合法，应保留
        "pinned_items": "not-a-list",   # 脏值
        "notification_enabled": "yes",  # 脏值
        "ocr_lang": 123,                # 脏值
    }), encoding="utf-8")

    cm = ConfigManager(config_dir=str(d))
    assert cm.get("hotkey") == "<alt>+x"            # 合法值保留
    assert cm.get("pinned_items") == []             # 回落默认
    assert cm.get("notification_enabled") is True   # 回落默认
    assert cm.get("ocr_lang") == "chi_sim+eng"      # 回落默认
    assert cm.get_pinned_items() == []              # 不再抛异常


def test_config_ignores_non_object_json(tmp_path):
    """配置根节点不是 JSON 对象时不应崩溃，也不应污染内存配置"""
    from config import ConfigManager, CONFIG_FILE

    d = tmp_path / "ScreenshotOCR"
    d.mkdir(parents=True)
    (d / CONFIG_FILE).write_text("[1, 2, 3]", encoding="utf-8")

    cm = ConfigManager(config_dir=str(d))
    assert cm.get("hotkey") == "<alt>+x"


def test_config_set_rejects_wrong_type(isolated_config):
    """已知键收到类型不符的值时必须拒绝写入，与 load() 的校验保持一致"""
    isolated_config.set("pinned_items", "not-a-list")
    assert isolated_config.get("pinned_items") == []

    isolated_config.set("notification_enabled", "yes")
    assert isolated_config.get("notification_enabled") is True

    isolated_config.set("ocr_lang", 123)
    assert isolated_config.get("ocr_lang") == "chi_sim+eng"

    # 合法写入仍然生效
    isolated_config.set("ocr_lang", "eng")
    assert isolated_config.get("ocr_lang") == "eng"


# ---------- 剪贴板 ----------

def test_clipboard_text_roundtrip():
    """文字必须真正进入剪贴板，并能原样读回（注意：会覆盖当前剪贴板）"""
    import win32clipboard
    from clipboard_manager import ClipboardManager

    assert ClipboardManager.copy_text("Hello Test") is True

    win32clipboard.OpenClipboard()
    try:
        assert win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) == "Hello Test"
    finally:
        win32clipboard.CloseClipboard()


# ---------- OCR 引擎 ----------

def test_ocr_engine_factory():
    """工厂必须返回 Tesseract 后端"""
    from ocr_engine import create_ocr_engine, TesseractBackend

    engine = create_ocr_engine("tesseract")
    assert isinstance(engine, TesseractBackend)
    assert engine.name == "tesseract"


def test_ocr_preprocess_is_engine_independent():
    """预处理必须能脱离 Tesseract 单独验证：灰度 + 小图放大"""
    from ocr_engine import TesseractBackend

    src = Image.new('RGB', (100, 100), color='white')
    out = TesseractBackend._preprocess(src)

    assert out.mode == 'L'            # 已转灰度
    assert out.size == (200, 200)     # 小图放大 2 倍


def test_ocr_preprocess_leaves_large_image_unscaled():
    """大图不应被放大，避免无谓的耗时与内存"""
    from ocr_engine import TesseractBackend

    src = Image.new('RGB', (1200, 1200), color='white')
    out = TesseractBackend._preprocess(src)

    assert out.size == (1200, 1200)


def test_ocr_failure_raises_instead_of_faking_result(monkeypatch):
    """识别失败必须抛 OcrError。

    回归防护：旧实现会把异常吞掉并返回 "识别失败: ..." 字符串，
    导致错误信息被当成识别文字显示给用户。

    这里必须**强制引擎失败**：在装有 Tesseract 的机器上走成功路径时，
    原来的写法两条断言都成立，测试恒过、形同虚设。
    """
    import pytesseract

    from ocr_engine import TesseractBackend, OcrError

    def boom(*args, **kwargs):
        raise RuntimeError("simulated engine failure")

    monkeypatch.setattr(pytesseract, "image_to_string", boom)

    backend = TesseractBackend()
    with pytest.raises(OcrError) as excinfo:
        backend.recognize(Image.new('RGB', (60, 20), color='white'))

    assert "识别失败" not in str(excinfo.value)   # 不得伪装成识别结果
    assert excinfo.value.kind == "other"


def test_ocr_success_path_returns_engine_text(monkeypatch):
    """成功路径必须原样返回引擎结果（去掉首尾空白）"""
    import pytesseract

    from ocr_engine import TesseractBackend

    monkeypatch.setattr(pytesseract, "image_to_string", lambda *a, **k: "  hello  ")

    assert TesseractBackend().recognize(Image.new('RGB', (60, 20), color='white')) == "hello"


def test_tesseract_subprocess_never_creates_a_console_window(monkeypatch):
    """回归防护：Tesseract 子进程必须用 CREATE_NO_WINDOW 启动。

    本程序是 GUI 进程（pythonw / PyInstaller --noconsole），自身没有控制台。
    这类进程用**裸** subprocess 调用 spawn 控制台程序时，Windows 会为子进程
    新建一个**可见**的控制台窗口 —— 用户看到的就是「识别时一个空白小窗口一闪而过」。

    pytesseract 只在 run_tesseract() 里设了 STARTF_USESHOWWINDOW + SW_HIDE，
    而 get_tesseract_version() / get_languages() 是裸调用。实测（由子进程自报
    GetConsoleWindow）：裸调用 -> 可见控制台；SW_HIDE -> 有控制台但不可见；
    CREATE_NO_WINDOW -> 根本不创建控制台。所以必须注入 CREATE_NO_WINDOW。
    """
    import subprocess as sp

    import pytesseract.pytesseract as _pt

    import ocr_engine

    # pytesseract 内部的 subprocess 必须已被替换成注入版本
    assert isinstance(_pt.subprocess, ocr_engine._HiddenSubprocess)

    # 真正走到 Popen 时必须带上 CREATE_NO_WINDOW
    seen = {}

    def spy_popen(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop before actually spawning")

    monkeypatch.setattr(sp, "Popen", spy_popen)

    with pytest.raises(RuntimeError):
        _pt.subprocess.check_output(["tesseract", "--version"])

    assert seen.get("creationflags") == sp.CREATE_NO_WINDOW
    assert seen.get("startupinfo") is not None


def test_is_available_is_cached_per_tesseract_path(monkeypatch):
    """回归防护：is_available() 必须缓存。

    OCR 窗口每次识别都会调用它，不缓存就要多 spawn 一次 tesseract
    （实测约 500ms），让 OCR 总耗时凭空翻倍。
    """
    import pytesseract

    import ocr_engine

    ocr_engine._availability_cache.clear()
    calls = []

    def fake_version():
        calls.append(1)
        return "5.5.0"

    monkeypatch.setattr(pytesseract, "get_tesseract_version", fake_version)
    monkeypatch.setattr(
        ocr_engine.config_manager, "get",
        lambda key, default=None: r"X:\tesseract.exe" if key == "tesseract_path" else default,
    )

    try:
        engine = ocr_engine.TesseractBackend()
        assert engine.is_available() is True
        assert engine.is_available() is True
        assert len(calls) == 1, "第二次调用必须命中缓存，不能再 spawn 一次 tesseract"

        # 路径变化时必须重新检查（用户在「指定路径」引导里改过 tesseract.exe）
        monkeypatch.setattr(
            ocr_engine.config_manager, "get",
            lambda key, default=None: r"Y:\tesseract.exe" if key == "tesseract_path" else default,
        )
        assert ocr_engine.TesseractBackend().is_available() is True
        assert len(calls) == 2
    finally:
        ocr_engine._availability_cache.clear()


def test_ocr_error_kind_classification():
    """错误必须被正确归类，UI 才能给出对应的修复引导"""
    from ocr_engine import TesseractBackend

    classify = TesseractBackend._classify_error
    assert classify(RuntimeError("tesseract is not installed or it's not in your PATH")) == "not_found"
    assert classify(RuntimeError("Failed loading language 'chi_sim'")) == "lang_pack"
    assert classify(RuntimeError("Error opening data file /x/tessdata/eng.traineddata")) == "lang_pack"
    assert classify(RuntimeError("something else entirely")) == "other"


# ---------- 翻译历史迁移 ----------

def test_translator_migration_is_explicit(tmp_path, monkeypatch):
    """构造 Translator 不得产生文件副作用；迁移必须显式调用。

    回归防护：迁移曾放在 __init__ 里，导致任何 ``import translator``
    （测试、自检、IDE 索引）都会往用户配置目录写文件。
    """
    import translator as translator_module
    from translator import Translator

    cfg = tmp_path / "cfg"
    legacy_dir = tmp_path / "legacy"
    cfg.mkdir()
    legacy_dir.mkdir()
    (legacy_dir / "translation_history.json").write_text(
        '[{"time": "t", "from": "zh", "to": "en", "original": "a", "translated": "b"}]',
        encoding="utf-8",
    )

    # 让程序目录候选失效，确保只有 CWD 候选命中
    monkeypatch.setattr(translator_module.config_manager, "base_path", str(tmp_path / "nope"))

    target = cfg / "translation_history.json"
    t = Translator(history_file=str(target))
    assert not target.exists(), "构造 Translator 不应产生文件副作用"

    monkeypatch.chdir(legacy_dir)
    assert t.migrate_legacy_history() is True
    assert target.exists()
    assert len(t.history) == 1

    # 目标已存在时不得重复迁移
    assert t.migrate_legacy_history() is False


def test_translator_does_not_import_the_heavy_engine_at_module_level(tmp_path):
    """回归防护：translator 模块不得在导入期加载 translators。

    translators 的依赖树极重：实测 import 耗时约 **2.4 秒**、工作集 **+48MB**，
    占整个程序内存的 80%（它一次拖进 aiohttp / httpx / niquests / requests
    四套 HTTP 客户端，外加 cryptography、lxml、multiprocess、psutil 等）。
    而翻译只是 OCR 之后的次要功能，多数会话根本用不到。

    一旦有人在 translator.py 顶层写回 ``import translators``，
    每次启动都会白付这份内存和 2.4 秒延迟。

    必须开子进程验证：同进程内 translators 可能已被别的测试导入，断言会失真。
    用临时 APPDATA 保证不碰用户真实配置目录。
    """
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import translator\n"
        "assert 'translators' not in sys.modules, "
        "'translators 在 translator 模块导入期就被加载了'\n"
        "assert translator._translators_module is None, "
        "'延迟加载缓存不应在导入期被填充'\n"
        "print('OK')\n"
    )
    env = dict(os.environ, APPDATA=str(tmp_path), PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=180,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "OK" in result.stdout


# ---------- 主题与自绘控件 ----------

def test_px_converts_logical_pixels_by_dpi():
    """``px()`` 必须按 DPI 换算。

    回归防护：Tk 的 ``padx``/``pady``/``width`` 单位是**物理像素**，而设计稿上的间距
    是逻辑像素。不换算的话，在 150% 缩放的屏幕上间距会缩水三分之一，界面显得挤。
    """
    from ui_theme import px

    class FakeWidget:
        def __init__(self, dpi):
            self._dpi = dpi

        def winfo_fpixels(self, _spec):
            return self._dpi

    assert px(FakeWidget(96), 12) == 12      # 100%
    assert px(FakeWidget(144), 12) == 18     # 150%
    assert px(FakeWidget(192), 12) == 24     # 200%
    # 再小的值也不能算出 0，否则控件会被压没
    assert px(FakeWidget(96), 0) == 1


def test_px_falls_back_to_one_when_dpi_is_unavailable():
    """取不到 DPI 时必须保守回退，不能抛异常把界面初始化打断"""
    from ui_theme import dpi_scale, px

    class BrokenWidget:
        def winfo_fpixels(self, _spec):
            raise RuntimeError("no display")

    assert dpi_scale(BrokenWidget()) == 1.0
    assert px(BrokenWidget(), 10) == 10


def test_light_and_dark_themes_define_the_same_fields():
    """回归防护：新增主题令牌时漏改其中一个是最容易犯的错。

    ``Theme`` 是无默认值的 frozen dataclass，漏掉字段会在构造时就报错；
    但"两边都定义了、只是某一边忘了调整取值"只能靠这条测试兜住 ——
    这里至少保证字段集合完全一致。
    """
    from ui_theme import DARK, LIGHT

    assert set(vars(LIGHT)) == set(vars(DARK))
    # 每个字段都必须是非空的颜色/数值，不能留空字符串
    for name, value in vars(LIGHT).items():
        assert value != "", f"LIGHT.{name} 是空的"
    for name, value in vars(DARK).items():
        assert value != "", f"DARK.{name} 是空的"


def test_readable_on_picks_a_contrasting_foreground():
    """压在强调色上的文字颜色必须按亮度自动选，不能写死白色。

    系统强调色是用户可改的（实测本机是紫色），浅色强调色上压白字会看不清。
    """
    from ui_theme import readable_on

    assert readable_on("#000000") == "#FFFFFF"
    assert readable_on("#FFFFFF") == "#1A1A1A"
    assert readable_on("#FFD700") == "#1A1A1A"   # 亮黄必须配深色字


def test_accent_variants_are_distinct_and_follow_the_system_color():
    """强调色的派生值（悬停/按下/浅底/文字色）必须彼此不同，且跟随系统强调色变化"""
    from ui_theme import ThemeManager

    tm = ThemeManager()
    tm.update(is_dark=True, accent_color="#0078D4")
    blue = (tm.accent, tm.accent_hover, tm.accent_pressed, tm.accent_soft,
            tm.accent_border, tm.accent_text)
    assert len(set(blue)) == len(blue), "派生色之间不应重合，否则看不出悬停/选中状态"

    tm.update(is_dark=True, accent_color="#C239B3")
    magenta = (tm.accent, tm.accent_hover, tm.accent_pressed, tm.accent_soft,
               tm.accent_border, tm.accent_text)
    assert magenta != blue, "换了系统强调色，派生值必须跟着变"

    # 明暗主题下同一个强调色要派生出不同的值（深色底上要提亮）
    tm.update(is_dark=False, accent_color="#0078D4")
    light_accent = tm.accent
    tm.update(is_dark=True, accent_color="#0078D4")
    assert tm.accent != light_accent


def test_ui_font_family_is_actually_installed(tk_root):
    """回归防护：``FONT_FAMILY`` 必须是系统里真实存在的字体。

    Tk 对不存在的字体名**不会报错**，只会静默回退到默认字体 —— 而默认字体没有中文
    字形，于是中英文混排时字重、字距、基线都不一致（这正是原来用 "Segoe UI" 时的
    症状：截图里中文明显比英文粗）。实测本机只有 "Microsoft YaHei UI"，
    "Microsoft YaHei" 这个名字并不存在，改错了会静默退化。
    """
    import tkinter.font as tkfont

    from ui_theme import FONT_FAMILY

    assert FONT_FAMILY in set(tkfont.families(tk_root)), (
        f"{FONT_FAMILY!r} 不在系统字体列表里，Tk 会静默回退，中文字形会不一致"
    )


def test_rounded_card_padding_never_covers_the_corners(tk_root):
    """回归防护：卡片内容的内缩量必须 >= 圆角半径。

    Tk 没有 border-radius，圆角是画在 Canvas 上、内容控件叠在上面的。内容控件是直角的，
    内缩量一旦小于半径，四个圆角就会被内容盖住，卡片看起来又变回方角。
    """
    from ui_theme import px
    from ui_widgets import RoundedCard

    card = RoundedCard(tk_root, radius=12, padding=2)   # 故意给一个过小的 padding
    try:
        assert card.padding >= px(card, 12)
    finally:
        card.destroy()


def test_rounded_card_does_not_inflate_its_parent_request(tk_root):
    """回归防护：``RoundedCard`` 不得虚报请求尺寸。

    Tk 的 Canvas 默认请求尺寸是 **570x400**，而 Canvas 的请求尺寸会传播到外层 Frame。
    于是"包着卡片的容器"会声称自己要 396px 高，在窗口不够高时把空间吃光，排在它之后
    打包的兄弟控件（实测是状态栏）被压成 0 高度、``winfo_ismapped()`` 变 0。
    这条测试直接盯住请求尺寸本身，比在窗口层面断言更贴近根因。
    """
    from ui_widgets import RoundedCard

    card = RoundedCard(tk_root, radius=8, padding=12)
    try:
        card.update_idletasks()
        assert card.winfo_reqheight() < 100, (
            f"RoundedCard 请求了 {card.winfo_reqheight()}px 高度，"
            "说明 Canvas 的默认请求尺寸没有被压掉"
        )
        assert card.winfo_reqwidth() < 100
    finally:
        card.destroy()


def test_rounded_card_fit_to_content_shrinks_to_the_body(tk_root):
    """工具栏依赖 ``fit_to_content`` 由内容决定窗口大小，它必须真的生效"""
    import tkinter as tk

    from ui_widgets import RoundedCard

    card = RoundedCard(tk_root, radius=8, padding=8)
    try:
        tk.Label(card.body, text="钉住 识字 复制").pack()
        w, h = card.fit_to_content()
        assert w == card.body.winfo_reqwidth() + card.padding * 2
        assert h == card.body.winfo_reqheight() + card.padding * 2
        assert card.canvas.winfo_reqwidth() == w
        assert card.canvas.winfo_reqheight() == h
    finally:
        card.destroy()


def test_thin_scrollbar_hides_thumb_when_content_fits(tk_root):
    """滚动条必须自绘、且内容不满一屏时不画滑块。

    回归防护：``tk.Scrollbar`` 一定带上下箭头按钮，正是"原生 Python 模样"最刺眼的来源；
    ``ttk.Scrollbar`` 在 Windows 上又受原生主题限制、做不出细圆角滑块。
    """
    import tkinter as tk

    from ui_widgets import ThinScrollbar

    host = tk.Toplevel(tk_root)
    try:
        sb = ThinScrollbar(host, thickness=6)
        sb.pack(fill="both", expand=True)
        host.geometry("120x200")
        host.update()

        sb.set(0.0, 1.0)                      # 内容没超出一屏
        assert sb._thumb_geom == (0, 0), "内容没超出一屏时不该画滑块"

        sb.set(0.0, 0.25)                     # 超出 -> 必须画出滑块
        assert sb._thumb_geom[1] > 0, "内容超出时滑块必须可见"
        assert sb._thumb_geom[1] < 200, "滑块高度应正比于可见比例"

        # 滑块位置必须随 first 变化（否则拖不动）
        top_before = sb._thumb_geom[0]
        sb.set(0.5, 0.75)
        assert sb._thumb_geom[0] > top_before
    finally:
        host.destroy()
