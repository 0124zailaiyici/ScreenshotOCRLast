# ScreenshotOCR

Windows 截图工具，支持截图后三选一操作：钉住到屏幕、OCR 识别文字、复制图片。常驻系统托盘，`Alt+X` 全局热键触发。

## 技术栈

- Python 3.10+, **无外部 GUI 框架**，纯 Tkinter 做 GUI
- **pystray** 系统托盘
- **Pillow** 图像处理
- **pywin32** Windows 剪贴板操作
- **pynput** 全局热键（非注册表方式）
- **pytesseract** OCR 识别（需独立安装 Tesseract-OCR 5.x）
- **translators** 中英翻译
- **PyInstaller** 打包为单文件 exe

## 架构 / 数据流

```
用户按热键
  → hotkey_listener.py (pynput 全局热键 → 放入 queue)
  → main.py (_on_screenshot_trigger → 放入持久化 Tk 线程队列)
    → screenshot_overlay.py (全屏覆盖层，拖拽选区域)
      → 浮动工具栏 [钉住|识字|复制]
        → pin_window.py (无边框浮窗，滚轮缩放)
        → ocr_window.py (文字识别窗口 + 翻译)
        → clipboard_manager.py (复制图片到剪贴板)
```

### 关键约束

- **Tkinter 线程安全**：所有 Tkinter 调用必须在创建该窗口的线程中执行。OCR 和翻译在后台线程运行，通过 `result` dict + 主线程 `after()` 轮询模式取回结果。
- **持久化 Tk 线程**：main.py 在 `_pin_loop` 中创建唯一一个隐藏的 Tk 主循环，专门用于显示钉住窗口。截图覆盖层和 OCR 窗口使用临时 Toplevel 作为会话容器。
- **跨线程通信**：后台线程只写普通 Python dict，主线程每 200ms 轮询检测变化。严禁后台线程调用 `win.after()`、`win.winfo_exists()` 等 Tkinter 函数。
- **配置路径**：exe 模式下配置文件在 exe 同级目录 (`sys.executable`)，源码模式下在项目根目录 (`__file__`)。

## 目录结构

```
.
├── main.py                   # 入口：持久化 Tk 线程 + 热键 + 托盘
├── config.py                 # JSON 配置读写 (exe 同级目录)
├── screenshot_overlay.py     # 全屏选区覆盖层 + 浮动工具栏
├── pin_window.py             # 钉住浮窗
├── ocr_window.py             # OCR 文字识别窗口 + 翻译
├── translator.py             # 翻译模块 (translators 库)
├── ocr_engine.py             # OCR 引擎工厂
├── ocr_backends/
│   ├── base.py               # OcrBackend 抽象基类
│   └── tesseract_backend.py  # Tesseract 后端 (含图像预处理)
├── clipboard_manager.py      # 剪贴板 (pywin32 CF_DIB/CF_UNICODETEXT)
├── hotkey_listener.py        # 全局热键 (pynput)
├── tray_app.py               # 系统托盘 (pystray)
├── ui_theme.py               # 主题系统（深色/浅色 + AccentColor）
├── ui_icons.py               # 图标缓存管理器 (PIL 程序化生成)
├── assets/                   # 托盘图标 + 钉住图片
├── build_exe.py              # PyInstaller 打包脚本
├── screenshot_ocr_config.json # 用户配置文件
└── requirements.txt
```

## 关键代码模式

### 后台任务 → UI 更新（防崩溃）

```python
result = {"done": False, "text": "", "error": None}

def poll_result():
    if not win.winfo_exists():
        return
    if result["done"]:
        _on_done()
    win.after(200, poll_result)  # 只在主线程调用 after()

threading.Thread(target=do_work, daemon=True).start()
poll_result()
```

### OCR 引擎抽象

所有的 OCR 后端实现 `OcrBackend` 接口（`recognize()`、`is_available()`、`name`），通过 `ocr_engine.create_ocr_engine()` 工厂创建。

## 配置项

`screenshot_ocr_config.json`，首次运行自动生成：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `hotkey` | `<alt>+x` | 全局快捷键 |
| `ocr_backend` | `tesseract` | OCR 引擎 |
| `ocr_lang` | `chi_sim+eng` | 识别语言 |
| `tesseract_path` | `""` | Tesseract 路径（空则自动查找） |
| `notification_enabled` | `true` | 托盘通知 |
| `pinned_items` | `[]` | 持久化的钉住窗口 |

## 构建

```bash
python build_exe.py
```

或手动 PyInstaller：

```bash
pyinstaller --noconsole --onefile --name "ScreenshotOCR" \
  --hidden-import pystray \
  --hidden-import pytesseract \
  --hidden-import win32clipboard \
  --hidden-import translators \
  --hidden-import PIL.ImageTk \
  --hidden-import ui_theme \
  --hidden-import ui_icons \
  main.py
```

打包后需将 `screenshot_ocr_config.json` 复制到 `dist/` 目录下。

## 依赖

```
pystray>=0.19.5      # 系统托盘
pytesseract>=0.3.10  # OCR Python 绑定
Pillow>=10.0.0       # 图像处理库
pywin32>=306         # Windows API（剪贴板 + 热键轮询）
translators>=5.0.0   # 多引擎翻译
```

## 已知注意事项

- **DPI 感知**：`main.py` 在 import 任何 GUI 模块前调用 `SetProcessDPIAware()`，确保选区坐标与像素匹配。
- **Tesseract 预处理**：`tesseract_backend.py` 对小图自动放大，转灰度 + 对比度拉伸 + 锐化以提高识别率。
- **translators 超时**：`translator.py` 设 `timeout=15` 防止网络卡死。
- **PyInstaller hidden imports**：`pytesseract`、`translators`、`PIL.ImageTk` 等库动态导入，需要显式 `--hidden-import`。
- **热键兼容性**：使用 pynput 库实现全局热键，兼容无管理员权限的受限环境。