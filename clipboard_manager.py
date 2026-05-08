import win32clipboard
import io
from PIL import Image

class ClipboardManager:
    """剪贴板管理器：处理图片和文字的存取"""

    @staticmethod
    def copy_image(image: Image.Image):
        """将 PIL Image 复制到 Windows 剪贴板"""
        try:
            # 将图片转换为 DIB (Device Independent Bitmap) 格式
            output = io.BytesIO()
            image.convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]  # 去掉 BMP 文件头 (14 字节)
            output.close()

            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            # 使用 CF_DIB 格式存入图片数据
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()
            return True
        except Exception as e:
            print(f"复制图片到剪贴板失败: {e}")
            return False

    @staticmethod
    def copy_text(text: str):
        """将字符串复制到 Windows 剪贴板"""
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            # 使用 CF_UNICODETEXT 格式确保中文不乱码
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return True
        except Exception as e:
            print(f"复制文字到剪贴板失败: {e}")
            return False

# 导出静态工具类
clipboard_manager = ClipboardManager()
