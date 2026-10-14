import json
import os
import sys
import winreg
import threading

# 默认配置文件名
CONFIG_FILE = "screenshot_ocr_config.json"

class ConfigManager:
    """配置管理器：负责读取和保存用户设置

    :param config_dir: 显式指定配置目录。默认使用 %APPDATA%/ScreenshotOCR。
                       显式传入可让测试完全隔离，不触碰用户真实配置。
    """

    # 各配置项的期望类型，用于加载时丢弃被写坏的条目
    _SCHEMA = {
        "hotkey": str,
        "ocr_backend": str,
        "ocr_lang": str,
        "tesseract_path": str,
        "auto_copy_text": bool,
        "auto_copy_image": bool,
        "notification_enabled": bool,
        "pinned_items": list,
    }

    def __init__(self, config_dir=None):
        self._lock = threading.Lock()
        # exe 所在目录（用于钉住图片等本地资源）
        if getattr(sys, 'frozen', False):
            self.base_path = os.path.dirname(sys.executable)
        else:
            self.base_path = os.path.dirname(os.path.abspath(__file__))

        # 配置文件固定存到 %APPDATA%，exe 移动到任何位置都不影响
        if config_dir is None:
            appdata = os.environ.get('APPDATA', self.base_path)
            config_dir = os.path.join(appdata, "ScreenshotOCR")
        self.config_dir = config_dir
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_path = os.path.join(self.config_dir, CONFIG_FILE)
        # 钉住图片等数据也存到同一目录
        self.data_dir = os.path.join(self.config_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.config = self._get_default_config()
        self.load()

    def _get_default_config(self):
        """返回默认配置项"""
        return {
            "hotkey": "<alt>+x",  # 全局截图热键
            "ocr_backend": "rapidocr",     # 默认 OCR 后端（见 ocr_engine.DEFAULT_BACKEND）
            "ocr_lang": "chi_sim+eng",     # 识别语言：限定简中+英文
            "tesseract_path": "",          # Tesseract 可执行文件路径
            "auto_copy_text": False,       # 彻底禁用自动复制文本行为
            "auto_copy_image": False,      # 截图后不自动复制图片
            "notification_enabled": True,  # 是否开启托盘通知
            "pinned_items": []             # 持久化钉住的项目 [{path: str, coords: [x,y,w,h]}]
        }

    @staticmethod
    def _clean_pinned_items(items):
        """逐元素清洗钉住条目。

        只校验容器类型（``isinstance(value, list)``）是不够的：消费方（``pin_window``）
        对每个元素都直接调 ``item.get(...)``，列表里混进一个字符串就会让「钉住」静默失败
        —— 异常被 ``main._do_screenshot`` 的 except 吞掉，窗口不出现、也没有任何提示。

        - 非 dict 的元素直接丢弃；
        - ``pos`` 形状不对时只丢掉这个字段（保留钉住本身，让它回落到默认位置），
          而不是把整条记录扔掉 —— 用户的钉住不该因为一个坏坐标就消失。
        """
        clean = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            pos = item.get("pos")
            if pos is not None:
                valid = (isinstance(pos, (list, tuple)) and len(pos) == 2
                         and all(isinstance(v, (int, float))
                                 and not isinstance(v, bool) for v in pos))
                if not valid:
                    item.pop("pos", None)
            clean.append(item)
        return clean

    def _sanitize(self, user_config):
        """丢弃类型不符的配置项，避免脏配置在运行期引发崩溃"""
        clean = {}
        for key, value in user_config.items():
            expected = self._SCHEMA.get(key)
            if expected is None:
                clean[key] = value          # 未知键原样保留，向后兼容
            elif expected is bool:
                if isinstance(value, bool):
                    clean[key] = value
            elif isinstance(value, expected):
                # 容器类型对不代表内容可用：pinned_items 是唯一有结构的字段，
                # 也是唯一需要逐元素校验的字段
                if key == "pinned_items":
                    clean[key] = self._clean_pinned_items(value)
                else:
                    clean[key] = value
        return clean

    def load(self):
        """从 JSON 文件加载配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                if not isinstance(user_config, dict):
                    print(f"配置格式错误（期望 JSON 对象）: {type(user_config).__name__}")
                    return
                self.config.update(self._sanitize(user_config))
            else:
                self.save()  # 文件不存在则创建默认配置
        except Exception as e:
            print(f"加载配置失败: {e}")

    def save(self):
        """将当前配置保存到 JSON 文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def get(self, key):
        """获取指定配置项"""
        return self.config.get(key)

    def set(self, key, value):
        """设置并保存配置项（线程安全）

        与 load() 一致地做类型校验：已知键收到类型不符的值时拒绝写入，
        避免脏值在运行期引发崩溃。未知键不做限制。
        """
        with self._lock:
            expected = self._SCHEMA.get(key)
            if expected is not None:
                if expected is bool:
                    ok = isinstance(value, bool)
                else:
                    ok = isinstance(value, expected)
                if not ok:
                    print(f"配置 {key} 期望 {expected.__name__}，"
                          f"收到 {type(value).__name__}，已拒绝写入")
                    return
            self.config[key] = value
            self.save()

    def get_pinned_items(self):
        """线程安全地获取钉住窗口列表。

        在**读取边界**上也做一次清洗，让「返回的每个元素都是形状正确的 dict」
        成为这个方法的硬保证 —— 消费方 ``pin_window`` 无条件信任这一点。
        """
        with self._lock:
            items = self.config.get("pinned_items")
            return self._clean_pinned_items(items) if isinstance(items, list) else []

    def set_pinned_items(self, items):
        """线程安全地设置钉住窗口列表（写入前清洗，坏数据不会落盘）"""
        with self._lock:
            self.config["pinned_items"] = self._clean_pinned_items(items)
            self.save()

    def get_system_accent_color(self):
        """获取 Windows 系统主题色 (Accent Color)"""
        try:
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\DWM")
            value, _ = winreg.QueryValueEx(key, "AccentColor")
            # Windows 返回的是 ABGR 格式 (如 0xffd47800)
            # 转换为 HEX 格式 (如 #0078D4)
            bgr = value & 0xFFFFFF
            r = bgr & 0xFF
            g = (bgr >> 8) & 0xFF
            b = (bgr >> 16) & 0xFF
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#0078D4" # 默认蓝色

    def is_dark_mode(self):
        """检测系统是否开启深色模式"""
        try:
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        except Exception:
            return False

# 全局配置单例
config_manager = ConfigManager()
