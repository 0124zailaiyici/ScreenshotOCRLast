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
- **配置路径**：配置、钉住图片、翻译历史一律存放在 `%APPDATA%/ScreenshotOCR/`，exe 可随意移动位置。任何新增的持久化数据都必须落到 `config_manager.config_dir`，禁止使用相对当前工作目录的路径。
- **PhotoImage 生命周期**：`PhotoImage` 隶属于创建它的 Tk 解释器。把属于解释器 A 的句柄配置给解释器 B 的控件会抛 `TclError: image "pyimageN" doesn't exist`。`ui_icons.IconProvider.get_*(color, master=...)` 接受调用方控件，缓存以**该控件所属的 root** 为准并在其变化时失效。不要用 `tkinter._default_root` 判断 root 是否变化 —— 它只在为 None 时才被覆盖，两个 root 并存时识别不出来。新建 `PhotoImage` 一律显式传 `master`。
- **OCR 失败契约**：识别失败必须抛 `ocr_engine.OcrError`，由 `ocr_window` 展示错误与修复引导。`OcrError.kind`（`not_found` / `lang_pack` / `other`）决定展示哪种引导 —— 只有 `not_found` 才弹「指定 tesseract.exe 路径」对话框。严禁把异常吞掉后返回形如 `"识别失败: ..."` 的字符串。
- **截图会话锁**：`main._screenshot_lock` 保护单次截图会话，**从热键触发一直持有到会话结束**（用户可能长时间开着 OCR 窗口，这属于正常情况）。只有确认消费队列的 Tk 线程已死亡时才回收遗留锁。**绝不允许按时间阈值回收**：`threading.Lock` 没有属主概念，释放一个仍被合法持有的锁会让两个会话并发执行，并使后续 `release` 抛 `release unlocked lock`。

## 目录结构

```
.
├── main.py                   # 入口：持久化 Tk 线程 + 热键 + 托盘 + 单实例 IPC
├── config.py                 # JSON 配置读写 (%APPDATA%/ScreenshotOCR/)
├── screenshot_overlay.py     # 全屏选区覆盖层 + 浮动工具栏
├── pin_window.py             # 钉住浮窗
├── ocr_window.py             # OCR 文字识别窗口 + 翻译
├── translator.py             # 翻译模块 (translators 库)
├── ocr_engine.py             # OcrBackend 抽象 + TesseractBackend + OcrError + 工厂
├── clipboard_manager.py      # 剪贴板 (pywin32 CF_DIB/CF_UNICODETEXT)
├── hotkey_listener.py        # 全局热键 (pynput)
├── tray_app.py               # 系统托盘 (pystray)
├── ui_theme.py               # 主题系统（深色/浅色 + AccentColor）
├── ui_icons.py               # 图标缓存管理器 (PIL 程序化生成，随 Tk root 失效)
├── conftest.py               # pytest 共享夹具（会话级 Tk root、配置隔离）
├── test_app.py               # 单元测试：配置 / 剪贴板 / OCR 契约
├── test_integration.py       # 集成测试：OCR 窗口几何与异步翻译
├── test_pin_logic.py         # 集成测试：钉住窗口位置 / 边界 / 持久化
├── verify_app.py             # 真实自检脚本（会失败、非零退出码）
├── build_exe.py              # PyInstaller 打包脚本
├── assets/                   # 本地资源目录
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

位置：`%APPDATA%/ScreenshotOCR/screenshot_ocr_config.json`，首次运行自动生成。
加载时会按 `ConfigManager._SCHEMA` 做类型校验，类型不符的条目会被丢弃并回落到默认值。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `hotkey` | `<alt>+x` | 全局快捷键 |
| `ocr_backend` | `tesseract` | OCR 引擎 |
| `ocr_lang` | `chi_sim+eng` | 识别语言 |
| `tesseract_path` | `""` | Tesseract 路径（空则自动查找） |
| `auto_copy_text` | `false` | 自动复制文本（已废弃，保持 false） |
| `auto_copy_image` | `false` | 自动复制图片（已废弃，保持 false） |
| `notification_enabled` | `true` | 托盘通知 |
| `pinned_items` | `[]` | 持久化的钉住窗口 |

同一目录下还有：`data/pinned/`（钉住图片）与 `translation_history.json`（翻译历史，最多保留 50 条）。

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

配置存放在 `%APPDATA%`，**不需要**再往 `dist/` 复制配置文件。

打包务必使用不含 pandas/numpy 的干净 venv，原因见下方「pandas 体积陷阱」。

## 依赖

以 `requirements.txt` 为准：

```
pynput>=1.7.6        # 全局热键支持
pystray>=0.19.5      # 系统托盘图标支持
pytesseract>=0.3.10  # Tesseract OCR Python 封装
Pillow>=10.0.0       # 图像处理库 (PIL)
pywin32>=306         # Windows API 访问 (剪贴板)
translators>=5.8.0   # 多引擎翻译支持
pytest>=7.0.0        # 单元测试框架
```

## 测试与验证

```bash
pytest test_app.py test_integration.py test_pin_logic.py   # 30 个用例
python verify_app.py                                       # 环境自检，失败返回非零退出码
```

- 测试是 **hermetic** 的：`conftest.py` 提供会话级共享 Tk root（反复新建/销毁 root 会让 Tcl 解释器失效），`isolated_config` 夹具把配置重定向到临时目录，**不会读写用户真实配置**。
- 新增 UI 测试请复用 `tk_root` 与 `stub_ocr` 夹具，不要自行 `tk.Tk()`。
- **夹具 teardown 顺序陷阱**：pytest 逆序拆卸夹具。任何在 teardown 里调用 `PinWindow._on_close()` 之类的清理夹具，**必须显式依赖 `isolated_config`**，否则 monkeypatch 会先被还原，清理动作就写到了用户真实配置上（`test_pin_logic.py` 的 `_cleanup_pin_windows` 就是这个写法）。
- **回归防护必须强制失败路径**：例如 OCR 契约测试要 `monkeypatch` 掉 `pytesseract.image_to_string` 让它抛异常，否则在装有 Tesseract 的机器上会走成功路径，断言恒真、形同虚设。
- `verify_app.py` 每一项都真的执行检查、可以失败；不要写死 `OK`。

## 已知注意事项

- **DPI 感知**：`main.py` 在 import 任何 GUI 模块前调用 `SetProcessDPIAware()`，确保选区坐标与像素匹配。
- **同一进程内不要并存 3 个以上 Tk 解释器**：实测会让 Tcl 找不到自己的库，抛 `TclError: Can't find a usable init.tcl`，且是否触发不稳定（会表现为偶发失败）。因此测试里**不要**为了验证「两个 root 并存」而真的 `tk.Tk()` 建多个解释器 —— 用带 `_root()` 方法的假控件直接测 `IconProvider._sync`（见 `test_integration.py::test_icon_cache_is_keyed_on_the_calling_widget_root`）。
- **Tesseract 预处理**：`ocr_engine.TesseractBackend._preprocess` 对小图自动放大，转灰度 + 对比度拉伸 + 锐化以提高识别率。该方法与识别引擎解耦，可在未安装 Tesseract 时单独测试。
- **translators 超时**：`translator.py` 设 `timeout=15` 防止网络卡死。
- **PyInstaller hidden imports**：`pytesseract`、`translators`、`PIL.ImageTk` 等库动态导入，需要显式 `--hidden-import`。
- **热键兼容性**：使用 pynput 库实现全局热键，兼容无管理员权限的受限环境。
- **Tesseract 子进程必须无控制台窗口**：本程序是 GUI 进程（`pythonw` / PyInstaller `--noconsole`），自身没有控制台。这类进程 spawn 一个**控制台子系统**程序时，Windows 会为子进程新建一个控制台窗口；用裸 `subprocess` 调用时该窗口**可见**，用户看到的就是「识别时一个空白小窗口一闪而过」。实测（由子进程自报 `GetConsoleWindow` + `IsWindowVisible`）：裸调用 → 有控制台且**可见**；`STARTF_USESHOWWINDOW`+`SW_HIDE` → 有控制台但不可见；`CREATE_NO_WINDOW` → 根本不创建控制台。**只有 `CREATE_NO_WINDOW` 可靠**。pytesseract 仅在 `run_tesseract()` 里做了抑制，而 `get_tesseract_version()` / `get_languages()` 是裸调用 —— 因此 `ocr_engine` 在 import 时把 `pytesseract.pytesseract.subprocess` 整体替换成 `_HiddenSubprocess`（注入 `creationflags=CREATE_NO_WINDOW`）。`test_app.py::test_tesseract_subprocess_never_creates_a_console_window` 是这条的回归防护，不要删除或简化。
- **`is_available()` 必须缓存**：OCR 窗口每次识别都会调用它，而它内部走 `pytesseract.get_tesseract_version()` —— 那是一次真实的 tesseract 进程 spawn。不缓存时每次识别要多花约 **500ms**（其中大部分是创建控制台窗口的开销；修复后约 60ms）。`ocr_engine._availability_cache` 以 tesseract 可执行文件路径为键，用户在「指定路径」引导里改过路径后会立刻重新检查，无需重启。
- **pandas 体积陷阱**：`pytesseract` 会 `try: import pandas`（仅服务于 `Output.DATAFRAME`，本项目用不到）。一旦运行环境装了 pandas，就会连带载入 numpy + OpenBLAS，实测多占 **约 63MB 工作集 / 528MB 私有内存 / 23 个线程**。`build_exe.py` 里的 `--exclude-module=pandas` 是安全的（pytesseract 的导入有 try/except 保护），不要移除；开发环境同样建议使用不含 pandas 的 venv。