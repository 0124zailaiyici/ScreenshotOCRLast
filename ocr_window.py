import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import threading
from ocr_engine import create_ocr_engine
from translator import translator
from config import config_manager
from clipboard_manager import clipboard_manager
from ui_theme import theme_manager, FONT_BUTTON, FONT_BUTTON_SM, FONT_MONO, COLOR_SUCCESS
from ui_icons import icons


class OcrWindow:
    """OCR 识别窗口：主题化界面、图标按钮、即时翻译交互"""

    def __init__(self, image, coords=None, master=None):
        theme_manager.update(
            is_dark=config_manager.is_dark_mode(),
            accent_color=config_manager.get_system_accent_color()
        )

        self.image = image
        self.coords = coords
        self.img_width, self.img_height = image.size

        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()

        self.root.title("OCR 识别")

        win_w = max(300, min(self.img_width, 600))
        win_h = max(200, min(self.img_height + 80, 500))
        self.root.geometry(f"{win_w}x{win_h}")

        self._position_near_region(win_w, win_h)

        self.root.attributes("-topmost", True)
        self.root.config(bg=theme_manager.theme.bg_primary)

        self.result = {"done": False, "text": "", "error": None}
        self.translations = {}
        self.current_lang = "raw"

        self._setup_ui()
        threading.Thread(target=self._do_ocr, daemon=True).start()
        self._poll_result()

    def _position_near_region(self, win_w, win_h):
        if not self.coords:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            x = (screen_w - win_w) // 2
            y = (screen_h - win_h) // 2
            self.root.geometry(f"+{x}+{y}")
            return

        x1, y1, x2, y2 = self.coords
        target_x = x2 + 10
        target_y = y1 - 10

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if target_x + win_w > screen_w:
            target_x = x1 - win_w - 10
        if target_y < 0:
            target_y = y2 + 10
        if target_y + win_h > screen_h:
            target_y = screen_h - win_h - 10

        target_x = max(0, target_x)
        target_y = max(0, target_y)
        self.root.geometry(f"+{target_x}+{target_y}")

    def _setup_ui(self):
        theme = theme_manager.theme

        toolbar = tk.Frame(self.root, bg=theme.bg_toolbar, height=44)
        toolbar.pack(side="top", fill="x")

        # 复制按钮（图标+文字，图标用白色以匹配有色背景）
        clip_icon = icons.get_clipboard("white")
        self.btn_copy = tk.Button(
            toolbar, image=clip_icon, text=" 复制",
            compound="left",
            command=self._copy_all,
            bg=theme_manager.accent_color, fg="white",
            relief="flat", font=FONT_BUTTON, padx=12, cursor="hand2"
        )
        self.btn_copy._icon_ref = clip_icon
        self.btn_copy.pack(side="left", padx=5, pady=5)

        # 语言选择区
        lang_frame = tk.Frame(toolbar, bg=theme.bg_toolbar)
        lang_frame.pack(side="right", padx=5)

        tk.Label(
            lang_frame, text="翻译至:",
            bg=theme.bg_toolbar, fg=theme.text_secondary,
            font=FONT_BUTTON_SM
        ).pack(side="left")

        self.btn_lang_zh = tk.Button(
            lang_frame, text="中文",
            command=lambda: self._trigger_translate("zh"),
            bg=theme.bg_hover, fg=theme.text_primary,
            activebackground=theme.bg_pressed,
            relief="flat", font=FONT_BUTTON, padx=8, cursor="hand2"
        )
        self.btn_lang_zh.pack(side="left", padx=2)

        self.btn_lang_en = tk.Button(
            lang_frame, text="英文",
            command=lambda: self._trigger_translate("en"),
            bg=theme.bg_hover, fg=theme.text_primary,
            activebackground=theme.bg_pressed,
            relief="flat", font=FONT_BUTTON, padx=8, cursor="hand2"
        )
        self.btn_lang_en.pack(side="left", padx=2)

        # OCR 结果预览区
        self.text_area = scrolledtext.ScrolledText(
            self.root, font=(FONT_MONO, 11), wrap=tk.WORD,
            bg=theme.bg_input, fg=theme.text_primary,
            insertbackground=theme.text_primary,
            relief="flat", padx=10, pady=10
        )
        self.text_area.pack(fill="both", expand=True)
        self.text_area.insert(tk.END, "正在识别...")

    def _do_ocr(self):
        try:
            engine = create_ocr_engine(config_manager.get("ocr_backend"))
            if not engine.is_available():
                self.result["error"] = "Tesseract 未安装或不在环境变量中"
                self.result["done"] = True
                return

            text = engine.recognize(self.image)
            self.result["text"] = text
            self.result["done"] = True
        except Exception as e:
            self.result["error"] = str(e)
            self.result["done"] = True

    def _poll_result(self):
        if not self.root.winfo_exists():
            return
        if self.result["done"]:
            if self.result["error"]:
                self.text_area.delete("1.0", tk.END)
                error_msg = self.result["error"]
                self.text_area.insert(
                    tk.END,
                    f"识别失败: {error_msg}\n\n"
                    f"原因：系统未找到 Tesseract 引擎。\n"
                    f"解决办法：\n"
                    f"1. 前往 https://github.com/UB-Mannheim/tesseract/wiki 下载并安装。\n"
                    f"2. 若已安装，请在下方对话框中手动指定 tesseract.exe 路径。"
                )

                if "Tesseract" in self.result["error"]:
                    if messagebox.askyesno(
                        "Tesseract 路径错误",
                        f"{self.result['error']}\n是否现在手动指定 tesseract.exe 路径？"
                    ):
                        path = filedialog.askopenfilename(
                            title="选择 tesseract.exe",
                            filetypes=[("Executable", "*.exe")]
                        )
                        if path:
                            config_manager.set("tesseract_path", path)
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
                self.current_lang = "raw"
        else:
            self.root.after(100, self._poll_result)

    def _copy_all(self):
        text = self.text_area.get("1.0", tk.END).strip()
        if not text or text == "正在识别...":
            return

        if clipboard_manager.copy_text(text):
            ck_icon = icons.get_checkmark("#FFFFFF")
            self.btn_copy.config(image=ck_icon, text=" 已复制", bg=COLOR_SUCCESS)
            self.btn_copy._icon_ref = ck_icon
            self.root.after(1500, self._restore_copy_button)

    def _restore_copy_button(self):
        clip_icon = icons.get_clipboard("#FFFFFF")
        self.btn_copy.config(image=clip_icon, text=" 复制", bg=theme_manager.accent_color)
        self.btn_copy._icon_ref = clip_icon

    def _trigger_translate(self, target):
        if not self.result["done"] or self.result["error"]:
            return
        original_text = self.result["text"]
        if not original_text.strip():
            return
        if self.current_lang == target:
            return
        if target in self.translations:
            self._update_text_area(self.translations[target], target)
            return

        self.btn_lang_zh.config(state="disabled")
        self.btn_lang_en.config(state="disabled")

        def _on_success(res):
            self.root.after(0, lambda: self._handle_translate_success(res, target))

        def _on_error(err):
            self.root.after(0, lambda: self._handle_translate_error(err, target, original_text))

        translator.translate_async(
            original_text, _on_success,
            error_callback=_on_error, to_lang=target
        )

    def _handle_translate_success(self, res, target):
        self.translations[target] = res
        self._update_text_area(res, target)
        self.btn_lang_zh.config(state="normal")
        self.btn_lang_en.config(state="normal")

    def _handle_translate_error(self, err, target, original_text):
        is_same_lang_error = any(
            msg in err.lower() for msg in [
                "target and source languages are the same",
                "same language", "should not be same", "identical"
            ]
        )
        if is_same_lang_error:
            hint = f"[原文已是{'中文' if target == 'zh' else '英文'}，无需翻译]\n\n{original_text}"
            self.translations[target] = hint
            self._update_text_area(hint, target)
        else:
            messagebox.showerror("翻译失败", err)

        self.btn_lang_zh.config(state="normal")
        self.btn_lang_en.config(state="normal")

    def _update_text_area(self, text, lang):
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, text)
        self.current_lang = lang

        active_bg = theme_manager.accent_color
        inactive_bg = theme_manager.theme.bg_hover
        active_fg = "white"
        inactive_fg = theme_manager.theme.text_primary

        self.btn_lang_zh.config(
            bg=active_bg if lang == "zh" else inactive_bg,
            fg=active_fg if lang == "zh" else inactive_fg
        )
        self.btn_lang_en.config(
            bg=active_bg if lang == "en" else inactive_bg,
            fg=active_fg if lang == "en" else inactive_fg
        )


def show_ocr_window(image, coords=None, master=None):
    return OcrWindow(image, coords=coords, master=master)
