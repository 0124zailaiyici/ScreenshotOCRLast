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


def test_translator_pins_the_region_before_importing_translators(monkeypatch):
    """回归防护：导入 translators **之前**必须先钉住地区。

    踩过的坑：``import translators`` 会在**导入期发网络请求**探测所在地区 ——
    它的模块体里直接写了 ``tss = TranslatorsServer()``（server.py:6205），
    构造函数调用 ``get_region_of_server()``（server.py:5896），后者请求
    geolocation.onetrust.com、失败再退到 httpbin.org（server.py:364）。
    于是：

    - 探测失败会抛 ``TranslatorError``，**整个 import 直接失败** —— 用户点
      「翻译」看到的是一个跟 httpbin.org 有关的报错（实测 25 次独立进程里挂 2 次）；
    - 那两次 ``requests.get`` **没有设 timeout**，网络不通时可能挂很久。

    ``server.py:344`` 留了逃生口：``translators_default_region`` 有值就直接返回、
    不发任何请求。所以必须在 import 之前把它设好 —— 顺序错了就等于没修。
    """
    import builtins

    import translator as translator_module

    monkeypatch.delenv("translators_default_region", raising=False)
    monkeypatch.setattr(translator_module, "_translators_module", None)

    seen = {}
    fake = type("FakeTranslators", (), {})()

    real_import = builtins.__import__

    def spy_import(name, *args, **kwargs):
        if name == "translators":
            # 记录"导入发生的那一刻"环境变量的值
            seen["region"] = os.environ.get("translators_default_region")
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", spy_import)

    assert translator_module._translators() is fake
    assert seen.get("region") == translator_module._DEFAULT_REGION, (
        "translators 是在地区被钉住之前导入的 —— 它会在导入期发网络请求，"
        "网络一抖整个 import 就失败"
    )


def test_translator_does_not_override_a_user_chosen_region(monkeypatch):
    """用户自己设了 ``translators_default_region`` 就必须尊重，不能被覆盖成 CN。

    非中国大陆的用户可以设 ``EN`` 来使用国际版后端，钉地区只应该是兜底默认值。
    """
    import builtins

    import translator as translator_module

    monkeypatch.setenv("translators_default_region", "EN")
    monkeypatch.setattr(translator_module, "_translators_module", None)

    fake = type("FakeTranslators", (), {})()
    real_import = builtins.__import__

    def spy_import(name, *args, **kwargs):
        if name == "translators":
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", spy_import)

    translator_module._translators()
    assert os.environ["translators_default_region"] == "EN"


def test_translator_loads_without_any_network(tmp_path):
    """回归防护：**断网时翻译栈也必须能加载**。

    这条是上面那条的端到端版本，也是最有力的证据 —— 不模拟"网络慢"，而是把
    ``socket.socket`` 直接换成连接必抛异常的类，任何真实网络请求都必然失败。

    修复前实测：``translator._translators()`` 抛
    ``TranslatorError: Unable to connect the Internet. Try
    os.environ["translators_default_region"] = "EN" or "CN" before import translators``
    —— 用户点「翻译」看到的就是这个跟 httpbin.org 有关的报错。
    修复后实测：1.15 秒导入成功。

    必须开子进程：同进程内 translators 可能已被别的测试导入，断言会失真。
    """
    import subprocess
    import sys

    code = (
        "import socket, sys\n"
        "class _Blocked(socket.socket):\n"
        "    def connect(self, *a, **k):\n"
        "        raise OSError('network blocked by test')\n"
        "socket.socket = _Blocked\n"
        "socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(\n"
        "    OSError('network blocked by test'))\n"
        "import translator\n"
        "translator._translators()\n"
        "print('OK')\n"
    )
    env = dict(os.environ, APPDATA=str(tmp_path), PYTHONIOENCODING="utf-8")
    env.pop("translators_default_region", None)  # 模拟用户没自己设过
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=300,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env,
    )
    assert result.returncode == 0, (
        "断网时 translators 加载失败 —— 它在导入期发了网络请求。\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
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

    Tk 的 Canvas 默认请求尺寸很大 —— 实测 **382x268**（100% DPI），随显示器缩放线性
    放大（150% 下约 573x402）。Canvas 的请求尺寸会传播到外层 Frame，于是"包着卡片的
    容器"会声称自己要几百像素高，在窗口不够高时把空间吃光，排在它之后打包的兄弟控件
    （实测是状态栏）被压成 0 高度、``winfo_ismapped()`` 变 0。

    这条测试直接盯住请求尺寸本身，比在窗口层面断言更贴近根因。

    断言写成 ``<= 2`` 而不是某个"看着挺小"的数（比如 100）：``RoundedCard`` 里
    Canvas 被显式设成 1x1，真实值就是 **1**，留 100 的余量等于放任它虚报 99px。
    """
    from ui_widgets import RoundedCard

    card = RoundedCard(tk_root, radius=8, padding=12)
    try:
        card.update_idletasks()
        assert card.winfo_reqheight() <= 2, (
            f"RoundedCard 请求了 {card.winfo_reqheight()}px 高度，"
            "说明 Canvas 的默认请求尺寸没有被压掉"
        )
        assert card.winfo_reqwidth() <= 2, (
            f"RoundedCard 请求了 {card.winfo_reqwidth()}px 宽度"
        )
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


def test_scrollbar_drag_survives_the_pointer_leaving(tk_root):
    """回归防护：拖动滑块时指针离开控件，不得中断拖动。

    滚动条只有 thickness 像素宽（150% DPI 下 9px），垂直拖动时指针稍一横向漂移就会
    触发 ``<Leave>``。旧实现把 ``_drag`` 清掉，拖动直接断掉（或要等指针回到条上才继续）。
    拖动只应由 ``<ButtonRelease-1>`` 结束。
    """
    import tkinter as tk

    from ui_widgets import ThinScrollbar

    host = tk.Toplevel(tk_root)
    try:
        moved = []
        sb = ThinScrollbar(host, thickness=6, command=lambda *a: moved.append(a))
        sb.pack(fill="both", expand=True)
        host.geometry("120x200")
        host.update()
        sb.set(0.0, 0.25)          # 内容超出一屏，滑块可见
        sb.update()

        class _Evt:
            def __init__(self, y):
                self.y = y

        top, thumb_h = sb._thumb_geom
        sb._on_press(_Evt(top + thumb_h // 2))
        assert sb._drag is not None, "按在滑块上应当开始拖动"

        sb._on_leave(_Evt(0))      # 指针横向漂移离开控件
        assert sb._drag is not None, "指针离开控件后拖动被中断了"

        sb._on_motion(_Evt(top + thumb_h // 2 + 20))
        assert moved, "离开控件后继续拖动应当仍然产生滚动"

        sb._on_release(_Evt(0))
        assert sb._drag is None, "松开按键后拖动必须结束"
    finally:
        host.destroy()


# ---------- 配置：pinned_items 的元素级校验 ----------

def test_sanitize_cleans_pinned_items_not_just_the_container():
    """回归防护：``_sanitize`` 必须逐元素校验 ``pinned_items``。

    只做 ``isinstance(value, list)`` 是不够的 —— 消费方（``pin_window``）对每个元素都
    直接调 ``item.get(...)``。列表里混进一个字符串，点「钉住」就会抛
    ``AttributeError: 'str' object has no attribute 'get'``，而这个异常被
    ``main._do_screenshot`` 的 except 吞掉：窗口不出现、也没有任何提示。

    ``pinned_items`` 是 ``_SCHEMA`` 里唯一有结构的字段，也是唯一需要逐元素校验的。
    """
    from config import ConfigManager

    # 不跑 __init__，避免在测试里建目录
    cm = ConfigManager.__new__(ConfigManager)

    clean = cm._sanitize({
        "hotkey": "<alt>+x",
        "pinned_items": ["junk", 123, None, ["nested"], {"id": "ok", "path": "x"}],
    })

    assert clean["hotkey"] == "<alt>+x"
    assert clean["pinned_items"] == [{"id": "ok", "path": "x"}], \
        "非 dict 元素必须被丢掉，形状正确的 dict 必须原样保留"


def test_dirty_pinned_items_are_dropped_at_load(tmp_path):
    """端到端：脏配置文件读进来后，消费方拿到的必须是形状正确的 dict"""
    import json as _json

    from config import ConfigManager

    cfg_dir = tmp_path / "ScreenshotOCR"
    cfg_dir.mkdir()
    (cfg_dir / "screenshot_ocr_config.json").write_text(_json.dumps({
        "pinned_items": [
            "junk", 123, None,
            {"id": "good", "path": "x", "pos": [1, 2]},
            {"id": "badpos", "path": "y", "pos": "not-a-pair"},
            {"id": "badpos2", "path": "z", "pos": [1, "two"]},
            {"id": "badpos3", "path": "w", "pos": [1, 2, 3]},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    cm = ConfigManager(config_dir=str(cfg_dir))
    items = cm.get_pinned_items()

    assert all(isinstance(i, dict) for i in items), "get_pinned_items 必须只返回 dict"
    assert [i["id"] for i in items] == ["good", "badpos", "badpos2", "badpos3"], \
        "坏坐标只该丢字段，不该把整条钉住记录扔掉（否则用户的钉住会无声消失）"
    assert items[0]["pos"] == [1, 2]
    for item in items[1:]:
        assert "pos" not in item, f"{item['id']} 的坏 pos 没有被清掉"


def test_set_pinned_items_refuses_to_write_malformed_entries(tmp_path):
    """写入边界同样要清洗：坏数据不该被落盘"""
    import json as _json

    from config import ConfigManager

    cm = ConfigManager(config_dir=str(tmp_path / "ScreenshotOCR"))
    cm.set_pinned_items(["junk", {"id": "ok"}, 42])

    assert cm.get_pinned_items() == [{"id": "ok"}]
    with open(cm.config_path, encoding="utf-8") as f:
        assert _json.load(f)["pinned_items"] == [{"id": "ok"}]


# ---------- 测试隔离 ----------

def test_isolated_config_redirects_the_translator_singleton(isolated_config):
    """回归防护：``isolated_config`` 必须把 ``translator`` 也隔离掉。

    ``translator`` 在**导入期**就执行了 ``from config import config_manager``，并当场
    构造模块级单例 ``Translator()`` —— 而 ``Translator.__init__`` 会把
    ``config_manager.config_dir`` 算成 ``history_file``。测试模块在**收集期**就
    ``from ocr_window import OcrWindow``，连带导入 ``translator``，那时 fixture 还没运行，
    单例已经抓住了**用户真实目录**。

    所以只 ``setattr(translator, "config_manager", cm)`` 是不够的，必须把单例上
    已经算好的 ``history_file`` 一起重定向。否则从"隔离"上下文调用 ``_save_history()``
    会真的写进 ``%APPDATA%/ScreenshotOCR/translation_history.json``。
    """
    import os

    import translator as translator_module

    singleton = translator_module.translator

    assert translator_module.config_manager is isolated_config, \
        "translator 模块上的 config_manager 没被隔离"
    assert singleton.history_file.startswith(isolated_config.config_dir), \
        f"单例的 history_file 仍指向 {singleton.history_file}"

    real_hist = os.path.join(
        os.environ.get("APPDATA", ""), "ScreenshotOCR", "translation_history.json")

    def _snapshot():
        if not os.path.exists(real_hist):
            return None
        with open(real_hist, encoding="utf-8") as f:
            return f.read()

    before = _snapshot()
    singleton._save_history("隔离测试原文", "隔离测试译文", "zh", "en")
    after = _snapshot()

    assert before == after, "隔离测试把翻译历史写进了用户真实目录"
    assert os.path.exists(singleton.history_file), "应该写进临时目录"


# ---------- 图标缓存 ----------

def test_icon_cache_invalidates_when_the_root_is_destroyed():
    """回归防护：``_sync`` 必须识别出「解释器已被销毁」。

    ``Misc._root()`` 只是纯 Python 的属性遍历 —— 一个已经被 ``destroy()`` 的 root
    仍然等于它自己。只比对身份的话会命中旧缓存，返回上一轮那个已被 Tcl 删除的
    ``PhotoImage``，等到把它配到某个活控件时才炸成
    ``TclError: image "pyimageN" doesn't exist`` —— 报错位置离真正的原因很远，
    正是 ``IconProvider`` 的 docstring 声称要防的错误。

    修复后的行为：当场抛一个说得清的 ``RuntimeError``，并把缓存清干净。
    """
    import tkinter as tk

    import pytest as _pytest

    from ui_icons import IconProvider

    provider = IconProvider()
    victim = tk.Tk()
    victim.withdraw()
    try:
        provider.get_pin("#FFFFFF", master=victim)
        assert provider._cache_root is victim
        assert provider._cache, "第一次调用应该填充了缓存"

        victim.destroy()

        # 再向那个已销毁的控件要图标：必须当场报错，而不是返回死句柄
        with _pytest.raises(RuntimeError, match="已被销毁"):
            provider.get_pin("#FFFFFF", master=victim)

        assert provider._cache_root is None, "发现解释器已死时必须清掉缓存归属"
        assert not provider._cache, "死句柄不得留在缓存里"
    finally:
        try:
            victim.destroy()
        except tk.TclError:
            pass


def test_icon_cache_still_works_with_fake_widgets():
    """回归防护：没有 ``winfo_exists`` 的假控件不能被误判成"已销毁"。

    ``test_integration.py::test_icon_cache_is_keyed_on_the_calling_widget_root``
    用假控件直接测 ``_sync``（避免在测试里建多个 Tk 解释器）。存活检查不能把这类
    对象当成死的 —— 它们根本没有解释器可谈。
    """
    from ui_icons import IconProvider

    class _FakeRoot:
        pass

    class _FakeWidget:
        def __init__(self, root):
            self._r = root

        def _root(self):
            return self._r

    fake_root = _FakeRoot()
    provider = IconProvider()
    assert provider._sync(_FakeWidget(fake_root)) is fake_root


def test_is_alive_reports_a_destroyed_interpreter_as_dead():
    """``_is_alive`` 的判定逻辑：``winfo_exists()`` 抛 TclError 就是已销毁"""
    import tkinter as tk

    from ui_icons import IconProvider

    class _DeadRoot:
        def winfo_exists(self):
            raise tk.TclError(
                'can\'t invoke "winfo" command: application has been destroyed')

    class _LiveRoot:
        def winfo_exists(self):
            return 1

    assert IconProvider._is_alive(_LiveRoot()) is True
    assert IconProvider._is_alive(_DeadRoot()) is False


def test_round_rect_has_four_symmetric_corners(tk_root):
    """回归防护：圆角矩形必须四角一致，且圆角深度随半径增长。

    踩过的坑：``round_rect`` 原来用 ``create_polygon(..., smooth=True)``。Tk 的
    ``smooth`` 是 B 样条，曲线**不经过**给定点，圆角量由相邻点间距决定，而不是由传入
    的 ``r`` 决定。实测（真实渲染后逐像素数左上角挖掉的像素数）：

        请求半径 r=4 / 8 / 12 / 20  ->  35 / 36 / 38 / 47   （几乎不随半径变化）
        同一图形的右下角            ->   0 /  1 /  3 / 12   （基本是直角）

    也就是说它画的根本不是"半径 r 的圆角"，而且**上面圆、下面方** —— 一个看起来
    像坏掉的窗口。这个函数被 ``RoundedCard``（OCR 窗口的文本卡片、截图工具栏）共用，
    所以影响面是整个 UI，不只是某一个窗口。

    **本测试的能力边界（别高估它）**：旧写法的**点集本身是对称的**，不对称是
    ``smooth=True`` 的样条**渲染**出来的，几何断言看不到。所以这里拦的是"又退回了
    smooth=True"这个动作，靠两条：① 点数必须远超 12（显式采样圆弧）；② 圆角深度必须
    随半径增长（旧写法几乎不变）。真正的四角对称性只能靠逐像素渲染验证，
    证据记录在 ``ui_widgets.round_rect`` 的 docstring 里。
    """
    from ui_widgets import round_rect

    import tkinter as tk

    cv = tk.Canvas(tk_root, width=200, height=120)
    try:
        item = round_rect(cv, 0, 0, 200, 120, 12, fill="#000")
        coords = cv.coords(item)
        pts = list(zip(coords[0::2], coords[1::2]))
        assert len(pts) > 12, "点数太少，圆角没有被采样出来"

        cx, cy = 100.0, 60.0
        for x, y in pts:
            assert any(abs(2 * cx - x - px) < 1e-6 and abs(y - py) < 1e-6
                       for px, py in pts), \
                f"({x:.2f},{y:.2f}) 的横向镜像不在图形里 —— 左右角不对称"
            assert any(abs(x - px) < 1e-6 and abs(2 * cy - y - py) < 1e-6
                       for px, py in pts), \
                f"({x:.2f},{y:.2f}) 的纵向镜像不在图形里 —— 上下角不对称"

        # 圆角深度必须随半径增长。用"离左上角最近的那个点的 x+y"当度量：
        # 半径 r 时该点约在 (r(1-1/√2), r(1-1/√2))，所以 r 越大 x+y 越大。
        # smooth=True 的旧写法下这两个值几乎一样，会被这条断言拦下。
        near = []
        for r in (4, 20):
            it = round_rect(cv, 0, 0, 200, 120, r, fill="#000")
            c = cv.coords(it)
            near.append(min(x + y for x, y in zip(c[0::2], c[1::2])))
        assert near[1] > near[0] + 8, (
            f"半径 4 与 20 的圆角深度几乎一样（{near[0]:.2f} vs {near[1]:.2f}）—— "
            "说明圆角不是按半径画的"
        )
    finally:
        cv.destroy()

