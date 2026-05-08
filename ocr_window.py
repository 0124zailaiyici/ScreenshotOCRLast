import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import threading
from ocr_engine import create_ocr_engine
from translator import translator
from config import config_manager
from clipboard_manager import clipboard_manager

class OcrWindow:
    """OCR 识别窗口：实现动态尺寸、精简工具栏及即时翻译交互"""

    def __init__(self, image, master=None):
        self.image = image
        self.img_width, self.img_height = image.size
        
        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()
            
        self.root.title("OCR 识别")
        
        # 3.1 动态计算窗口尺寸：不超过截图区域，且设定最小尺寸保证工具栏可见
        win_w = max(300, min(self.img_width, 600))
        win_h = max(200, min(self.img_height + 80, 500)) # 80px 用于工具栏
        self.root.geometry(f"{win_w}x{win_h}")
        
        self.root.attributes("-topmost", True)
        self.root.config(bg="white")
        
        # 状态变量
        self.result = {"done": False, "text": "", "error": None}
        self.translations = {} # 缓存翻译结果，格式: {'en': '...', 'zh': '...'}
        self.current_lang = "raw" # 当前显示的语言类型: raw, zh, en
        
        # UI 组件
        self._setup_ui()
        
        # 开始识别任务
        threading.Thread(target=self._do_ocr, daemon=True).start()
        # 开始轮询更新 UI
        self._poll_result()

    def _setup_ui(self):
        """初始化 UI 布局：3.2 顶部工具栏固定，3.3 翻译集成到语言选择"""
        # 顶部工具栏
        toolbar = tk.Frame(self.root, bg="#F3F3F3", height=40)
        toolbar.pack(side="top", fill="x")
        
        # 3.2 复制按钮常驻左侧
        self.btn_copy = tk.Button(toolbar, text="📋 复制", command=self._copy_all, 
                                 bg="#0078D4", fg="white", relief="flat", 
                                 font=("Segoe UI", 9, "bold"), padx=15)
        self.btn_copy.pack(side="left", padx=5, pady=5)
        
        # 3.3/5.3 语言选择区（中文/英文标签）
        lang_frame = tk.Frame(toolbar, bg="#F3F3F3")
        lang_frame.pack(side="right", padx=5)
        
        tk.Label(lang_frame, text="翻译至:", bg="#F3F3F3", font=("Segoe UI", 9)).pack(side="left")
        
        self.btn_lang_zh = tk.Button(lang_frame, text="中文", command=lambda: self._trigger_translate("zh"),
                                    bg="white", relief="flat", font=("Segoe UI", 9), padx=8)
        self.btn_lang_zh.pack(side="left", padx=2)
        
        self.btn_lang_en = tk.Button(lang_frame, text="英文", command=lambda: self._trigger_translate("en"),
                                    bg="white", relief="flat", font=("Segoe UI", 9), padx=8)
        self.btn_lang_en.pack(side="left", padx=2)
        
        # 5.1 OCR 结果预览区
        self.text_area = scrolledtext.ScrolledText(self.root, font=("Consolas", 11), wrap=tk.WORD, 
                                                  bg="white", relief="flat", padx=10, pady=10)
        self.text_area.pack(fill="both", expand=True)
        self.text_area.insert(tk.END, "正在识别...")

    def _do_ocr(self):
        """后台执行 OCR"""
        try:
            engine = create_ocr_engine(config_manager.get("ocr_backend"))
            if not engine.is_available():
                self.result["error"] = "Tesseract 未安装或不在环境变量中"
                self.result["done"] = True
                return

            text = engine.recognize(self.image)
            self.result["text"] = text
            self.result["done"] = True
            # 注意：此处不再调用 clipboard_manager.copy_text，实现需求 1 & 2
        except Exception as e:
            self.result["error"] = str(e)
            self.result["done"] = True

    def _poll_result(self):
        """轮询更新结果"""
        if not self.root.winfo_exists(): return
        if self.result["done"]:
            if self.result["error"]:
                self.text_area.delete("1.0", tk.END)
                error_msg = self.result["error"]
                self.text_area.insert(tk.END, f"识别失败: {error_msg}\n\n"
                                             f"原因：系统未找到 Tesseract 引擎。\n"
                                             f"解决办法：\n"
                                             f"1. 前往 https://github.com/UB-Mannheim/tesseract/wiki 下载并安装。\n"
                                             f"2. 若已安装，请在下方对话框中手动指定 tesseract.exe 路径。")
                
                # 弹出路径选择对话框
                if "Tesseract" in self.result["error"]:
                    if messagebox.askyesno("Tesseract 路径错误", f"{self.result['error']}\n是否现在手动指定 tesseract.exe 路径？"):
                        path = filedialog.askopenfilename(title="选择 tesseract.exe", 
                                                         filetypes=[("Executable", "*.exe")])
                        if path:
                            config_manager.set("tesseract_path", path)
                            # 重新开始 OCR
                            self.result["done"] = False
                            self.result["error"] = None
                            self.text_area.delete("1.0", tk.END)
                            self.text_area.insert(tk.END, "重新识别中...")
                            threading.Thread(target=self._do_ocr, daemon=True).start()
                            self.root.after(100, self._poll_result)
                            return
            else:
                self.text_area.delete("1.0", tk.END)
                self.text_area.insert(tk.END, self.result["text"])
                # 初始化时，我们将原始内容记录在缓存中（虽然不知道具体语言，但点击任何按钮如果报错都会退回到这里）
                # 标记当前显示的是“原始内容”
                self.current_lang = "raw" 
        else:
            self.root.after(100, self._poll_result)

    def _copy_all(self):
        """5.2 用户主动点击复制原文"""
        text = self.text_area.get("1.0", tk.END).strip()
        if not text or text == "正在识别...": return
        
        if clipboard_manager.copy_text(text):
            self.btn_copy.config(text="✅ 已复制", bg="#107C10")
            self.root.after(1500, lambda: self.btn_copy.config(text="📋 复制", bg="#0078D4"))

    def _trigger_translate(self, target):
        """5.3 点击语言标签即触发翻译，支持无限次双向切换与内容缓存"""
        if not self.result["done"] or self.result["error"]:
            return
            
        original_text = self.result["text"]
        if not original_text.strip():
            return

        # 如果点击的是当前已经显示的语言，则不做操作
        if self.current_lang == target:
            return

        # 检查是否已有缓存
        if target in self.translations:
            self._update_text_area(self.translations[target], target)
            return
            
        # 禁用按钮防止重复点击
        self.btn_lang_zh.config(state="disabled")
        self.btn_lang_en.config(state="disabled")
        
        def _on_success(res):
            self.root.after(0, lambda: self._handle_translate_success(res, target))

        def _on_error(err):
            self.root.after(0, lambda: self._handle_translate_error(err, target, original_text))

        translator.translate_async(original_text, _on_success, error_callback=_on_error, to_lang=target)

    def _handle_translate_success(self, res, target):
        """主线程处理翻译成功"""
        self.translations[target] = res
        self._update_text_area(res, target)
        self.btn_lang_zh.config(state="normal")
        self.btn_lang_en.config(state="normal")

    def _handle_translate_error(self, err, target, original_text):
        """主线程处理翻译错误"""
        # 捕获“源语言与目标语言相同”的各种报错变体
        is_same_lang_error = any(msg in err.lower() for msg in [
            "target and source languages are the same",
            "same language",
            "should not be same",
            "identical"
        ])

        if is_same_lang_error:
            # 如果翻译失败是因为源语言已经是目标语言，则直接将原文存入该语言的缓存并显示
            self.translations[target] = original_text
            self._update_text_area(original_text, target)
        else:
            # 其他真实错误（如网络问题、API 限制）才弹出报错
            messagebox.showerror("翻译失败", err)
        
        self.btn_lang_zh.config(state="normal")
        self.btn_lang_en.config(state="normal")

    def _update_text_area(self, text, lang):
        """更新文本区域并记录当前语言状态"""
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, text)
        self.current_lang = lang
        # 更新按钮样式以反馈当前状态
        self.btn_lang_zh.config(relief="sunken" if lang == "zh" else "flat")
        self.btn_lang_en.config(relief="sunken" if lang == "en" else "flat")

# 导出函数
def show_ocr_window(image, master=None):
    return OcrWindow(image, master=master)
