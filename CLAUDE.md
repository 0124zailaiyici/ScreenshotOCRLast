# ScreenshotOCR

Windows 截图工具，支持截图后三选一操作：钉住到屏幕、OCR 识别文字、复制图片。常驻系统托盘，`Alt+X` 全局热键触发。

## 技术栈

- Python 3.10+, **无外部 GUI 框架**，纯 Tkinter 做 GUI
- **pystray** 系统托盘
- **Pillow** 图像处理
- **pywin32** Windows 剪贴板操作
- **pynput** 全局热键（非注册表方式）
- **pytesseract** OCR 识别（需独立安装 Tesseract-OCR 5.x）
- **rapidocr-onnxruntime** OCR 识别（中文准确率更高，模型随程序打包，无需外部安装）
- **translators** 中英翻译
- **PyInstaller** 打包为单文件 exe

## 架构 / 数据流

```
用户按热键
  → hotkey_listener.py (pynput 全局热键 → 放入 queue)
  → main.py (_on_screenshot_trigger → 放入持久化 Tk 线程队列)
    → screenshot_overlay.py (全屏覆盖层，拖拽选区域)
      → 浮动工具栏 [钉住|识字|复制]
        → pin_window.py (无边框浮窗，拖动 / 滚轮缩放 / 右键菜单)
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
├── pin_window.py             # 钉住浮窗：拖动 / 滚轮缩放 / 右键菜单
├── ocr_window.py             # OCR 文字识别窗口 + 翻译
├── translator.py             # 翻译模块 (translators 库)
├── ocr_engine.py             # OcrBackend 抽象 + TesseractBackend + RapidOcrBackend + OcrError + 工厂
├── clipboard_manager.py      # 剪贴板 (pywin32 CF_DIB/CF_UNICODETEXT)
├── hotkey_listener.py        # 全局热键 (pynput)
├── tray_app.py               # 系统托盘 (pystray)
├── ui_theme.py               # 主题令牌：颜色 / 字体 / 间距 / DPI 换算 / 强调色派生
├── ui_widgets.py             # 自绘控件：圆角卡片 / 细滚动条 / 扁平按钮 / 分段选择器 / 右键菜单
├── ui_icons.py               # 图标缓存管理器 (PIL 程序化生成，随 Tk root 失效)
├── conftest.py               # pytest 共享夹具（会话级 Tk root、配置隔离）
├── test_app.py               # 单元测试：配置 / 剪贴板 / OCR 契约 / 主题与自绘控件
├── test_integration.py       # 集成测试：OCR 窗口几何、布局与异步翻译
├── test_pin_logic.py         # 集成测试：钉住窗口位置 / 边界 / 持久化
├── verify_app.py             # 真实自检脚本（会失败、非零退出码）
├── build_exe.py              # PyInstaller 打包脚本
├── make_icon.py              # 生成 assets/app.ico（设计与托盘图标一致）
├── install.py                # 安装/卸载：放固定位置 + 建快捷方式 + 登记卸载入口
├── assets/                   # 本地资源目录（app.ico）
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

所有的 OCR 后端实现 `OcrBackend` 接口（`recognize()`、`is_available()`、`name`），通过 `ocr_engine.create_ocr_engine(backend_name=None)` 工厂创建。传 `None` 时读 `config_manager.get("ocr_backend")`；**名字未知时回落到 `DEFAULT_BACKEND`**，而不是抛异常 —— 配置写坏不该让识字功能整体不可用。

目前两个后端，**默认 RapidOCR**（`DEFAULT_BACKEND`），托盘菜单「识别引擎」里可切换（单选），选择写回配置：

| | RapidOCR | Tesseract |
|---|---|---|
| 中文 | **正确**（`真实渲染`） | 错字（`真实泻染`、`自检`→`目检`） |
| 拉丁/数字 | 对，**模型自己会输出空格**；`rebuild_spaces` 只在汉字边界补 | 对，空格保留 |
| 用户真实难图相似度 | **100.0%**（**注意：该指标去掉了所有空白再比，看不见空格错误**） | 96.9% |
| 速度 | 约 1.2s | 约 0.5s |
| 依赖 | 模型随程序打包（+81MB） | 需外部安装 Tesseract 5.x |
| 预处理 | **不做任何预处理**（2x 放大会掉到 77.1%） | 灰度 → 2x BICUBIC → Otsu |

- **`RapidOcrBackend` 必须懒加载**：`import rapidocr_onnxruntime` 写在 `_module()` 里，`_get_engine()` 才真正构造 `RapidOCR()`（构造要读三个 ONNX 模型，很慢）。详见下方「`is_available()` 绝不能用 `import` 来判断」。
- **`rebuild_spaces` 只在「汉字 ↔ ASCII 字母数字」的边界补空格，别的地方一律不动**。这条规则是拿真实截屏量出来的，**不要再改回"拉丁文内部按间隙插"**：
  - 模型**自己就会输出空格字符**（`item[4]` 里就有 `' '` 项，与 `item[1]` 完全一致），它只是偶尔漏，不是全吞。所以"按间隙补"能捞的收益有限，风险却很大。
  - 拉丁文内部的间隙**分不开**：真实截屏上，不是空格的地方 `d|e`(detail) 5px、`h|e`(head) 6px、`w|o` 5px、`m|j` 5px；是空格的地方 `m|' '`(npm run) 5px、`3|/`(173 / fail) 11px。区间重叠，**任何阈值都分不开**（0.35 拆散 `passed`、0.6 粘住 `60 passed`，这是早期就记录过的老问题）。
  - 两类错误代价极不对称，**这是复制工具**：漏一个空格只是难看；多一个空格会让 `look-at-real-size.m js`、`d eepseek` 这种路径和标识符**直接废掉**。改之前那一版在真实截屏上触发 6 次、错了 5 次。
  - 用户反馈的就是这个现象（"识别总是出来有空格"）。**注意旧指标骗了我们**：当初说"相似度 100.0%"是 `difflib` 在**去掉所有空白之后**比的，**根本看不见空格错误** —— 评价 OCR 的空格必须单独看空格，不能只看去空白相似度。
  - 边界判定用 `_is_ideograph` + `_is_word_char`，**不是** `_is_cjk`：
    - `_is_cjk` 把**中文标点**也算进来，用它当边界会插出 `全部通过： pass`、`510、 left`（中文标点后面不加空格）。
    - `_is_word_char` **必须限定 ASCII**（`ch.isascii() and ch.isalnum()`）。**不能只用 `str.isalnum()`**：汉字在 Unicode 里也算字母（`"行".isalnum()` 是 `True`），那样「汉字↔汉字」会被判成边界，插出 `运 行命 令`、`02生 活工作台`。
  - 阈值 `GAP_RATIO=0.45` / `MIN_GAP_PX=2` 只用来判断"边界上到底有没有真空格"（`第1章` 这种没空格的不能插）。
  - 回归防护：`test_app.py::test_rapidocr_rebuilds_spaces_only_at_cjk_boundaries`（含 `isalnum` 陷阱与中文标点两条）、`test_rapidocr_rebuild_spaces_leaves_real_words_intact`（用实测间隙复现 `workbench` 被拆的历史 bug）。三条变异（`isalnum`、`_is_cjk` 边界、旧的"两侧非 CJK 就插"）都已验证会被拦住。
- **`return_word_box=True` 必须传给 `__call__`，不能传给构造函数**（`main.py:82` 读的是 `kwargs.get("return_word_box", False)`），否则拿不到字符框，`rebuild_spaces` 直接失效。
- **`ocr_window._do_ocr` 会自动降级**：请求的引擎不可用时按 `FALLBACK_ORDER` 换下一个，并在状态栏标注「已降级」与降级原因。失败时 `result["error_engine"]` 记下是哪个引擎失败的 —— 只有 `kind == "not_found"` **且失败的是 Tesseract** 才弹「指定 tesseract.exe 路径」引导。

### 钉住窗口的右键菜单

钉住窗口支持拖动、滚轮缩放、**右键菜单**。菜单由 `ui_widgets.ContextMenu` 自绘（圆角 + 深色），**不用 `tk.Menu`** —— Tk 在 Windows 上自绘的弹出菜单不受系统深色主题控制，会弹出一个浅灰方块，是这个全自绘界面里唯一不搭的东西。

菜单项刻意只有三条：**复制图片**、**识别文字…**、**取消钉住**（中间一条分隔线把不可逆的那条隔开）。

**旧行为是右键直接关闭窗口** —— 于是钉住的图既没法复制、也没法重新识别：想复制只能重新 `Alt+X` 截一次，而截图工具栏是"钉住 / 识字 / 复制"三选一，**不能都要**。改成菜单之后关闭挪进菜单里，`Esc` 仍然直接关闭。

几个实现要点：

- **复制必须用 `original_image`，不能用 `label` 上显示的图**。后者是滚轮缩放过的，直接复制出去画质会掉。这个区别只有在缩放之后才暴露，所以回归防护里刻意先缩到 50%。
- **「识别文字」要把识字窗口挂在钉住窗口的父窗口下**（`self.root.master`），而不是钉住窗口本身 —— 否则关掉钉住会把识字窗口一起销毁。
- **菜单打开时要暂停钉住窗口的置顶定时器**。`_ensure_topmost` 每 2 秒把窗口抬到 `HWND_TOPMOST`，会把刚弹出来的菜单盖住。
- **`ContextMenu` 的关闭路径有四条**：点中某项、点菜单矩形之外、`Esc`、焦点离开。前两条靠 `grab_set()`（应用内的点击都会被重定向到菜单窗口，即便点在别的窗口上，坐标也落在矩形外，所以命中判定必须能识别出来）；第四条靠 `focus_force()` 之后的 `<FocusOut>` 兜底 —— 本地 grab 管不到应用外的点击。
- **`_on_close` 要先关菜单再销毁窗口**：菜单持有 grab，直接销毁父窗口会留下一个孤儿 Toplevel。
- **菜单的 `close()` 必须可重复调用**：关闭路径有四条，重复调用是常态而不是异常。
- **边界收拢**：菜单在屏幕右下角弹出时必须往回收，否则会被裁掉一半。定位同样要 `withdraw()` → 一次性 `geometry()` → `deiconify()`（`overrideredirect` 的通用坑）。

**回归防护的坑（第一版是恒真的，证伪时才发现）**：

- 「右键弹菜单」不能直接调 `_on_context_menu` —— 那样只验证了处理函数，把 `bind` 改回 `_on_close` 照样通过。**必须真的 `event_generate("<Button-3>")`**。
- 「点分隔线不执行任何东西」单独测是恒真的：`_row_at` 会跳过分隔线返回 -1，那条有 bug 的代码根本走不到。真正会暴露问题的是**点分隔线后面那一项**，所以两者合并在 `test_context_menu_dispatches_to_the_right_item` 里测。
- `_rows` 与 `items` **都包含**分隔线，两者下标是对齐的 —— 不要凭空假设它们会错位。

**`<Escape>` 依赖键盘焦点**：无边框窗口默认拿不到焦点，测试里必须先 `focus_force()`，否则焦点可能落在已被销毁的窗口上、键盘事件送不到。真实运行时新建的钉住窗口是拿得到焦点的（探针验证过），测试里显式聚焦只是为了不受用例执行顺序影响。

## 配置项

位置：`%APPDATA%/ScreenshotOCR/screenshot_ocr_config.json`，首次运行自动生成。
加载时会按 `ConfigManager._SCHEMA` 做类型校验，类型不符的条目会被丢弃并回落到默认值。

**容器类型对不代表内容可用**：`pinned_items` 是唯一有结构的字段，因此额外做**逐元素**校验（`ConfigManager._clean_pinned_items`）—— 非 dict 的元素丢弃，`pos` 形状不对时只丢这个字段（保留钉住本身，别让用户的钉住因为一个坏坐标就消失）。清洗在三个边界上都做：`load()`（脏文件）、`set_pinned_items()`（写入）、`get_pinned_items()`（读取，让"返回的每个元素都是形状正确的 dict"成为硬保证）。**只校验 `isinstance(value, list)` 是不够的**：消费方 `pin_window` 对每个元素直接调 `item.get(...)`，列表里混进一个字符串就会抛 `AttributeError`，而这个异常被 `main._do_screenshot` 的 except 吞掉 —— 用户看到的是"点了钉住，什么都没发生，也没有任何提示"。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `hotkey` | `<alt>+x` | 全局快捷键 |
| `ocr_backend` | `rapidocr` | OCR 引擎（`rapidocr` / `tesseract`，见 `ocr_engine.BACKEND_LABELS`） |
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
  --hidden-import rapidocr_onnxruntime \
  --hidden-import onnxruntime \
  --collect-data rapidocr_onnxruntime \
  main.py
```

配置存放在 `%APPDATA%`，**不需要**再往 `dist/` 复制配置文件。

打包务必使用不含 pandas 的干净 venv，原因见下方「pandas 体积陷阱」。**但 numpy 必须装着** —— onnxruntime 硬依赖它。

### 构建后自检（`build_exe.py` 已内置，不要绕过）

`build_exe.py` 在打包结束后会读回产物、核对模块清单，不合格就 `exit(1)`：

- `REQUIRED_MODULES` 里的模块必须都在包里。**新增本项目模块后要往这里加**；
- `REQUIRED_DATA` 里的**数据文件**必须都在包里（目前是 RapidOCR 的三个 ONNX 模型 + `config.yaml`）；
- `FORBIDDEN_MODULES`（pandas / matplotlib / scipy / torch）必须都不在包里。**numpy 不在这个名单里** —— 它是 onnxruntime 的硬依赖，排掉它等于把 RapidOCR 后端一起排掉。

**为什么需要这道检查**：EXE 体积曾在两次构建之间从 **36MB 掉到 29MB**，事后产物被覆盖、无法复原，查不出究竟少了什么。体积变化本身无所谓，**静默少打模块才是问题** —— 最可疑的是 `translators` 的依赖树（`cryptography` / `lxml` / `qh3` / 四套 HTTP 客户端，合计约 7MB），它们全是动态导入，漏掉的后果是"翻译在 exe 里直接坏掉，但打包过程一切正常"。这道检查**真的拦下过东西**：第一次把 RapidOCR 打进去时 `--collect-data` 漏了模型，自检直接报「数据文件没打进包」并 `exit(1)`。

**模型文件必须靠 `--collect-data` 带**：`ocr_engine` 里 `import rapidocr_onnxruntime` 写在函数内，PyInstaller 的静态分析跟不到；而 `.onnx` 是**数据文件**，`--hidden-import` 只管模块、不管数据。漏掉的表现是"程序能启动、托盘能切引擎，一识别就报模型找不到"。

**自检自己也会写错**：`REQUIRED_DATA` 里的名字必须写成**归一化后的点分形式**（`rapidocr_onnxruntime.models.xxx.onnx`），因为 `_read_bundled_entries` 会把 CArchive 里的路径分隔符换成点。第一版这里写的是带斜杠的路径，于是模型明明打进去了却报"缺失" —— **写完自检要拿真实产物对一遍**。

读包内容时注意：**纯 Python 模块在 PYZ 里，而入口脚本 `main` 和所有原生扩展（`.pyd`/`.dll`）在顶层条目里，不在 PYZ**（例如 `win32\win32clipboard.pyd` 是以 `win32clipboard` 这个名字被 import 的）。只看 PYZ 会误报 `main` 和 `win32clipboard` 缺失。

### 体积

打包两个引擎后 EXE 是 **117.4 MB**（只打 Tesseract 时是 36.2 MB）。构成：onnxruntime `capi` 约 37.6MB、numpy 约 15MB、三个 ONNX 模型约 15.4MB，其余是原有的 36MB。这是「中文识别准确率」的代价，**不是配置问题，压不下去** —— onnxruntime 的 DLL 和模型都是必需项。

### 图标

`python make_icon.py` 生成 `assets/app.ico`（透明底，16/24/32/48/64/128/256 共 7 个尺寸），`build_exe.py` 用 `--icon` 嵌入。设计复用**托盘图标那台相机**，所以任务栏 / 开始菜单 / 托盘三处图形一致。

- **先按 64 的原始坐标放大 16 倍画到 1024，再交给 Pillow 逐级缩小**。直接在小画布上画，细线会糊成一团 —— 这是图标的标准做法。
- **透明底**，而托盘图标是实心方块（深色模式下就是一块深灰）。装到开始菜单里是个方块会很难看。
- 颜色**钉死**成项目主色，不用系统强调色 —— 图标是固定的品牌资产，不该随用户设置变化。

### 安装与分发（`install.py`）

```bash
python install.py              # 安装（默认装完启动）
python install.py --no-start   # 安装但不启动
python install.py --uninstall  # 卸载
```

装到 `%LOCALAPPDATA%\Programs\ScreenshotOCR`，建开始菜单 + 桌面快捷方式，并在 `HKCU\...\Uninstall\ScreenshotOCR` 登记「应用和功能」条目。**全程不需要管理员权限**，不往 `Program Files` 写东西。

**不打包成 Inno Setup / NSIS**：这是单文件绿色 exe，"安装"本质只有三步（放固定位置、建快捷方式、留卸载入口），为它引入一整套安装框架不划算。

踩过的坑，改这里之前先看：

- **桌面路径必须问 shell 拿**（`SHGetFolderPathW(CSIDL_DESKTOPDIRECTORY)`），**不能拼 `%USERPROFILE%\Desktop`**。本机桌面就是 `D:\桌面`（被重定向过），硬拼出来的快捷方式用户根本看不见。开始菜单同理。
- **`taskkill` 是异步的**：它返回时进程只是"收到终止信号"，文件句柄还没释放，紧接着复制 exe 会 `PermissionError: [Errno 13]`。覆盖安装必现（第一次安装不现，因为旧实例跑的是 `dist\` 里的另一个文件）。`_stop_running()` 必须轮询等进程真的消失。
- **批处理删不掉自己所在的目录**。所以 `卸载.cmd` 先把自身复制到 `%TEMP%` 再重新执行，于是 `rd` 的目标是个普通目录。**不要用** `start "" cmd /c "... rd /s /q "路径""` 那种绕法 —— 嵌套引号在 cmd 里极不可靠，内层引号会和外层配对，`rd` 拿到的路径是断的、目录根本删不掉（第一版就这么写的，跑一遍才发现）。
- **`start` 一个 `.cmd` 时 Windows 会用 `cmd /K`**，脚本跑完留下一个不关的黑窗口。必须显式写 `start "" /min cmd /c "路径"`。
- **COM 对象要在 `CoUninitialize()` 之前丢掉引用**（`del link, shell`），否则每次建快捷方式都会往 stderr 吐一行 `Win32 exception occurred releasing IUnknown`。
- **`UNINSTALL_KEY` 别写成 `r"...\Uninstall\\" + APP_NAME`** —— 原始字符串末尾的 `\\` 是**两个**反斜杠。`winreg` 容忍，`reg delete` 不容忍，卸载时登记项就删不掉。
- **卸载不动用户数据**：`%APPDATA%\ScreenshotOCR`（配置、钉住图片、翻译历史）保留，重装后设置还在。
- **不设开机自启**：这是用户明确选的（托盘工具确实需要常驻才能用热键，但不替用户决定）。
- **Task Manager 里会看到两个同名进程**：PyInstaller onefile = 引导器父进程（约 7.6MB）+ 解包后的真身（几十 MB）。正常现象，不是跑了两个实例。

## 依赖

以 `requirements.txt` 为准：

```
pynput>=1.7.6                  # 全局热键支持
pystray>=0.19.5                # 系统托盘图标支持
pytesseract>=0.3.10            # Tesseract OCR Python 封装（需另装 Tesseract-OCR 5.x）
rapidocr-onnxruntime>=1.3.0    # RapidOCR（PaddleOCR 模型 + ONNX Runtime，随程序打包）
Pillow>=10.0.0                 # 图像处理库 (PIL)
pywin32>=306                   # Windows API 访问 (剪贴板)
translators>=5.8.0             # 多引擎翻译支持
pytest>=7.0.0                  # 单元测试框架
```

## 测试与验证

```bash
pytest test_app.py test_integration.py test_pin_logic.py   # 89 个用例
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
- **Tesseract 预处理**：`ocr_engine.TesseractBackend._preprocess` = 灰度 → 小图 2x BICUBIC 放大 → **Otsu 二值化**。该方法与识别引擎解耦，可在未安装 Tesseract 时单独测试。**不要加对比度增强，也不要加锐化** —— 详见下方「OCR 识别率排查记录」。
- **translators 超时**：`translator.py` 设 `timeout=15` 防止网络卡死。
- **PyInstaller hidden imports**：`pytesseract`、`translators`、`PIL.ImageTk` 等库动态导入，需要显式 `--hidden-import`。
- **热键兼容性**：使用 pynput 库实现全局热键，兼容无管理员权限的受限环境。
- **Tesseract 子进程必须无控制台窗口**：本程序是 GUI 进程（`pythonw` / PyInstaller `--noconsole`），自身没有控制台。这类进程 spawn 一个**控制台子系统**程序时，Windows 会为子进程新建一个控制台窗口；用裸 `subprocess` 调用时该窗口**可见**，用户看到的就是「识别时一个空白小窗口一闪而过」。实测（由子进程自报 `GetConsoleWindow` + `IsWindowVisible`）：裸调用 → 有控制台且**可见**；`STARTF_USESHOWWINDOW`+`SW_HIDE` → 有控制台但不可见；`CREATE_NO_WINDOW` → 根本不创建控制台。**只有 `CREATE_NO_WINDOW` 可靠**。pytesseract 仅在 `run_tesseract()` 里做了抑制，而 `get_tesseract_version()` / `get_languages()` 是裸调用 —— 因此 `ocr_engine` 在 import 时把 `pytesseract.pytesseract.subprocess` 整体替换成 `_HiddenSubprocess`（注入 `creationflags=CREATE_NO_WINDOW`）。`test_app.py::test_tesseract_subprocess_never_creates_a_console_window` 是这条的回归防护，不要删除或简化。
- **`is_available()` 必须缓存**：OCR 窗口每次识别都会调用它，而它内部走 `pytesseract.get_tesseract_version()` —— 那是一次真实的 tesseract 进程 spawn。不缓存时每次识别要多花约 **500ms**（其中大部分是创建控制台窗口的开销；修复后约 60ms）。`ocr_engine._availability_cache` 以 tesseract 可执行文件路径为键，用户在「指定路径」引导里改过路径后会立刻重新检查，无需重启。
- **`translators` 必须延迟导入**：它的依赖树极重 —— 实测 `import translators` 耗时 **约 2.4 秒**、工作集 **+48MB**，占整个程序内存的 **80%**。它一次拖进 aiohttp / httpx / niquests / requests **四套 HTTP 客户端**，外加 `cryptography`、`lxml`、`multiprocess`、`pathos`、`psutil`、`tqdm` 等 40 多个包。而翻译只是 OCR 之后的次要功能，多数会话根本用不到。因此 `translator.py` 用 `_translators()` 在**首次真正翻译时**才导入，**绝不允许**在模块顶层写 `import translators`。实测收益：源码启动工作集 74.7M → 26.9M，打包后 EXE 119.8M → 59.6M，启动也快了 2.4 秒。`test_app.py::test_translator_does_not_import_the_heavy_engine_at_module_level` 是这条的回归防护。
- **`translators` 导入前必须钉住地区**：`import translators` **在导入期就会发网络请求** —— 它的模块体里直接写了 `tss = TranslatorsServer()`（`server.py:6205`），构造函数调用 `get_region_of_server()`（`server.py:5896`），后者请求 `geolocation.onetrust.com`、失败再退到 `httpbin.org`（`server.py:364`）。两个后果都很糟：① 探测失败抛 `TranslatorError`，**整个 import 直接失败** —— 用户点「翻译」看到的是一个跟 httpbin.org 有关的报错（实测 25 次独立进程里挂 2 次，`verify_app.py` 也因此随机失败）；② 那两次 `requests.get` **没设 timeout**，网络不通时可能挂很久。`server.py:344` 留了逃生口：`translators_default_region` 有值就在第一行直接返回、不发请求。所以 `translator._translators()` 在 `import translators` **之前**先 `os.environ.setdefault("translators_default_region", "CN")`（`_DEFAULT_REGION`）—— **顺序错了就等于没修**。用 `setdefault` 是为了不覆盖用户自己设的值，非中国大陆用户可设 `EN` 覆盖。回归防护：`test_app.py::test_translator_pins_the_region_before_importing_translators`（检查顺序）、`test_translator_does_not_override_a_user_chosen_region`、`test_translator_loads_without_any_network`（把 `socket.socket` 换成连接必抛异常的类，**断网也必须能加载**）。
- **`verify_app.py` 的依赖检查不能直接 `import translators`**：理由同上，那样会依赖网络、随机失败。它走应用自己的 `translator._translators()`，既稳定，测的又是应用真正使用的那条路径。
- **延迟导入的内存收益有前提：本次运行没点过翻译**。Python 无法可靠卸载已导入的模块 —— 用户第一次点「中文/英文」后，那 48MB 会一直留到程序重启（实测 50MB → 100MB）。**不要试图用 `del sys.modules["translators"]` 去"回收"**：它不会把内存还给操作系统，强行重新导入还有崩溃风险。真要"用完就降回来"，只能把翻译做成用完即退的独立子进程，复杂度明显上升，目前不做。
- **内存基线**（空转、无翻译、未用过 RapidOCR，用于回归对比）：打包后 EXE **约 58MB 工作集 / 约 34MB 私有 / 12 个线程 / 空闲 CPU 0.000%**。逐阶段构成：空解释器 14.5M、tkinter +3.6M、Pillow +4.4M、pystray +1.7M、pynput +0.4M、pywin32 +1.4M、pytesseract +0.2M、**本项目全部模块 +0.3M**。也就是说内存几乎全由第三方库决定，**优化要往"少加载/晚加载第三方包"方向做，改自己的代码没有意义**。注意 `tesseract.exe` 是每次识别 spawn 的子进程、用完即退，它的内存从不计入本进程。历史值：只打 Tesseract 时 50.4MB / 9 线程 —— 现在这 +8MB / +3 线程就是 pytesseract 那句 `from numpy import ndarray` 的代价（见下）。
- **UI 主题与自绘控件**：`ui_theme.py` 是唯一的颜色/字体/间距来源，`ui_widgets.py` 放 Tk 原生做不到的件（圆角卡片、细滚动条、扁平按钮、分段选择器）。改界面前先读这两个文件的模块注释。
- **字体必须含中日韩字形**：`FONT_FAMILY` 是 `Microsoft YaHei UI`（同时含拉丁与中日韩字形）。**不要改回 `Segoe UI`** —— 它没有中文字形，Tk 只能逐字回退，中英文混排时字重/字距/基线全都不一致（实测症状：中文明显比英文粗）。注意 `Microsoft YaHei`（不带 ` UI`）这个名字在系统里**并不存在**，Tk 对不存在的字体名不报错、只静默回退，所以 `test_app.py::test_ui_font_family_is_actually_installed` 会拦住它。
- **字号用「点」（正数），间距用 `px()`（逻辑像素）**：本程序是 DPI 感知的，Tk 会把点按 `tk scaling` 换算成物理像素（实测本机 150% 缩放，`tk scaling = 2.0`）。而 `padx`/`pady`/`width`/`height` 的单位是**物理像素**，直接写 12 在 150% 屏上只有 8 个逻辑像素、观感偏挤 —— 所以间距一律过 `ui_theme.px()`。窗口尺寸同理按 DPI 缩放（见 `ocr_window._compute_window_size`）。
- **`RoundedCard` 的 Canvas 必须显式设 `width=1, height=1`**：Tk 的 Canvas **默认请求尺寸很大** —— 实测 **382x268**（100% DPI），并随显示器缩放线性放大（150% 下约 573x402）。这个请求尺寸会一路传播到外层 Frame，不压掉的话包着卡片的容器会虚报几百像素高，在窗口不够高时把空间吃光，排在它后面打包的兄弟控件被压成 0 高度、`winfo_ismapped()` 变 0 —— 实测踩过一次，整条状态栏消失。这条有两个回归防护：`test_app.py::test_rounded_card_does_not_inflate_its_parent_request`（根因层，断言 `reqsize <= 2`）与 `test_integration.py::test_ocr_window_layout_is_not_over_subscribed`（现象层）。
- **Tk 的 packer 在空间不够时按调用顺序分配**：固定尺寸的"外框"（操作栏、状态栏）要先打包，`expand=True` 的内容区放最后。这是惯用法，但**它本身不是上面那条 bug 的根因** —— 真正的根因是请求尺寸被虚报。两者都要做。
- **Tk 的 Text 没有 line-height**：行距只能靠 `spacing1/2/3` 模拟，而三者语义不同 —— `spacing1/3` 只作用于**逻辑行**的上下，`spacing2` 才作用于同一逻辑行的**折行之间**。只设 `spacing1/3` 的话，长行折行处会紧贴上一行、硬换行处却很松，同一段文字里出现两种行距。正确组合是 `spacing1=0, spacing2=spacing3=extra`（见 `ocr_window._line_spacing`）。
- **圆角只能自绘，而且不能用 `smooth=True`**：Tk 没有 `border-radius`。`RoundedCard` 画圆角矩形，内容控件叠在上面 —— 因此**内容的内缩量必须 >= 圆角半径**，否则直角的控件会盖住圆角（`RoundedCard` 内部已强制 `max(padding, radius)`）。窗口圆角靠 `-transparentcolor` 抠出来（见 `screenshot_overlay._show_toolbar` 与 `ocr_window._make_frameless`）。
  - **`round_rect` 绝不能退回 `create_polygon(..., smooth=True)`**。Tk 的 `smooth` 是 B 样条，曲线**不经过**给定点，圆角量由相邻点间距决定，而不是由传入的 `r` 决定。实测真实渲染后逐像素数（左上角挖掉的像素数）：请求半径 r=4/8/12/20 → **35/36/38/47**（几乎不随半径变化），而同一图形的右下角 → **0/1/3/12**（基本是直角）。也就是说它画的不是"半径 r 的圆角"，而且**上面圆、下面方**，看起来就是个坏掉的窗口。现在改成把四个圆角显式采样成圆弧点、`smooth=False`，实测挖掉量随半径正常增长（36/45/60/106）、四角一致。这个函数被 `RoundedCard`（OCR 窗口文本卡片、截图工具栏）和 `ThinScrollbar` 的滑块共用，所以影响面是整个 UI。回归防护：`test_app.py::test_round_rect_has_four_symmetric_corners`（**注意它的能力边界**：旧写法的点集本身是对称的，不对称是样条*渲染*出来的，几何断言看不到 —— 这条拦的是"又退回 smooth=True"这个动作，靠点数与"圆角深度随半径增长"两条）。
  - **`-transparentcolor` 抠圆角时，只有圆角处真的透明**：`ImageGrab` 抓的是合成后的屏幕，透明处会露出背后的东西。想验证圆角有没有生效，就在窗口背后放一块**已知的亮色**再抓图 —— 直接目测深色主题下的深色圆角是看不出来的（踩过：以为圆角没生效，其实只是背后也是深色）。
- **`overrideredirect(True)` 会让"映射前设置的位置"失效**：无边框窗口如果在 `__init__` 里先 `geometry("WxH")` 再 `geometry("+X+Y")`，映射后尺寸生效、**位置被丢弃**，窗口永远出现在屏幕左上角（实测构造完 `geometry()` 是 `'1x1+0+0'`，映射后是 `'624x323+0+0'`）。正确做法是 `withdraw()` → **一次性** `geometry(f"{w}x{h}+{x}+{y}")` → `deiconify()`。这个问题只在加了 `overrideredirect` 之后才出现，无边框之前的版本没有。
- **`pack_propagate(False)` 的容器不能用 `winfo_reqwidth()` 量需求宽度**：为了固定高度给操作栏设了 `pack_propagate(False)` 之后，它不再按子控件报告宽度，实测**恒为 1**。要量就得问里面那层会传播尺寸的 `Frame`（见 `ocr_window._bar_required_width`）。这个下限是真会生效的：给少了 packer 会把最后打包的控件挤小（实测分段控件 245 → 180，文字被裁）—— 又一次"空间被超额订阅"。
- **无边框窗口必须自己补拖动与关闭，并强制抢一次焦点**：去掉原生标题栏后窗口既不能拖也不能关，必须自绘（`ocr_window` 把整条操作栏当拖动区 + 最右一个 ✕）。另外无边框窗口默认**拿不到键盘焦点**，不 `focus_force()` 的话 Text 里的 Ctrl+C 与拖选全部失效，用户会以为程序卡了。关闭直接 `destroy()` 即可 —— `main._do_screenshot` 给 `win.root` 绑了 `<Destroy>` 来结束会话，锁和会话容器都会被正确回收。
- **`tk.Scrollbar` 一定带上下箭头**，`ttk.Scrollbar` 在 Windows 上受原生主题限制、做不出细圆角滑块 —— 所以滚动条用 `ui_widgets.ThinScrollbar` 自绘。`tk.Button` 即使 `relief="flat"` 在 Windows 上**仍会画立体边框**，必须同时 `bd=0` + `highlightthickness=0`（见 `ui_widgets.flat_button`）。
- **UI 改动必须两种主题都验证**：`%APPDATA%` 里的配置决定明暗，只测一种会漏掉写死的色值。`_ui_shot.py` 这类临时探针的写法：`config_manager.is_dark_mode = lambda: False` 强制浅色，再用 `ImageGrab` 抓窗口（**探针自己也要先 `SetProcessDPIAware()`，否则 Tk 的逻辑坐标与 ImageGrab 的物理像素对不上，会抓到别的窗口**；无边框浮窗还要 `-topmost`，否则会被别的窗口盖住）。
- **选区图必须从冻结的全屏截图里裁，不能重新抓屏**：`ScreenshotOverlay.__init__` 已经拍了一张干净的全屏图（`self.full_screenshot`），选区图就该从它裁（`self.full_screenshot.crop(...)`）。**绝不允许**在 `_on_button_release` 里再调一次 `ImageGrab.grab(bbox=...)` —— 那时覆盖层窗口还显示着，而选区边框（3px 白框 + 1px 虚线强调框）就画在选区边缘上，重新抓屏会把边框一起抓进识别输入。实测（真实渲染的中英文，紧贴文字裁剪）：不带边框 **90%** 准确率，带边框直接崩到 **4.3%**。用户贴着文字选是最自然的选法，所以触发率极高；而选区留白 6px 以上时边框落在空白处、实测无影响 —— 这个 bug 只在"选得紧"时发作，从偶发现象极难反推。用冻结图还有两个附带好处：不受"抓图期间屏幕变化"影响，且省掉一次全屏抓取。回归防护：`test_integration.py::test_overlay_crops_the_frozen_screenshot_instead_of_regrabbing`（判定方式是抓屏函数的调用次数）。
- **OCR 识别率排查记录（别再走弯路）**：两个真正的杀手，都已修复，**别再往别处找**：
  1. **选区边框被拍进识别输入**（见上一条）—— 贴着文字选时 90% → 4.3%。
  2. **预处理里的「对比度增强 + 锐化」**—— 用户真实截图上只有 **85.4%**，换成 **Otsu 二值化**后 **96.9%**。见下。
- **预处理：合成样本会骗你，必须用真实截图做基准**。这条是花了两次排查才学到的：
  - 第一轮我用 PIL 合成样本测，结论是"对比度 2.0 / 2x/3x 放大 / autocontrast / Otsu **全部无差别**（99%+），别在预处理上瞎调"。**这个结论是错的** —— 它只在干净样本上成立。合成样本没有亚像素渲染、没有背景干扰，任何管线都能认对。
  - 换成**用户的真实截图**（小字 + 中英数字混排 + 背后有花哨插画）后，差异立刻显出来：对比度增强+锐化 **85.4%**、不处理 92.7%、autocontrast 90.6%、**Otsu 96.9%**。
  - **"增强对比度"这个直觉是错的**：它把细笔画糊掉，反而让 Tesseract 自己的二值化更难做。而旧实现恰好是所有候选里最差的一个。
  - 放大倍数与重采样要**配合 Otsu 一起扫**（难图 / 好认-浅底）：`1x 81.2%/100%`、`2x 96.9%/100%`、`3x 96.9%/98.6%`、`4x 95.8%/98.6%`。3x 起会把"好认的图"从 100% 拉到 98.6%，2x 不会 —— 所以取 **2x BICUBIC**。
  - 无差别（别再测了）：`--oem 1` vs 3、`chi_sim+eng` vs `eng+chi_sim`、`preserve_interword_spaces`、加白边、PSM 3/4/6。局部自适应阈值（BoxBlur 背景 + 阈值）实测 **88%**，明显不如全局 Otsu。`eng` 单语言只有 62.5%（中文全丢），**不要**为了让拉丁字符更准而去掉 `chi_sim`。
  - 反色（invert）**更差**：Tesseract 5 自己能处理浅字深底，不要去 invert（暗底浅字实测 100%）。
  - **Tesseract 的天花板就在这里**：96.9% 仍是"有肉眼可见错误"的水平（实测 `0 FAIL` → `/0 FAILL`、`渲染` → `泻染`、`自检` → `目检`）。这是标准 `chi_sim` 模型在这类内容上的上限，**不是配置没调好** —— 继续调参不会再有明显收益。要再上一个台阶只能换引擎（PaddleOCR / RapidOCR 一类），代价是 EXE 体积明显变大。
  - 回归防护：`test_app.py::test_ocr_preprocess_binarizes_instead_of_boosting_contrast`（断言输出只含 0/255，防止有人把"对比度增强"加回来）与 `test_ocr_otsu_picks_a_threshold_between_the_two_peaks`。
- **pandas 体积陷阱**：`pytesseract` 会 `try: import pandas`（仅服务于 `Output.DATAFRAME`，本项目用不到）。一旦运行环境装了 pandas，就会连带载入 numpy + OpenBLAS，实测多占 **约 63MB 工作集 / 528MB 私有内存 / 23 个线程**。`build_exe.py` 里的 `--exclude-module=pandas` 是安全的（pytesseract 的导入有 try/except 保护），不要移除；开发环境同样建议使用不含 pandas 的 venv。
- **numpy 现在**是**必须装的**（onnxruntime 的硬依赖），于是上面那个坑以镜像形式又踩了一次：`pytesseract.py:35` 有一句 `from numpy import ndarray`（同样包在 `try/except ModuleNotFoundError` 里）。numpy 没装时它静默失败、零代价；numpy 一装，**每次启动都真的加载 numpy 并拉起 OpenBLAS 线程池**。实测空闲进程：
  - 修之前：工作集 **86.1MB**、私有 **516.6MB**、线程 **27**
  - 修之后：工作集 **58.4MB**、私有 **34.1MB**、线程 **12**
  - （改造前、只有 Tesseract 的基线：50.4MB / 9 线程 —— 所以打包 RapidOCR 的净代价只有 +8MB / +3 线程）
  
  修法是在 `ocr_engine.py` 里**于 `import pytesseract` 之前**把这些环境变量 `setdefault` 成 `"1"`：`OPENBLAS_NUM_THREADS` / `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `NUMEXPR_NUM_THREADS`。**顺序错了就等于没修**（环境变量只在模块首次加载时生效）。实测限制成单线程**不会拖慢识别**（推理是 onnxruntime 自己的线程池在做，numpy 只是数据容器）：RapidOCR 单张图 1.24s → 1.17s。
- **`is_available()` 绝不能用 `import` 来判断**：`RapidOcrBackend.is_available()` 用 `importlib.util.find_spec`。原因是**托盘菜单在构建菜单时就会问一次可用性**（要标注「未安装」），只要那里写了 `import`，"懒加载"就被彻底绕过 —— 实测：只是启动程序、什么都没做，工作集就从 50MB 涨到 86MB。回归防护：`test_app.py::test_rapidocr_availability_check_does_not_import_the_module`（用 monkeypatch 断言 `_module()` 没被调用）与 `test_ocr_engine_does_not_import_rapidocr_at_module_level`（开子进程验证，同进程内断言会失真）。