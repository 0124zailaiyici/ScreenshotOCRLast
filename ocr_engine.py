import importlib.util
import os
import statistics
import subprocess

# ---------------------------------------------------------------------------
# 压掉 numpy 带进来的 OpenBLAS 线程池
#
# **必须在 import numpy 之前设置**（环境变量只在新加载时生效）。
#
# 为什么需要：``pytesseract`` 在导入期有一句 ``from numpy import ndarray``
# （包在 ``try/except ModuleNotFoundError`` 里，``pytesseract.py:35``）。
# 以前 numpy 没装，这句静默失败、没有任何代价；**现在 numpy 是 onnxruntime 的
# 硬依赖、必然装着**，于是每次启动都会真的加载 numpy，并拉起 OpenBLAS 的线程池。
# 实测空闲进程：线程 **9 → 27**、私有内存 516MB、工作集 +9MB。
#
# 这和 CLAUDE.md 里记的 pandas 陷阱是同一个坑的镜像版（pytesseract 会
# ``try: import pandas``，pandas 一装就连带 numpy + OpenBLAS）。
#
# 限制成单线程**不会拖慢识别**：推理是 onnxruntime 自己的线程池在做，numpy 只是
# 数据容器。实测 RapidOCR 单张图 1.24s → 1.17s（略快，没有变慢）。
# ---------------------------------------------------------------------------
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
             "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import pytesseract  # noqa: E402  （必须在上面那几个环境变量之后）
from PIL import Image  # noqa: E402
from config import config_manager  # noqa: E402


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
    def _otsu(image: Image.Image) -> Image.Image:
        """Otsu 全局阈值二值化（类间方差最大化）。

        自己实现而不是引入 OpenCV —— 只为这一个函数不值得多打一个几十 MB 的依赖。
        256 次直方图遍历，对截图尺寸来说开销可忽略。
        """
        hist = image.histogram()
        total = sum(hist)
        if total == 0:
            return image

        sum_all = sum(i * hist[i] for i in range(256))
        sum_bg = weight_bg = 0.0
        best_variance, threshold = -1.0, 127
        for i in range(256):
            weight_bg += hist[i]
            if weight_bg == 0:
                continue
            weight_fg = total - weight_bg
            if weight_fg == 0:
                break
            sum_bg += i * hist[i]
            mean_bg = sum_bg / weight_bg
            mean_fg = (sum_all - sum_bg) / weight_fg
            variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
            if variance > best_variance:
                best_variance, threshold = variance, i
        return image.point(lambda x: 255 if x > threshold else 0, "L")

    @staticmethod
    def _preprocess(image: Image.Image) -> Image.Image:
        """图像预处理：灰度 → 小图 2x 放大（BICUBIC）→ Otsu 二值化

        与识别引擎解耦，便于在未安装 Tesseract 的环境中单独测试。

        **不要加对比度增强，也不要加锐化。** 旧实现是「灰度 → 2x LANCZOS →
        对比度 2.0 → SHARPEN」，实测在用户的真实截图上（小字 + 中英数字混排 +
        背后有花哨插画）是**所有候选里最差的一个**：

            预处理                难图(用户实际)   好认-浅底   好认-暗底
            对比度2.0 + SHARPEN       85.4%         100%       100%   <-- 旧实现
            什么都不做                92.7%         100%       100%
            autocontrast              90.6%         100%       100%
            Otsu 二值化               96.9%         100%       100%   <-- 现在

        也就是说"增强对比度"这个直觉是错的 —— 它把细笔画糊掉，反而让 Tesseract
        的二值化更难做。在干净的合成样本上这些差异看不出来（全都是 98%+），
        必须用真实截图才测得出。

        放大倍数同理（配合 Otsu 一起测，难图 / 好认-浅底）：

            1x  81.2% / 100%     2x  96.9% / 100%     3x  96.9% / 98.6%
            4x  95.8% / 98.6%

        3x 起会把"好认的图"从 100% 拉到 98.6%，2x 不会。所以取 2x。
        """
        processed = image.convert('L')

        # 自动放大：针对小图提高识别率
        w, h = processed.size
        if w < 1000 or h < 1000:
            processed = processed.resize((w * 2, h * 2),
                                         Image.Resampling.BICUBIC)

        return TesseractBackend._otsu(processed)

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

class RapidOcrBackend(OcrBackend):
    """RapidOCR 后端（PaddleOCR 的中文模型 + ONNX Runtime）。

    为什么要有它：Tesseract 的标准 ``chi_sim`` 模型在中文上有**模型层面的上限**，
    调参救不回来。同一张用户真实截图（小字 + 中英数字混排 + 花哨背景）：

        Tesseract 最佳配置   真实**泻**染截图确认      **目**检通过      13 PASS **/0 FAILL**
        RapidOCR            真实**渲**染截图确认      **自**检通过      13 PASS **/ 0 FAIL**

    相似度都是 96.9%，但 Tesseract 错的是**汉字**（文本直接不可用），RapidOCR 错的
    只是空格（内容可恢复）—— 对用户来说这是质的区别。

    代价：EXE 体积从 36MB 涨到约 80MB，单次识别约 0.5s → 1.8s。

    **必须懒加载。** onnxruntime + 三个模型会给进程加几十 MB 工作集，而只用
    Tesseract 的用户根本用不到 —— 和 ``translator`` 的 ``translators`` 同理。
    因此 ``import rapidocr_onnxruntime`` 只出现在 ``_module()`` / ``_get_engine()`` 里，
    **绝不允许**写到模块顶层。

    **不要对它做 Tesseract 那套预处理。** 实测把图先 2x 放大再喂给 RapidOCR，
    相似度从 96.9% 掉到 **77.1%**（它内部有自己的尺寸归一化，外部放大反而干扰）。
    二值化同理。所以 ``recognize`` 直接喂原图。
    """

    #: 空格重建阈值：间隙超过「中位字宽 × 该比例」就判定为空格。
    #: **只在「中日韩 ↔ 非中日韩」的边界上判定**，拉丁文内部一律不插 ——
    #: 原因见 rebuild_spaces 的注释。
    GAP_RATIO = 0.45
    #: 间隙的绝对下限（像素）。只靠比例会在小字号图上误判。
    MIN_GAP_PX = 2

    def __init__(self):
        self._engine = None

    @staticmethod
    def _module():
        import rapidocr_onnxruntime

        return rapidocr_onnxruntime

    def is_available(self) -> bool:
        """检查 RapidOCR **在不在**，但**不真的导入它**。

        **绝不能用 ``import`` 来检查可用性。** ``import rapidocr_onnxruntime`` 会
        连带加载 onnxruntime + numpy，实测给一个空闲进程加约 **36MB 工作集和 18 个
        线程**（OpenBLAS 的线程池）。而托盘菜单在**构建菜单时**就会问一次可用性
        （``TrayApp._engine_text`` 要标注「未安装」），于是"懒加载"被彻底绕过 ——
        实测：只是启动程序、什么都没做，工作集就从 **50MB 涨到 86MB**、线程 9 → 27。

        ``find_spec`` 只问模块定位器，不执行模块代码，所以没有这个代价。
        """
        try:
            return importlib.util.find_spec("rapidocr_onnxruntime") is not None
        except (ImportError, ValueError):
            # 父包不存在时 find_spec 会抛 ModuleNotFoundError；名字非法时抛 ValueError
            return False

    def _get_engine(self):
        """首次识别时才构造引擎（构造会加载三个 ONNX 模型，实测约 0.6s）。"""
        if self._engine is None:
            self._engine = self._module().RapidOCR()
        return self._engine

    # ------------------------------------------------------------ 空格重建

    @staticmethod
    def _is_ideograph(ch: str) -> bool:
        """是不是**汉字**（表意文字）。

        **不要用「中日韩标点也算在内」的宽口径判断**（那种写法把 ``：`` ``、``
        ``，`` 和全角字符也算进来）。补空格只在**汉字**旁边做，中文标点后面
        **不加空格**，否则会得到 ``全部通过： pass``、``510、 left`` 这种。

        这条是实测加的：真实截屏上 ``全部通过：pass`` 和 ``510、left`` 都被
        插过错空格。
        """
        return any(lo <= ord(ch) <= hi for lo, hi in (
            (0x4E00, 0x9FFF),   # 统一表意文字
            (0x3400, 0x4DBF),   # 扩展 A
            (0xF900, 0xFAFF),   # 兼容表意文字
        ))

    @staticmethod
    def _is_word_char(ch: str) -> bool:
        """**ASCII** 字母或数字 —— 补空格的**另一侧**必须是它。

        **不能用 ``str.isalnum()`` 单独判断**：汉字在 Unicode 里也算字母，
        ``"行".isalnum()`` 是 ``True`` —— 那样「汉字↔汉字」也会被判成边界，
        插出 ``运 行命 令``、``02生 活工作台`` 这种废文本（真踩过）。

        另一侧是标点时不补：``读取·D:\\...`` 里那个 ``·`` 是分隔符，
        在它前面再加空格就成了 ``读取 ··D:``。
        """
        return ch.isascii() and ch.isalnum()

    @classmethod
    def rebuild_spaces(cls, item) -> str:
        """在**中日韩 ↔ 非中日韩的边界**上补空格，其余位置一律不动。

        背景：RapidOCR 有时会吞掉空格，调用时传 ``return_word_box=True`` 会额外
        返回每个字符的框与字符本身（item 变成 6 元组），于是可以按间隙把空格补回来。

        **只在 CJK 边界补，不在拉丁文内部补。** 这是实测改出来的规则，改之前
        先读完这段：

        模型**自己就会输出空格字符**（``item[4]`` 里就有 ``' '`` 项，与 ``item[1]``
        完全一致）。它的问题只是**偶尔漏掉**空格，而不是全吞。所以"按间隙补空格"
        能捞到的收益有限，风险却很大。

        拿真实截屏（中英混排 + 长路径）量过一轮，拉丁文内部的间隙**完全分不开**：

        ====================  ==================  ==========================
        位置                  间隙                真实情况
        ====================  ==================  ==========================
        ``d|e`` (detail)      5px                 **不是**空格
        ``h|e`` (head)        6px                 **不是**空格
        ``w|o`` (workbench)   5px                 **不是**空格
        ``m|j`` (mjs)         5px                 **不是**空格
        ``m|' '`` (npm run)   5px                 **是**空格
        ``3|/`` (173 / fail)  11px                **是**空格
        ====================  ==================  ==========================

        区间重叠，**任何阈值都分不开**（0.35 拆散 ``passed``，0.6 粘住 ``60 passed``，
        这是早期就记录过的老问题）。而两类错误的代价极不对称：

        - 漏一个空格：``pytest60`` 少了空格，**能用**。
        - 多一个空格：``look-at-real-size.m js``、``d eepseek``，**路径和标识符直接废掉**。

        这是复制工具，粘贴出去的文本要能直接用，所以**宁可漏、不可多**。

        改这一版之前，拉丁文内部的插入在真实截屏上触发 6 次、错了 5 次（约 17%
        精确率），代价就是上面那些被拆碎的路径。

        CJK 边界则相反：中英/中数之间加空格是约定俗成且无歧义的，而模型在这里
        **稳定漏掉**（``verify全部``、``包校验17项``），所以保留。

        边界还收紧了两处（都是实测撞出来的）：

        - **只认汉字，不认中文标点**。用「中日韩标点也算在内」的宽口径判断当边界
          会得到 ``全部通过： pass``、``510、 left`` —— 中文标点后面不加空格。
          所以改用 ``_is_ideograph``。
        - **另一侧必须是字母或数字**。``读取·D:\\...`` 里的 ``·`` 是分隔符，
          在它前面补空格会变成 ``读取 ··D:``。所以另一侧用 ``_is_word_char``。
        """
        if len(item) < 5 or not item[3] or not item[4]:
            return item[1]

        boxes, chars = item[3], item[4]
        if len(boxes) != len(chars):
            return item[1]

        widths = [max(p[0] for p in b) - min(p[0] for p in b) for b in boxes]
        median_w = statistics.median(widths) if widths else 0
        if median_w <= 0:
            return item[1]

        out = []
        for i, ch in enumerate(chars):
            if i and cls._is_space_boundary(chars[i - 1], ch):
                gap = min(p[0] for p in boxes[i]) - max(p[0] for p in boxes[i - 1])
                if (gap > median_w * cls.GAP_RATIO and gap >= cls.MIN_GAP_PX
                        and not out[-1].endswith(" ")):
                    out.append(" ")
            out.append(ch)
        return "".join(out)

    @classmethod
    def _is_space_boundary(cls, left: str, right: str) -> bool:
        """这一对相邻字符是不是该补空格的「汉字 ↔ 字母数字」边界。

        一侧是汉字、另一侧是字母或数字，才算边界：

        - ``和|v``（``第一件事和verify``）-> 是，补
        - ``y|全``（``verify全部``）     -> 是，补
        - ``验|1``（``包校验17项``）     -> 是，补
        - ``：|p``（``通过：pass``）     -> 否，``：`` 是标点
        - ``取|·``（``读取·D:``）        -> 否，``·`` 是标点
        - ``d|e``                        -> 否，两侧都不是汉字
        """
        return ((cls._is_ideograph(left) and cls._is_word_char(right))
                or (cls._is_word_char(left) and cls._is_ideograph(right)))

    @staticmethod
    def _classify_error(exc) -> str:
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        if isinstance(exc, ImportError) or "no module named" in text:
            return "not_found"
        if "onnxruntime" in text and ("not found" in text or "failed" in text):
            return "not_found"
        return "other"

    def recognize(self, image: Image.Image) -> str:
        """识别图片中的文字

        :raises OcrError: 识别过程失败（引擎缺失、模型加载失败等）
        """
        try:
            import numpy as np

            engine = self._get_engine()
            result, _ = engine(np.array(image.convert("RGB")),
                               return_word_box=True)
        except Exception as e:
            raise OcrError(
                f"RapidOCR 识别出错: {e}", kind=self._classify_error(e)
            ) from e

        if not result:
            return ""
        return "\n".join(self.rebuild_spaces(item) for item in result).strip()

    @property
    def name(self) -> str:
        return "rapidocr"


#: 后端名 -> 实现类。``config_manager`` 里的 ``ocr_backend`` 就是这里的键。
_BACKENDS = {
    "tesseract": TesseractBackend,
    "rapidocr": RapidOcrBackend,
}

#: 默认后端。中文正确率优先 —— 见 RapidOcrBackend 的类注释。
DEFAULT_BACKEND = "rapidocr"

#: 引擎不可用时的兜底顺序。用户选的那个起不来就依次往下试。
FALLBACK_ORDER = ("rapidocr", "tesseract")

#: 后端名 -> 界面展示名
BACKEND_LABELS = {
    "tesseract": "Tesseract",
    "rapidocr": "RapidOCR",
}


def backend_label(name) -> str:
    """后端名的界面展示形式（未知名字原样返回，便于排查配置写错）。"""
    if not name:
        return "未知引擎"
    return BACKEND_LABELS.get(name, str(name))


def available_backends():
    """返回当前环境里真正可用的后端名列表（按 FALLBACK_ORDER 排序）。"""
    names = []
    for name in FALLBACK_ORDER:
        cls = _BACKENDS.get(name)
        if cls is None:
            continue
        try:
            if cls().is_available():
                names.append(name)
        except Exception:
            continue
    return names


def create_ocr_engine(backend_name=None):
    """OCR 引擎工厂。

    :param backend_name: 后端名；为 None 时读配置里的 ``ocr_backend``。
        未知名字**回落到默认后端**而不是抛异常 —— 配置文件被手工改坏不该让
        整个识字功能不可用。
    """
    if backend_name is None:
        backend_name = config_manager.get("ocr_backend") or DEFAULT_BACKEND
    return _BACKENDS.get(backend_name, _BACKENDS[DEFAULT_BACKEND])()
