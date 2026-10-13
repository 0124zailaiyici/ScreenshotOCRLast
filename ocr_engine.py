import os
import subprocess

import pytesseract
from PIL import Image, ImageFilter, ImageEnhance
from config import config_manager


# ---------------------------------------------------------------------------
# 抑制 Tesseract 子进程的控制台窗口
#
# 本程序是 GUI 进程（pythonw / PyInstaller --noconsole），自身没有控制台。
# 这类进程 spawn 一个控制台程序时，Windows 会为子进程**新建一个控制台窗口**。
# 用裸 subprocess 调用时这个窗口是**可见**的，用户会看到"空白小窗口一闪而过"。
#
# pytesseract 只在 run_tesseract() 里设了 STARTF_USESHOWWINDOW + SW_HIDE，
# 而 get_tesseract_version() 和 get_languages() 用的是裸 subprocess 调用，
# 完全没有任何抑制。实测（由子进程自报 GetConsoleWindow）：
#
#     裸调用            -> 有控制台窗口，IsWindowVisible = True   <-- 一闪而过的窗口
#     SW_HIDE           -> 有控制台窗口，IsWindowVisible = False
#     CREATE_NO_WINDOW  -> 根本没有控制台窗口
#
# 也就是说 CREATE_NO_WINDOW 才是唯一可靠的手段，因此这里把 pytesseract
# 内部使用的 subprocess 整体替换成会注入该标志的转发对象。
# ---------------------------------------------------------------------------

def _no_window_kwargs():
    """返回让子进程不创建控制台窗口的 Popen 参数（Windows 专用）。"""
    kwargs = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


class _HiddenSubprocess:
    """转发 subprocess 模块，但为每个子进程调用注入「不创建窗口」的参数。

    只包装会创建进程的入口；`PIPE` / `DEVNULL` / `TimeoutExpired` 等常量与
    异常类型通过 ``__getattr__`` 原样透传，保证 pytesseract 的既有用法不受影响。
    """

    _WRAPPED = ("Popen", "run", "call", "check_call", "check_output")

    def __init__(self, module):
        self._module = module
        for name in self._WRAPPED:
            if hasattr(module, name):
                setattr(self, name, self._make(name))

    def _make(self, name):
        real = getattr(self._module, name)

        def wrapper(*args, **kwargs):
            for key, value in _no_window_kwargs().items():
                kwargs.setdefault(key, value)
            return real(*args, **kwargs)

        wrapper.__name__ = name
        return wrapper

    def __getattr__(self, name):
        return getattr(self._module, name)


def _silence_tesseract_console():
    """把 pytesseract 内部用到的 subprocess 换成不弹控制台的版本。"""
    import pytesseract.pytesseract as _pt

    if not isinstance(getattr(_pt, "subprocess", None), _HiddenSubprocess):
        _pt.subprocess = _HiddenSubprocess(subprocess)


_silence_tesseract_console()

# is_available() 的结果按可执行文件路径缓存，避免每次识别都多 spawn 一次 tesseract
_availability_cache = {}


class OcrError(RuntimeError):
    """OCR 识别失败。

    识别失败必须向上抛出，由调用方展示给用户；绝不能被伪装成
    一个形如 "识别失败: ..." 的字符串混进识别结果里。

    :param kind: 失败类别，供调用方选择对应的修复引导
        - ``"not_found"``: 找不到 Tesseract 可执行文件
        - ``"lang_pack"``: 缺少识别语言包
        - ``"other"``:     其它
    """

    def __init__(self, message, kind="other"):
        super().__init__(message)
        self.kind = kind


class OcrBackend:
    """OCR 后端抽象基类"""
    def recognize(self, image: Image.Image) -> str:
        raise NotImplementedError
    
    def is_available(self) -> bool:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

class TesseractBackend(OcrBackend):
    """Tesseract OCR 后端实现"""

    def __init__(self):
        self._update_path()

    def _update_path(self):
        """从配置更新 Tesseract 可执行文件路径，若无配置则尝试自动搜索"""
        path = config_manager.get("tesseract_path")
        
        # 如果配置为空，尝试在 Windows 常见安装路径下搜索
        if not path:
            common_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Tesseract-OCR\tesseract.exe")
            ]
            for p in common_paths:
                if os.path.exists(p):
                    path = p
                    config_manager.set("tesseract_path", p) # 自动保存找到的路径
                    break
        
        if path:
            pytesseract.pytesseract.tesseract_cmd = path

    def is_available(self) -> bool:
        """检查 Tesseract 是否可用

        结果按可执行文件路径缓存：OCR 窗口每次识别都会调用本方法，
        不缓存的话每次识别都要额外 spawn 一次 tesseract（实测约 500ms），
        让 OCR 总耗时凭空翻倍。

        用户在「指定 tesseract.exe 路径」引导里改过路径后，缓存键会变化，
        因此会立刻重新检查，不需要重启程序。
        """
        self._update_path()
        cmd = pytesseract.pytesseract.tesseract_cmd
        if cmd in _availability_cache:
            return _availability_cache[cmd]

        try:
            pytesseract.get_tesseract_version()
            available = True
        except Exception:
            available = False

        _availability_cache[cmd] = available
        return available

    @staticmethod
    def _preprocess(image: Image.Image) -> Image.Image:
        """图像预处理：灰度 → 小图放大 → 对比度拉伸 → 锐化

        与识别引擎解耦，便于在未安装 Tesseract 的环境中单独测试。
        """
        processed = image.convert('L')

        # 自动放大：针对小图提高识别率
        w, h = processed.size
        if w < 1000 or h < 1000:
            processed = processed.resize((w * 2, h * 2), Image.Resampling.LANCZOS)

        # 增强对比度
        processed = ImageEnhance.Contrast(processed).enhance(2.0)

        # 锐化
        return processed.filter(ImageFilter.SHARPEN)

    @staticmethod
    def _classify_error(exc) -> str:
        """把底层异常归类，供 UI 选择对应的修复引导"""
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        if "tesseractnotfound" in name or "not installed" in text or "not in your path" in text:
            return "not_found"
        if ("failed loading language" in text or "tessdata" in text
                or "error opening data file" in text):
            return "lang_pack"
        return "other"

    def recognize(self, image: Image.Image) -> str:
        """识别图片中的文字

        :raises OcrError: 识别过程失败（引擎缺失、语言包缺失等）
        """
        try:
            processed_img = self._preprocess(image)
            lang = config_manager.get("ocr_lang") or "chi_sim+eng"
            return pytesseract.image_to_string(processed_img, lang=lang).strip()
        except Exception as e:
            raise OcrError(
                f"Tesseract 识别出错: {e}", kind=self._classify_error(e)
            ) from e

    @property
    def name(self) -> str:
        return "tesseract"

def create_ocr_engine(backend_name="tesseract"):
    """OCR 引擎工厂函数"""
    if backend_name == "tesseract":
        return TesseractBackend()
    # 未来可扩展其他后端 (如 paddleocr, baidu_api 等)
    return TesseractBackend()
