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
