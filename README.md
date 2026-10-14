# ScreenshotOCR

Windows 截图工具，支持截图后三选一操作：钉住到屏幕、OCR 识别文字、复制图片。常驻系统托盘，`Alt+X` 全局热键触发。

## 1. 项目背景

本项目旨在提供一个轻量级、无外部框架依赖的截图工具，支持以下核心流程：

- **全局触发**：通过 `Alt+X` 快速进入截图模式。
- **选区操作**：支持鼠标拖拽选择区域，并提供 \[钉住 | 识字 | 复制] 三合一工具栏。
- **高级 OCR 与翻译**：
  - **OCR**：集成 Tesseract 引擎进行离线识别。
  - **翻译**：支持多引擎翻译（默认阿里云），具备**语言自动检测**、**目标语言切换**及**本地历史记录**功能。
- **用户主控复制**：废弃自动复制。
- **系统集成**：常驻系统托盘，支持配置持久化。

## 2. 界面

界面为**纯 Tkinter 自绘**，不依赖任何 GUI 框架（也没有 Electron/Qt 的体积）。

- **主题**：深色 / 浅色自动跟随系统，强调色取自系统 AccentColor（按钮、选中态、光标都用它派生）。
- **识字窗口**：顶部操作栏（复制 / 重新识别 / 原文·中文·EN）+ 圆角文本卡片 + 底部状态栏（字数、识别耗时、当前视图）。
- **截图工具栏**：圆角浮窗，三个操作之间有分隔线，鼠标悬停有反馈。
- **字体**：`Microsoft YaHei UI` —— 同时含拉丁与中日韩字形。用 `Segoe UI` 的话中文只能靠逐字回退，中英文混排会字重不一致。
- **DPI 感知**：字号用「点」自动缩放，间距按显示器缩放系数换算，150% 缩放下观感与 100% 一致。

### 资源占用（实测）

打包后的 EXE 空转（未使用翻译）时：

| 指标 | 数值 |
|------|------|
| 工作集 | 约 50 ~ 60 MB |
| 私有内存 | 约 50 MB |
| 线程数 | 10 |
| **空闲 CPU** | **0.000%** |

OCR 引擎 `tesseract.exe` 是每次识别时 spawn 的子进程、用完即退，其内存不计入本进程。
翻译所用的 `translators` 库重达 48MB，已改为**首次点击翻译时**才加载，因此常驻期间不占用。

## 2. 功能详细说明

### 2.1 OCR 识别与翻译

- **识别流程**：截图 -> 点击“识字” -> 弹出 OCR 窗口。
- **翻译增强**：
  - 支持 `zh`, `en`目标语言。
  - 自动检测源语言。
  - 翻译失败自动重试或弹出错误提示。
  - 翻译历史记录保存在 `translation_history.json`。

### 2.2 复制管理

- **手动触发**：OCR 识别后，用户需点击按钮才执行复制。
- **选择复制**：支持用鼠标选中特定行/词进行复制。


## 3. 安装与运行

### 环境要求

- Windows 10/11
- Python 3.10+
- **Tesseract-OCR 5.x**：
  - 请从 [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) 下载 Windows 安装包。
  - 安装时请勾选 **"Additional language data (download)"** 中的 **"Chinese"** 相关选项以支持中文识别。
  - 程序会自动尝试在 `C:\Program Files\Tesseract-OCR` 搜索，若安装在其他目录，请在程序提示时手动指定 `tesseract.exe` 路径。

### 快速开始
1. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```
2. **运行程序**：
   ```bash
   python main.py
   ```

### 打包为 EXE
如果你想在桌面直接点击运行，可以执行以下命令：
```bash
python build_exe.py
```
打包完成后，你可以在 `dist/` 目录下找到 `ScreenshotOCR.exe`。将它复制到桌面即可。
3. **运行测试**：
   ```bash
   pytest test_app.py test_integration.py test_pin_logic.py
   ```
   另可运行环境自检（失败返回非零退出码）：
   ```bash
   python verify_app.py
   ```

## 4. API 与模块说明

- **`translator.py`**: 提供 `translate_async(text, callback, error_callback, to_lang)` 接口。
- **`ocr_engine.py`**: 提供 `recognize(image)` 接口，返回识别文本。
- **`config.py`**: 管理 JSON 配置，支持 `set(key, value)` 和 `get(key)`。

## 5. 贡献指南 (Contribution)

欢迎通过以下方式参与贡献：
1. **提交 Issue**：报告 Bug 或提出新功能建议。
2. **提交 Pull Request**：
   - 请先 Fork 本仓库。
   - 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)。
   - 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)。
   - 推送到分支 (`git push origin feature/AmazingFeature`)。
   - 开启一个 Pull Request。

## 6. 许可证信息 (License)

本项目采用 [MIT License](LICENSE) 开源许可证。

## 7. 更新日志 (Changelog)

### [v1.3.1] - 2026-10-13

**对抗式复核后的修复：3 条 MAJOR + 7 条 MINOR**

复核发现的问题不是"代码写错"，而是**声明的保证与实际不符** —— 三处都是"说好了要防，其实没防住"。

- **\[Fix]** 脏配置能让「钉住」静默失败：`_sanitize` 对 `pinned_items` 只校验了容器类型（是 list 就放行），**不校验元素**。列表里混进一个字符串就抛 `AttributeError`，被 `main._do_screenshot` 的 except 吞掉 —— 用户看到的是"点了钉住，什么都没发生，也没有任何提示"。现在在**加载 / 写入 / 读取**三个边界都做逐元素清洗；`pos` 形状不对时只丢这个字段，不丢整条钉住记录
- **\[Fix]** 测试隔离名不副实：`translator` 在导入期就绑定了 `config_manager` 并构造了单例，`Translator.__init__` 当场把 `config_dir` 算成了 `history_file`。测试模块在收集期就导入它，那时隔离夹具还没运行 —— 于是从"隔离"上下文写翻译历史会**真的落进用户真实配置目录**。现在连单例上已算好的 `history_file` 一起重定向
- **\[Fix]** 图标缓存识别不出"已销毁的解释器"：`Misc._root()` 只是属性遍历，销毁后的 root 仍等于它自己，缓存不失效 → 返回死句柄 → 等到配到活控件时才炸成 `image "pyimageN" doesn't exist`，报错位置离原因很远。现在当场抛 `RuntimeError` 并清缓存
- **\[Fix]** IPC 启动竞态：IPC 线程早于 `_pin_queue` 创建，竞态下 `AttributeError` 被一个包着整个 `while` 循环的 `except` 吞掉 → IPC 服务线程**永久退出**。调整初始化顺序
- **\[Fix]** 滚动条拖动被中断：滚动条只有 9px 宽，垂直拖动时指针稍一横向漂移就触发 `<Leave>`，旧实现在那里清掉拖动状态。现在拖动期间 grab 指针，只由松开按键结束
- **\[Fix]** 收紧过松的断言：`RoundedCard` 请求尺寸的断言写成 `< 100`，而真实值是 **1** —— 上界松了 100 倍，虚报 99px 也能过。改为 `<= 2`
- **\[Docs]** 修正 3 处不准确的文档：Canvas 默认请求尺寸是 **DPI 相关**的（100% 下 382x268，150% 下约 573x402），原文写死成 570x400；`SetProcessDpiAwareness` 实际在所有 import **之后**、窗口创建之前调用，不是"import 之前"；"并存 3 个以上 Tk 解释器会抛 init.tcl"这条**未能稳定复现**（连开 6 个正常），措辞已降级
- **\[Chore]** 删除 `screenshot_overlay.py` 里无效的重复 `SetProcessDpiAwareness` 调用（Tk 已在运行时再调只会拿到 `E_ACCESSDENIED`）
- **\[Test]** 测试 46 → **55 个**。新增的 9 条回归防护**每一条都实际验证过会失败** —— 逐个撤掉对应修复确认断言变红，避免写出恒真断言

### [v1.3.0] - 2026-10-13

**界面重做：从 Tkinter 默认外观改为扁平现代风**

- **\[UI]** 新增 `ui_widgets.py`：Tk 原生做不到的件全部自绘 —— 圆角卡片、无箭头细滚动条、扁平按钮、分段选择器
- **\[UI]** 识字窗口重排：顶部操作栏 + 圆角文本卡片 + 底部状态栏（字数 / 识别耗时 / 当前视图）
- **\[UI]** 截图工具栏改为圆角浮窗（`-transparentcolor` 抠角），操作之间加分隔线，补齐悬停反馈
- **\[UI]** 新增「重新识别」按钮：识别错了可以直接重试，不用重新截图
- **\[UI]** 翻译目标改为「原文 / 中文 / EN」三段选择器，并修正初始态 —— 之前未翻译时「中文」是选中状态，会让人误以为看到的是译文
- **\[UI]** 去掉所有控件的立体边框（`tk.Button` 即使 `relief="flat"` 在 Windows 上仍会画边框，必须 `bd=0` + `highlightthickness=0`）
- **\[Fix]** 字体改用 `Microsoft YaHei UI`：原来的 `Segoe UI` 没有中文字形，Tk 只能逐字回退，中英文混排时字重与字距不一致
- **\[Fix]** 间距改为按 DPI 换算。原来只缩放字号不缩放间距，在 150% 缩放的屏幕上界面明显偏挤
- **\[Fix]** 修正正文行距：`spacing1/3` 只作用于逻辑行，折行要用 `spacing2`。原来长行折行处紧贴上一行、硬换行处却很松，同一段文字里有两种行距
- **\[Fix]** 修复矮窗口下整条状态栏消失：`RoundedCard` 里的 Canvas 用了 Tk 的默认请求尺寸（约 570×400），一路传播上来把内容区撑到 288px，空间不够时排在最后打包的状态栏被压成 0 高度
- **\[Fix]** 修复工具栏定位写死宽度（`toolbar_w = 220`，实际 299）导致贴屏幕右边时跑到屏幕外
- **\[UI]** 图标改为圆头笔画，重绘图钉与刷新图标
- **\[Test]** 测试 31 → **46 个**，新增 7 条 UI 回归防护（字体真实存在、DPI 换算、明暗主题字段对齐、卡片不虚报请求尺寸、矮窗口布局不被挤爆、滚动条自绘、行距一致）

### [v1.2.3] - 2026-10-13

- **\[Fix]** 消除 OCR 时一闪而过的控制台窗口：pytesseract 的 `get_tesseract_version()` / `get_languages()` 用的是裸 `subprocess` 调用，而本程序是无控制台的 GUI 进程，Windows 会为子进程新建一个**可见**的控制台窗口。`ocr_engine` 现在把 `pytesseract.pytesseract.subprocess` 整体替换为注入 `CREATE_NO_WINDOW` 的版本（实测只有 `CREATE_NO_WINDOW` 可靠，`SW_HIDE` 不足）
- **\[Perf]** `is_available()` 按 tesseract 可执行文件路径缓存，不再每次识别都多 spawn 一次 tesseract 去查版本号（每次约省 500ms）
- **\[Perf]** `translators` 改为首次真正翻译时才导入：它一个包占 **48MB**（全程序内存的 80%）并拖慢启动 **2.4 秒**。打包后常驻内存 **119.8MB → 59.6MB**，启动快 2.4 秒
- **\[Fix]** 截图会话锁的遗留回收改为判断消费队列的 Tk 线程是否存活（v1.2.2 引入的 30s 超时会在锁仍被合法持有时强行释放，导致两个截图会话并发执行、后续 `release` 抛 `release unlocked lock`）
- **\[Test]** 测试增至 **31 个**，并新增两条回归防护（子进程必须无控制台窗口、translator 不得在导入期加载 translators）；测试套件由 3.26s 降至 1.20s

### [v1.2.2] - 2026-10-13

- **\[Fix]** 修复 Tk root 变化后图标缓存失效导致的 `TclError: image "pyimageN" doesn't exist`（缓存现在随 root 自动失效）
- **\[Fix]** 修复 OCR 识别失败被伪装成识别结果的问题，改为抛出 `OcrError` 并展示修复引导
- **\[Fix]** 修复钉住窗口的置顶定时器在关闭后不取消（每 2 秒空转的泄漏）
- **\[Fix]** 修复截图会话锁异常时不释放导致热键永久失效（新增 30s 超时强制回收）
- **\[Fix]** 修复翻译历史写在当前工作目录的问题，迁移到 `%APPDATA%/ScreenshotOCR/`，旧数据自动迁移
- **\[Fix]** 修复配置项被写坏类型时运行期崩溃，加载时按 schema 校验并回落默认值
- **\[Test]** 测试由 7 failed / 5 passed 修复为 23 passed；新增 hermetic 夹具，不再读写用户真实配置
- **\[Build]** `verify_app.py` 由硬编码假验证改为 13 项真实检查，失败返回非零退出码

### [v1.2.1] - 2026-05-09

- **\[Build]** 优化打包流程：使用独立 venv 构建，排除 Anaconda 环境的冗余库（sphinx/pytest/pandas 等），EXE 从 125MB 缩减至 30MB

### [v1.2.0] - 2026-05-09

- **\[UI]** 全新主题系统：支持深色/浅色模式自动切换，跟随系统主题色
- **\[UI]** PIL 程序化生成图标（图钉/放大镜/剪贴板/勾选），替换 emoji
- **\[UI]** 工具栏鲜艳配色：图钉/复制用主题色，识字用绿色，文字自适应黑白
- **\[UI]** 简化覆盖层：截图画面真实显示，无灰色/暗色遮罩
- **\[UI]** 系统托盘图标优化为相机形状，深色/浅色模式自适应
- **\[Fix]** 修复快速重复截图导致程序卡死的问题（Esc 取消链不完整）
- **\[Fix]** 修复第二次截图工具栏图标不显示（PhotoImage 缓存生命周期管理）
- **\[Fix]** 修复多次热键触发导致截图锁无法释放的问题

### [v1.1.0] - 2026-05-08

- **\[Feature]** 实现完整的翻译功能模块，增加语言检测和多语言切换。
- **\[Feature]** 增加翻译历史记录功能（本地 JSON 持久化）。
- **\[Fix]** 修复 Tesseract 未安装时的崩溃问题，增加路径指引对话框。
- **\[Fix]** 修复多线程环境下 Tkinter 窗口销毁导致的 `TclError`。

***

