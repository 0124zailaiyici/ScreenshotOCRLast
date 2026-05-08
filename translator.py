import translators as ts
import threading
import json
import os
from datetime import datetime

class Translator:
    """翻译模块：封装多引擎翻译逻辑，支持自动检测、历史记录及错误处理"""

    def __init__(self, timeout=15):
        self.timeout = timeout
        self.history_file = "translation_history.json"
        self._load_history()

    def _load_history(self):
        """从本地加载翻译历史"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
            except:
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
        except:
            pass

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
