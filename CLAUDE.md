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
  - **光比对 root 身份还不够，必须再确认解释器存活**：`Misc._root()` 只是纯 Python 属性遍历，一个已被 `destroy()` 的 root 仍等于它自己。`IconProvider._is_alive()` 用 `winfo_exists()`（抛 `TclError` 即已销毁）补上这一环；检测到已销毁时**当场抛 `RuntimeError` 并清空缓存**，而不是返回死句柄 —— 后者会在把图标配到某个活控件时才炸，报错位置离真正原因很远。没有 `winfo_exists` 的对象（测试里的假控件）按存活处理。回归防护：`test_app.py::test_icon_cache_invalidates_when_the_root_is_destroyed` 与 `test_icon_cache_still_works_with_fake_widgets`。
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
├── ui_theme.py               # 主题令牌：颜色 / 字体 / 间距 / DPI 换算 / 强调色派生
├── ui_widgets.py             # 自绘控件：圆角卡片 / 细滚动条 / 扁平按钮 / 分段选择器
├── ui_icons.py               # 图标缓存管理器 (PIL 程序化生成，随 Tk root 失效)
├── conftest.py               # pytest 共享夹具（会话级 Tk root、配置隔离）
├── test_app.py               # 单元测试：配置 / 剪贴板 / OCR 契约 / 主题与自绘控件
├── test_integration.py       # 集成测试：OCR 窗口几何、布局与异步翻译
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

**容器类型对不代表内容可用**：`pinned_items` 是唯一有结构的字段，因此额外做**逐元素**校验（`ConfigManager._clean_pinned_items`）—— 非 dict 的元素丢弃，`pos` 形状不对时只丢这个字段（保留钉住本身，别让用户的钉住因为一个坏坐标就消失）。清洗在三个边界上都做：`load()`（脏文件）、`set_pinned_items()`（写入）、`get_pinned_items()`（读取，让"返回的每个元素都是形状正确的 dict"成为硬保证）。**只校验 `isinstance(value, list)` 是不够的**：消费方 `pin_window` 对每个元素直接调 `item.get(...)`，列表里混进一个字符串就会抛 `AttributeError`，而这个异常被 `main._do_screenshot` 的 except 吞掉 —— 用户看到的是"点了钉住，什么都没发生，也没有任何提示"。

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

### 构建后自检（`build_exe.py` 已内置，不要绕过）

`build_exe.py` 在打包结束后会读回产物、核对模块清单，不合格就 `exit(1)`：

- `REQUIRED_MODULES` 里的模块必须都在包里。**新增本项目模块后要往这里加**；
- `FORBIDDEN_MODULES`（pandas / numpy / matplotlib / scipy / torch）必须都不在包里。

**为什么需要这道检查**：EXE 体积曾在两次构建之间从 **36MB 掉到 29MB**，事后产物被覆盖、无法复原，查不出究竟少了什么。体积变化本身无所谓，**静默少打模块才是问题** —— 最可疑的是 `translators` 的依赖树（`cryptography` / `lxml` / `qh3` / 四套 HTTP 客户端，合计约 7MB），它们全是动态导入，漏掉的后果是"翻译在 exe 里直接坏掉，但打包过程一切正常"。当前构建是**确定性**的（连测两次都是 36.15MB）。

读包内容时注意：**纯 Python 模块在 PYZ 里，而入口脚本 `main` 和所有原生扩展（`.pyd`/`.dll`）在顶层条目里，不在 PYZ**（例如 `win32\win32clipboard.pyd` 是以 `win32clipboard` 这个名字被 import 的）。只看 PYZ 会误报 `main` 和 `win32clipboard` 缺失。

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
pytest test_app.py test_integration.py test_pin_logic.py   # 58 个用例
python verify_app.py                                       # 环境自检，失败返回非零退出码
```

- 测试是 **hermetic** 的：`conftest.py` 提供会话级共享 Tk root（反复新建/销毁 root 会让 Tcl 解释器失效），`isolated_config` 夹具把配置重定向到临时目录，**不会读写用户真实配置**。
- 新增 UI 测试请复用 `tk_root` 与 `stub_ocr` 夹具，不要自行 `tk.Tk()`。
- **夹具 teardown 顺序陷阱**：pytest 逆序拆卸夹具。任何在 teardown 里调用 `PinWindow._on_close()` 之类的清理夹具，**必须显式依赖 `isolated_config`**，否则 monkeypatch 会先被还原，清理动作就写到了用户真实配置上（`test_pin_logic.py` 的 `_cleanup_pin_windows` 就是这个写法）。
- **`isolated_config` 必须连 `translator` 一起隔离**：`translator.py` 在**导入期**就 `from config import config_manager` 并构造了模块级单例 `Translator()`，而 `Translator.__init__` 当场把 `config_dir` 算成了 `history_file`。测试模块在**收集期**就 `from ocr_window import OcrWindow`，连带导入 `translator` —— 那时 fixture 还没运行，单例已经抓住了**用户真实目录**。所以只 `setattr(translator, "config_manager", cm)` 不够，**必须把单例上已经算好的 `history_file` 一起重定向**，否则从"隔离"上下文调用 `_save_history()` 会真的写进 `%APPDATA%/ScreenshotOCR/translation_history.json`。回归防护：`test_app.py::test_isolated_config_redirects_the_translator_singleton`。**教训**：凡是 `from config import config_manager` 这种模块级绑定，新增一个模块就要在 conftest 里补一处 —— 漏掉不会有任何报错，只会静默污染用户数据。
- **回归防护必须强制失败路径**：例如 OCR 契约测试要 `monkeypatch` 掉 `pytesseract.image_to_string` 让它抛异常，否则在装有 Tesseract 的机器上会走成功路径，断言恒真、形同虚设。
- `verify_app.py` 每一项都真的执行检查、可以失败；不要写死 `OK`。

## 已知注意事项

- **DPI 感知**：`main.py` 在 `if __name__ == "__main__":` 里（即**所有 import 之后**、任何窗口创建之前）调用 `ctypes.windll.shcore.SetProcessDpiAwareness(1)`，确保选区坐标与物理像素匹配。真实约束是"早于任何窗口创建"，不是"早于 import"。`SetProcessDpiAwareness` 全进程只生效一次，**不要**在别处再调 —— 那时 Tk 已在运行，只会拿到 `E_ACCESSDENIED` 并被 except 吞掉，属于"看起来有用其实无效"的代码。
- **多 Tk 解释器**：曾观察到同进程内并存多个 Tk 解释器时抛 `TclError: Can't find a usable init.tcl`，**但未能稳定复现**（后续连开 6 个 `tk.Tk()` 全部正常）。不管触发条件是什么，测试里都**不要**为了验证「两个 root 并存」而真的建多个解释器 —— 用带 `_root()` 方法的假控件直接测 `IconProvider._sync`（见 `test_integration.py::test_icon_cache_is_keyed_on_the_calling_widget_root`）。这是防御性选择，与上面那条观察是否复现无关。
- **Tesseract 预处理**：`ocr_engine.TesseractBackend._preprocess` 对小图自动放大，转灰度 + 对比度拉伸 + 锐化以提高识别率。该方法与识别引擎解耦，可在未安装 Tesseract 时单独测试。
- **translators 超时**：`translator.py` 设 `timeout=15` 防止网络卡死。
- **PyInstaller hidden imports**：`pytesseract`、`translators`、`PIL.ImageTk` 等库动态导入，需要显式 `--hidden-import`。
- **热键兼容性**：使用 pynput 库实现全局热键，兼容无管理员权限的受限环境。
- **Tesseract 子进程必须无控制台窗口**：本程序是 GUI 进程（`pythonw` / PyInstaller `--noconsole`），自身没有控制台。这类进程 spawn 一个**控制台子系统**程序时，Windows 会为子进程新建一个控制台窗口；用裸 `subprocess` 调用时该窗口**可见**，用户看到的就是「识别时一个空白小窗口一闪而过」。实测（由子进程自报 `GetConsoleWindow` + `IsWindowVisible`）：裸调用 → 有控制台且**可见**；`STARTF_USESHOWWINDOW`+`SW_HIDE` → 有控制台但不可见；`CREATE_NO_WINDOW` → 根本不创建控制台。**只有 `CREATE_NO_WINDOW` 可靠**。pytesseract 仅在 `run_tesseract()` 里做了抑制，而 `get_tesseract_version()` / `get_languages()` 是裸调用 —— 因此 `ocr_engine` 在 import 时把 `pytesseract.pytesseract.subprocess` 整体替换成 `_HiddenSubprocess`（注入 `creationflags=CREATE_NO_WINDOW`）。`test_app.py::test_tesseract_subprocess_never_creates_a_console_window` 是这条的回归防护，不要删除或简化。
- **`is_available()` 必须缓存**：OCR 窗口每次识别都会调用它，而它内部走 `pytesseract.get_tesseract_version()` —— 那是一次真实的 tesseract 进程 spawn。不缓存时每次识别要多花约 **500ms**（其中大部分是创建控制台窗口的开销；修复后约 60ms）。`ocr_engine._availability_cache` 以 tesseract 可执行文件路径为键，用户在「指定路径」引导里改过路径后会立刻重新检查，无需重启。
- **`translators` 必须延迟导入**：它的依赖树极重 —— 实测 `import translators` 耗时 **约 2.4 秒**、工作集 **+48MB**，占整个程序内存的 **80%**。它一次拖进 aiohttp / httpx / niquests / requests **四套 HTTP 客户端**，外加 `cryptography`、`lxml`、`multiprocess`、`pathos`、`psutil`、`tqdm` 等 40 多个包。而翻译只是 OCR 之后的次要功能，多数会话根本用不到。因此 `translator.py` 用 `_translators()` 在**首次真正翻译时**才导入，**绝不允许**在模块顶层写 `import translators`。实测收益：源码启动工作集 74.7M → 26.9M，打包后 EXE 119.8M → 59.6M，启动也快了 2.4 秒。`test_app.py::test_translator_does_not_import_the_heavy_engine_at_module_level` 是这条的回归防护。
- **`translators` 导入前必须钉住地区**：`import translators` **在导入期就会发网络请求** —— 它的模块体里直接写了 `tss = TranslatorsServer()`（`server.py:6205`），构造函数调用 `get_region_of_server()`（`server.py:5896`），后者请求 `geolocation.onetrust.com`、失败再退到 `httpbin.org`（`server.py:364`）。两个后果都很糟：① 探测失败抛 `TranslatorError`，**整个 import 直接失败** —— 用户点「翻译」看到的是一个跟 httpbin.org 有关的报错（实测 25 次独立进程里挂 2 次，`verify_app.py` 也因此随机失败）；② 那两次 `requests.get` **没设 timeout**，网络不通时可能挂很久。`server.py:344` 留了逃生口：`translators_default_region` 有值就在第一行直接返回、不发请求。所以 `translator._translators()` 在 `import translators` **之前**先 `os.environ.setdefault("translators_default_region", "CN")`（`_DEFAULT_REGION`）—— **顺序错了就等于没修**。用 `setdefault` 是为了不覆盖用户自己设的值，非中国大陆用户可设 `EN` 覆盖。回归防护：`test_app.py::test_translator_pins_the_region_before_importing_translators`（检查顺序）、`test_translator_does_not_override_a_user_chosen_region`、`test_translator_loads_without_any_network`（把 `socket.socket` 换成连接必抛异常的类，**断网也必须能加载**）。
- **`verify_app.py` 的依赖检查不能直接 `import translators`**：理由同上，那样会依赖网络、随机失败。它走应用自己的 `translator._translators()`，既稳定，测的又是应用真正使用的那条路径。
- **延迟导入的内存收益有前提：本次运行没点过翻译**。Python 无法可靠卸载已导入的模块 —— 用户第一次点「中文/英文」后，那 48MB 会一直留到程序重启（实测 50MB → 100MB）。**不要试图用 `del sys.modules["translators"]` 去"回收"**：它不会把内存还给操作系统，强行重新导入还有崩溃风险。真要"用完就降回来"，只能把翻译做成用完即退的独立子进程，复杂度明显上升，目前不做。
- **内存基线**（空转、无翻译，用于回归对比）：打包后 EXE **约 50~60MB 工作集 / 约 50MB 私有 / 10 个线程 / 空闲 CPU 0.000%**。逐阶段构成：空解释器 14.5M、tkinter +3.6M、Pillow +4.4M、pystray +1.7M、pynput +0.4M、pywin32 +1.4M、pytesseract +0.2M、**本项目全部模块 +0.3M**。也就是说内存几乎全由第三方库决定，**优化要往"少加载/晚加载第三方包"方向做，改自己的代码没有意义**。注意 `tesseract.exe` 是每次识别 spawn 的子进程、用完即退，它的内存从不计入本进程。
- **UI 主题与自绘控件**：`ui_theme.py` 是唯一的颜色/字体/间距来源，`ui_widgets.py` 放 Tk 原生做不到的件（圆角卡片、细滚动条、扁平按钮、分段选择器）。改界面前先读这两个文件的模块注释。
- **字体必须含中日韩字形**：`FONT_FAMILY` 是 `Microsoft YaHei UI`（同时含拉丁与中日韩字形）。**不要改回 `Segoe UI`** —— 它没有中文字形，Tk 只能逐字回退，中英文混排时字重/字距/基线全都不一致（实测症状：中文明显比英文粗）。注意 `Microsoft YaHei`（不带 ` UI`）这个名字在系统里**并不存在**，Tk 对不存在的字体名不报错、只静默回退，所以 `test_app.py::test_ui_font_family_is_actually_installed` 会拦住它。
- **字号用「点」（正数），间距用 `px()`（逻辑像素）**：本程序是 DPI 感知的，Tk 会把点按 `tk scaling` 换算成物理像素（实测本机 150% 缩放，`tk scaling = 2.0`）。而 `padx`/`pady`/`width`/`height` 的单位是**物理像素**，直接写 12 在 150% 屏上只有 8 个逻辑像素、观感偏挤 —— 所以间距一律过 `ui_theme.px()`。窗口尺寸同理按 DPI 缩放（见 `ocr_window._compute_window_size`）。
- **`RoundedCard` 的 Canvas 必须显式设 `width=1, height=1`**：Tk 的 Canvas **默认请求尺寸很大** —— 实测 **382x268**（100% DPI），并随显示器缩放线性放大（150% 下约 573x402）。这个请求尺寸会一路传播到外层 Frame，不压掉的话包着卡片的容器会虚报几百像素高，在窗口不够高时把空间吃光，排在它后面打包的兄弟控件被压成 0 高度、`winfo_ismapped()` 变 0 —— 实测踩过一次，整条状态栏消失。这条有两个回归防护：`test_app.py::test_rounded_card_does_not_inflate_its_parent_request`（根因层，断言 `reqsize <= 2`）与 `test_integration.py::test_ocr_window_layout_is_not_over_subscribed`（现象层）。
- **Tk 的 packer 在空间不够时按调用顺序分配**：固定尺寸的"外框"（操作栏、状态栏）要先打包，`expand=True` 的内容区放最后。这是惯用法，但**它本身不是上面那条 bug 的根因** —— 真正的根因是请求尺寸被虚报。两者都要做。
- **Tk 的 Text 没有 line-height**：行距只能靠 `spacing1/2/3` 模拟，而三者语义不同 —— `spacing1/3` 只作用于**逻辑行**的上下，`spacing2` 才作用于同一逻辑行的**折行之间**。只设 `spacing1/3` 的话，长行折行处会紧贴上一行、硬换行处却很松，同一段文字里出现两种行距。正确组合是 `spacing1=0, spacing2=spacing3=extra`（见 `ocr_window._line_spacing`）。
- **圆角只能自绘**：Tk 没有 `border-radius`。`RoundedCard` 用 `create_polygon(smooth=True)` 画圆角矩形，内容控件叠在上面 —— 因此**内容的内缩量必须 >= 圆角半径**，否则直角的控件会盖住圆角（`RoundedCard` 内部已强制 `max(padding, radius)`）。浮动工具栏的窗口圆角靠 `-transparentcolor` 抠出来（见 `screenshot_overlay._show_toolbar`）。
- **`tk.Scrollbar` 一定带上下箭头**，`ttk.Scrollbar` 在 Windows 上受原生主题限制、做不出细圆角滑块 —— 所以滚动条用 `ui_widgets.ThinScrollbar` 自绘。`tk.Button` 即使 `relief="flat"` 在 Windows 上**仍会画立体边框**，必须同时 `bd=0` + `highlightthickness=0`（见 `ui_widgets.flat_button`）。
- **UI 改动必须两种主题都验证**：`%APPDATA%` 里的配置决定明暗，只测一种会漏掉写死的色值。`_ui_shot.py` 这类临时探针的写法：`config_manager.is_dark_mode = lambda: False` 强制浅色，再用 `ImageGrab` 抓窗口（**探针自己也要先 `SetProcessDPIAware()`，否则 Tk 的逻辑坐标与 ImageGrab 的物理像素对不上，会抓到别的窗口**；无边框浮窗还要 `-topmost`，否则会被别的窗口盖住）。
- **pandas 体积陷阱**：`pytesseract` 会 `try: import pandas`（仅服务于 `Output.DATAFRAME`，本项目用不到）。一旦运行环境装了 pandas，就会连带载入 numpy + OpenBLAS，实测多占 **约 63MB 工作集 / 528MB 私有内存 / 23 个线程**。`build_exe.py` 里的 `--exclude-module=pandas` 是安全的（pytesseract 的导入有 try/except 保护），不要移除；开发环境同样建议使用不含 pandas 的 venv。