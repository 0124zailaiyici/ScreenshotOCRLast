import json
import os
import shutil
import threading
from datetime import datetime

from config import config_manager


# translators 的依赖树极重：实测 import 耗时约 2.4 秒、工作集 +48MB，
# 占整个程序内存的 80% —— 它一次拖进 aiohttp / httpx / niquests / requests
# 四套 HTTP 客户端，外加 cryptography、lxml、multiprocess、psutil 等 40 多个包。
# 而翻译只是 OCR 之后的次要功能，多数会话根本用不到，因此改为首次翻译时才导入。
# 注意：**不要**在模块顶层 import translators，那会让每次启动都白付这份开销。
_translators_module = None

# translators 在**导入期**就会发网络请求探测所在地区：它的模块体里直接写了
# ``tss = TranslatorsServer()``（server.py:6205），构造函数又调用
# ``get_region_of_server()``（server.py:5896），后者去请求
# geolocation.onetrust.com，失败再退到 httpbin.org（server.py:364）。
# 两个后果都很糟：
#   1. 探测失败会抛 TranslatorError，**整个 import 直接失败** —— 用户点「翻译」
#      看到的是一个跟 httpbin.org 有关的报错；
#   2. 那两次 requests.get **没有设 timeout**，网络不通时可能挂很久。
# server.py:344 留了逃生口：只要 ``translators_default_region`` 有值，
# ``get_region_of_server`` 就在第一行直接返回（server.py:347-350），不发任何请求。
# 所以在导入前钉住地区 —— 本程序面向中文用户，选 CN（Google 等服务会走国内可用域名）。
# 用 setdefault 是为了不覆盖用户自己设的值；非中国大陆用户可设
# ``translators_default_region=EN`` 覆盖。
_DEFAULT_REGION = "CN"


def _translators():
    """延迟加载 translators，只在真正需要翻译时才付那份内存与时间。

    导入前会先钉住地区，避免 translators 在导入期发网络请求 —— 详见
    ``_DEFAULT_REGION`` 上方的说明。
    """
    global _translators_module
    if _translators_module is None:
        os.environ.setdefault("translators_default_region", _DEFAULT_REGION)
        import translators
        _translators_module = translators
    return _translators_module


class Translator:
    """翻译模块：封装多引擎翻译逻辑，支持自动检测、历史记录及错误处理"""

    def __init__(self, timeout=15, history_file=None):
        self.timeout = timeout
        # 历史记录与配置同目录（%APPDATA%/ScreenshotOCR），
        # 不再依赖当前工作目录，避免 exe 从任意位置启动时写错地方或静默失败
        if history_file is None:
            history_file = os.path.join(config_manager.config_dir, "translation_history.json")
        self.history_file = history_file
        self._load_history()

    def migrate_legacy_history(self):
        """把旧版写在当前工作目录的历史记录迁移到配置目录。

        必须由启动流程**显式调用**，不要在模块导入期执行文件复制 ——
        否则任何 ``import translator``（测试、自检、IDE 索引）都会产生副作用。

        :return: 是否发生了迁移
        """
        if os.path.exists(self.history_file):
            return False

        # 旧实现把历史写在当前工作目录，因此 CWD 与程序目录都可能是遗留位置
        candidates = [
            os.path.join(config_manager.base_path, "translation_history.json"),
            os.path.join(os.getcwd(), "translation_history.json"),
        ]
        for legacy in dict.fromkeys(candidates):
            if os.path.exists(legacy):
                try:
                    shutil.copyfile(legacy, self.history_file)
                    print(f"已迁移翻译历史: {legacy} -> {self.history_file}")
                    self._load_history()
                    return True
                except Exception as e:
                    print(f"迁移翻译历史失败: {e}")
        return False

    def _load_history(self):
        """从本地加载翻译历史"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.history = data if isinstance(data, list) else []
            except Exception as e:
                print(f"读取翻译历史失败: {e}")
                self.history = []
        else:
            self.history = []

    def _save_history(self, original, translated, from_lang, to_lang):
        """保存翻译记录"""
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "from": from_lang,
            "to": to_lang,
            "original": original[:100] + "..." if len(original) > 100 else original,
            "translated": translated[:100] + "..." if len(translated) > 100 else translated
        }
        self.history.insert(0, record)
        self.history = self.history[:50]  # 只保留最近 50 条
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"写入翻译历史失败: {e}")

    @staticmethod
    def _detect_language(text):
        """本地检测文本语言：通过 Unicode 范围判断是否含中文"""
        if not text:
            return 'en'
        cjk_chars = sum(1 for c in text if '一' <= c <= '鿿')
        if cjk_chars / max(len(text), 1) > 0.2:
            return 'zh'
        return 'en'

    def translate(self, text, from_lang='auto', to_lang='zh', engine='alibaba'):
        """
        同步翻译函数
        :param text: 待翻译文本
        :param from_lang: 源语言，默认 auto (自动检测)
        :param to_lang: 目标语言，仅支持 zh, en
        :param engine: 翻译引擎
        """
        if not text.strip():
            return ""

        # 严格过滤语言：仅支持中英
        if to_lang not in ['zh', 'en']:
            to_lang = 'zh' if from_lang == 'en' else 'en'

        # 本地语言检测：避免 API 自动检测出错
        if from_lang == 'auto':
            detected = self._detect_language(text)
            if detected == to_lang:
                # 源语言和目标语言相同，直接返回原文，无需调用 API
                self._save_history(text, text, detected, to_lang)
                return text
            from_lang = detected

        try:
            ts = _translators()
        except Exception as e:
            error_msg = f"翻译引擎不可用（translators 未安装或加载失败）: {e}"
            print(error_msg)
            raise Exception(error_msg) from e

        try:
            # 自动映射通用语言代码
            res = ts.translate_text(
                query_text=text,
                translator=engine,
                from_language=from_lang,
                to_language=to_lang,
                timeout=self.timeout
            )
            
            # 保存到历史记录
            self._save_history(text, res, from_lang, to_lang)
            return res
        except Exception as e:
            error_msg = f"翻译失败 [{engine}]: {str(e)}"
            print(error_msg)
            raise Exception(error_msg)

    def translate_async(self, text, callback, error_callback=None, **kwargs):
        """异步翻译，支持成功和失败回调"""
        def _task():
            try:
                res = self.translate(text, **kwargs)
                callback(res)
            except Exception as e:
                if error_callback:
                    error_callback(str(e))
        
        threading.Thread(target=_task, daemon=True).start()

# 导出翻译单例
translator = Translator()
