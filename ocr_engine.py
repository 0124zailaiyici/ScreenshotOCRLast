import pytesseract
from PIL import Image, ImageFilter, ImageEnhance
import os
from config import config_manager


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
        """检查 Tesseract 是否可用"""
        try:
            self._update_path()
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

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
