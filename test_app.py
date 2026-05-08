import pytest
import os
import json
from config import ConfigManager
from clipboard_manager import ClipboardManager
from PIL import Image

def test_config_manager():
    """测试配置管理器的读写功能"""
    cm = ConfigManager()
    # 测试默认值
    assert cm.get("hotkey") == "<ctrl>+<shift>+a"
    
    # 测试设置值
    cm.set("test_key", "test_value")
    assert cm.get("test_key") == "test_value"
    
    # 验证文件是否生成
    assert os.path.exists(cm.config_path)
    with open(cm.config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        assert data["test_key"] == "test_value"

def test_clipboard_text():
    """测试剪贴板文字复制 (Mock 或直接测试)"""
    res = ClipboardManager.copy_text("Hello Test")
    assert res is True

def test_ocr_engine_creation():
    """测试 OCR 引擎工厂"""
    from ocr_engine import create_ocr_engine, TesseractBackend
    engine = create_ocr_engine("tesseract")
    assert isinstance(engine, TesseractBackend)
    assert engine.name == "tesseract"

def test_image_processing_logic():
    """测试图片预处理逻辑是否报错"""
    from ocr_engine import TesseractBackend
    backend = TesseractBackend()
    img = Image.new('RGB', (100, 100), color='white')
    # 虽然没有安装 Tesseract 可能无法识别，但函数不应直接崩溃
    try:
        backend.recognize(img)
    except Exception as e:
        pytest.fail(f"OCR recognize logic raised exception: {e}")

if __name__ == "__main__":
    pytest.main([__file__])
