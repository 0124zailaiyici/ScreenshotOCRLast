"""真实自检脚本：逐项验证运行环境与关键子系统。

与旧版的关键区别：这里每一项都真的执行检查，没有任何硬编码的 "OK"。
任意一项 FAIL 都会以非零退出码结束，可直接用于 CI 或交付前把关。

用法:
    python verify_app.py
"""
import os
import sys
import tempfile
import traceback


class SkipCheck(Exception):
    """该检查项依赖的外部条件不满足（例如未安装 Tesseract）。

    跳过不代表程序损坏，只代表对应功能不可用。
    """


# ---------------------------------------------------------------- 检查项

def check_python_version():
    if sys.version_info < (3, 10):
        raise AssertionError(f"需要 Python 3.10+，当前 {sys.version.split()[0]}")
    return f"Python {sys.version.split()[0]}"


def check_dependencies():
    """第三方依赖都要能导入。

    ``translators`` **不能**直接 ``importlib.import_module`` —— 它在导入期会发网络
    请求探测地区，网络一抖就抛 TranslatorError，于是这项检查会随机失败（实测
    25 次里挂 2 次）。走应用自己的 ``translator._translators()``：那条路径会先钉住
    地区，不碰网络。这样检查既稳定，测的又是应用真正使用的那条路径。
    """
    import importlib
    required = ["PIL", "pytesseract", "pystray", "pynput", "win32clipboard"]
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except Exception as e:
            missing.append(f"{mod} ({type(e).__name__})")

    # translators 走应用自己的延迟加载入口
    try:
        from translator import _translators
        _translators()
    except Exception as e:
        missing.append(f"translators ({type(e).__name__}: {e})")

    if missing:
        raise AssertionError("无法导入: " + ", ".join(missing))
    return f"{len(required) + 1} 个依赖全部可导入"


def check_config_roundtrip():
    """配置必须在隔离目录中可写可读，不触碰用户真实配置"""
    from config import ConfigManager

    with tempfile.TemporaryDirectory() as d:
        cm = ConfigManager(config_dir=d)
        cm.set("probe_key", "probe_value")
        reloaded = ConfigManager(config_dir=d)
        if reloaded.get("probe_key") != "probe_value":
            raise AssertionError("配置写入后无法读回")
    return "隔离目录读写正常"


def check_config_dir_writable():
    from config import config_manager

    probe = os.path.join(config_manager.config_dir, ".write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
    finally:
        if os.path.exists(probe):
            os.remove(probe)
    return config_manager.config_dir


def check_tk_available():
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    try:
        return f"Tcl/Tk {root.tk.call('info', 'patchlevel')}"
    finally:
        root.destroy()


def check_icon_rendering():
    """图标必须能真正渲染，且 Tk root 变化后不得复用失效句柄"""
    import tkinter

    from ui_icons import IconProvider

    provider = IconProvider()

    root_a = tkinter.Tk()
    root_a.withdraw()
    try:
        for name in ("get_pin", "get_search", "get_clipboard", "get_checkmark"):
            getattr(provider, name)("#0078D4", master=root_a)
        image_a = provider.get_pin("#0078D4", master=root_a)
    finally:
        root_a.destroy()

    root_b = tkinter.Tk()
    root_b.withdraw()
    try:
        image_b = provider.get_pin("#0078D4", master=root_b)
        if image_b is image_a:
            raise AssertionError("root 变化后仍复用了属于已销毁解释器的图标句柄")
    finally:
        root_b.destroy()

    return "4 个图标渲染正常，且随 root 变化重建"


def check_ocr_engine_factory():
    from ocr_engine import DEFAULT_BACKEND, create_ocr_engine, OcrError

    for name in ("tesseract", "rapidocr"):
        engine = create_ocr_engine(name)
        if engine.name != name:
            raise AssertionError(f"工厂返回了非预期后端: {engine.name}（请求 {name}）")
        if not hasattr(engine, "recognize"):
            raise AssertionError(f"{name} 后端缺少 recognize 接口")

    # 配置写坏时不该让识字功能整体不可用，回落到默认后端即可
    if create_ocr_engine("no_such_engine").name != DEFAULT_BACKEND:
        raise AssertionError("未知后端名没有回落到默认后端")
    return "工厂与接口正常，未知后端名可回落"


def check_tesseract_available():
    from ocr_engine import create_ocr_engine

    engine = create_ocr_engine("tesseract")
    if not engine.is_available():
        raise SkipCheck("Tesseract 未安装或路径未配置，OCR 功能不可用")
    return "Tesseract 可用"


def check_rapidocr_available():
    """RapidOCR 是默认引擎，所以它必须真的能跑 —— 不只是模块在。

    模块在、但三个 ONNX 模型没打进来，是打包时最容易犯的错（`--collect-data`
    漏了数据文件），而它的表现是"程序能启动、能切引擎，一识别就报模型找不到"。
    这里真的构造一次引擎并识别一张小图，把模型能不能加载也验掉。
    """
    from PIL import Image

    from ocr_engine import create_ocr_engine

    engine = create_ocr_engine("rapidocr")
    if not engine.is_available():
        raise SkipCheck("RapidOCR 未安装，中文识别将回落到 Tesseract")

    # 构造引擎会真的读三个 ONNX 模型，模型缺失就在这里炸
    text = engine.recognize(Image.new("RGB", (120, 40), color="white"))
    if not isinstance(text, str):
        raise AssertionError(f"recognize() 应返回字符串，实际是 {type(text).__name__}")
    return "RapidOCR 可用，模型可加载"


def check_ocr_language_packs():
    import pytesseract

    from config import config_manager
    from ocr_engine import create_ocr_engine

    # tesseract_cmd 由引擎的 _update_path() 设置。若引擎不可用，本项应跳过
    # 而不是失败 —— 否则没装 Tesseract 的机器上自检会误报为损坏。
    if not create_ocr_engine("tesseract").is_available():
        raise SkipCheck("Tesseract 不可用，无法检查语言包")

    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception as e:
        raise SkipCheck(f"无法枚举语言包: {e}")

    configured = (config_manager.get("ocr_lang") or "chi_sim+eng").split("+")
    missing = [lang for lang in configured if lang not in installed]
    if missing:
        raise AssertionError(
            f"配置的识别语言缺少语言包 {missing}；已安装: {sorted(installed)}"
        )
    return f"{'+'.join(configured)} 语言包齐全"


def check_ocr_error_contract():
    """回归防护：识别失败必须抛 OcrError，不能把错误伪装成识别结果

    必须强制引擎失败，否则在装有 Tesseract 的机器上走成功路径，本项恒过。
    """
    import pytesseract
    from PIL import Image

    from ocr_engine import TesseractBackend, OcrError

    original = pytesseract.image_to_string

    def boom(*args, **kwargs):
        raise RuntimeError("self-check simulated failure")

    pytesseract.image_to_string = boom
    try:
        try:
            text = TesseractBackend().recognize(Image.new("RGB", (40, 16), color="white"))
        except OcrError as e:
            if "识别失败" in str(e):
                raise AssertionError("OcrError 消息不应包含伪装文案")
            if e.kind != "other":
                raise AssertionError(f"错误归类异常: {e.kind}")
            return "强制失败时正确抛出 OcrError"
        raise AssertionError(f"识别失败却返回了 {text!r}，未抛 OcrError")
    finally:
        pytesseract.image_to_string = original


def check_clipboard_text():
    import win32clipboard

    from clipboard_manager import clipboard_manager

    if not clipboard_manager.copy_text("ScreenshotOCR self-check"):
        raise AssertionError("文字写入剪贴板失败")

    win32clipboard.OpenClipboard()
    try:
        got = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()

    if got != "ScreenshotOCR self-check":
        raise AssertionError(f"剪贴板读回不一致: {got!r}")
    return "CF_UNICODETEXT 往返一致"


def check_clipboard_image():
    import win32clipboard
    from PIL import Image

    from clipboard_manager import clipboard_manager

    if not clipboard_manager.copy_image(Image.new("RGB", (4, 4), color="red")):
        raise AssertionError("图片写入剪贴板失败")

    win32clipboard.OpenClipboard()
    try:
        ok = win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB)
    finally:
        win32clipboard.CloseClipboard()

    if not ok:
        raise AssertionError("剪贴板中没有 CF_DIB 数据")
    return "CF_DIB 写入成功"


def check_single_instance_ipc():
    import socket

    from main import IPC_PORT

    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", IPC_PORT)) == 0:
            return f"{IPC_PORT} 已有实例在监听（单实例 IPC 正常）"

    server = socket.socket()
    try:
        server.bind(("127.0.0.1", IPC_PORT))
    finally:
        server.close()
    return f"{IPC_PORT} 可绑定"


CHECKS = [
    ("Python 版本", check_python_version),
    ("第三方依赖", check_dependencies),
    ("配置往返", check_config_roundtrip),
    ("配置目录可写", check_config_dir_writable),
    ("Tk 可用", check_tk_available),
    ("图标渲染", check_icon_rendering),
    ("OCR 引擎工厂", check_ocr_engine_factory),
    ("Tesseract 可用", check_tesseract_available),
    ("RapidOCR 可用", check_rapidocr_available),
    ("OCR 语言包", check_ocr_language_packs),
    ("OCR 错误契约", check_ocr_error_contract),
    ("剪贴板文字", check_clipboard_text),
    ("剪贴板图片", check_clipboard_image),
    ("单实例 IPC", check_single_instance_ipc),
]


def main():
    print("ScreenshotOCR 自检")
    print("=" * 68)

    counts = {"PASS": 0, "SKIP": 0, "FAIL": 0}
    failures = []

    for name, fn in CHECKS:
        try:
            detail = fn()
            status = "PASS"
        except SkipCheck as e:
            status, detail = "SKIP", str(e)
        except Exception as e:
            status = "FAIL"
            detail = f"{type(e).__name__}: {e}"
            failures.append((name, traceback.format_exc()))

        counts[status] += 1
        print(f"[{status}] {name:<16} {detail}")

    print("=" * 68)
    print(f"PASS {counts['PASS']}  SKIP {counts['SKIP']}  FAIL {counts['FAIL']}")

    if failures:
        print("\n失败详情:")
        for name, tb in failures:
            print(f"\n--- {name} ---")
            print(tb.rstrip())

    # 注意：本自检会覆盖系统剪贴板内容
    print("\n提示：剪贴板检查项会覆盖当前剪贴板内容。")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
