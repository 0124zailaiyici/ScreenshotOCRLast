import pytesseract
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import os
from config import config_manager

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

    def recognize(self, image: Image.Image) -> str:
        """识别图片中的文字，包含预处理逻辑"""
        try:
            # 1. 图像预处理：转灰度
            processed_img = image.convert('L')
            
            # 2. 自动放大：针对小图提高识别率
            w, h = processed_img.size
            if w < 1000 or h < 1000:
                processed_img = processed_img.resize((w*2, h*2), Image.Resampling.LANCZOS)

            # 3. 增强对比度
            enhancer = ImageEnhance.Contrast(processed_img)
            processed_img = enhancer.enhance(2.0)
            
            # 4. 锐化
            processed_img = processed_img.filter(ImageFilter.SHARPEN)

            # 5. 调用 pytesseract
            lang = config_manager.get("ocr_lang") or "chi_sim+eng"
            text = pytesseract.image_to_string(processed_img, lang=lang)
            return text.strip()
        except Exception as e:
            print(f"Tesseract 识别出错: {e}")
            return f"识别失败: {str(e)}"

    @property
    def name(self) -> str:
        return "tesseract"

def create_ocr_engine(backend_name="tesseract"):
    """OCR 引擎工厂函数"""
    if backend_name == "tesseract":
        return TesseractBackend()
    # 未来可扩展其他后端 (如 paddleocr, baidu_api 等)
    return TesseractBackend()
