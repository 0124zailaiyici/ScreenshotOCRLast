"""钉住窗口的位置、边界、重叠避让、缩放与持久化行为。

使用会话级共享 Tk root（conftest.tk_root），并通过 isolated_config
把配置与钉住图片重定向到临时目录 —— 不再写入用户真实配置。
"""
import win32clipboard
import pytest
from PIL import Image
from types import SimpleNamespace

from pin_window import PinWindow


@pytest.fixture(autouse=True)
def _cleanup_pin_windows(isolated_config):
    """保证每个用例结束后不残留活跃窗口，避免用例间互相污染。

    这里**必须**依赖 isolated_config：pytest 的夹具 teardown 是逆序执行的，
    只有让本夹具在 isolated_config 之后 setup，它的清理才会在 monkeypatch
    还原之前跑完。否则 ``win._on_close()`` 会写回用户真实配置。
    """
    yield
    for win in list(PinWindow.active_windows):
        try:
            win._on_close()
        except Exception:
            pass
    PinWindow.active_windows.clear()


def test_pin_position_jitter_within_10px(tk_root, isolated_config):
    """钉住后位置偏移不超过 10px"""
    img = Image.new('RGB', (100, 100))
    coords = (100, 100, 200, 200)

    for _ in range(10):
        win = PinWindow(img, coords=coords, master=tk_root)
        win.root.update()
        assert abs(win.root.winfo_x() - coords[0]) <= 10
        assert abs(win.root.winfo_y() - coords[1]) <= 10
        win._on_close()


def test_pin_stays_within_screen(tk_root, isolated_config):
    """在屏幕边缘截图时，钉住窗口不得超出屏幕"""
    img = Image.new('RGB', (100, 100))
    screen_w = tk_root.winfo_screenwidth()
    screen_h = tk_root.winfo_screenheight()

    win = PinWindow(img, coords=(screen_w - 50, screen_h - 50, screen_w, screen_h),
                    master=tk_root)
    win.root.update()

    assert win.root.winfo_x() + 100 <= screen_w
    assert win.root.winfo_y() + 100 <= screen_h


def test_pin_windows_do_not_overlap(tk_root, isolated_config):
    """同一位置连续钉住两次，两个窗口不得重叠"""
    img = Image.new('RGB', (50, 50))
    coords = (200, 200, 250, 250)

    win1 = PinWindow(img, coords=coords, master=tk_root)
    win1.root.update()
    win2 = PinWindow(img, coords=coords, master=tk_root)
    win2.root.update()

    x1, y1 = win1.root.winfo_x(), win1.root.winfo_y()
    w1, h1 = win1.root.winfo_width(), win1.root.winfo_height()
    x2, y2 = win2.root.winfo_x(), win2.root.winfo_y()
    w2, h2 = win2.root.winfo_width(), win2.root.winfo_height()

    overlapping = (x1 < x2 + w2 and x1 + w1 > x2 and
                   y1 < y2 + h2 and y1 + h1 > y2)
    assert not overlapping


def test_pin_zoom_keeps_top_left(tk_root, isolated_config):
    """滚轮缩放后窗口左上角位置保持不变"""
    win = PinWindow(Image.new('RGB', (100, 100)), coords=(300, 300, 400, 400),
                    master=tk_root)
    win.root.update()
    before_x, before_y = win.root.winfo_x(), win.root.winfo_y()

    class MockEvent:
        delta = 120

    win._on_zoom(MockEvent())
    win.root.update()

    assert win.root.winfo_x() == before_x
    assert win.root.winfo_y() == before_y
    assert win.current_scale > 1.0          # 确实放大了


def test_pin_zoom_out_shrinks(tk_root, isolated_config):
    """反向滚轮应缩小"""
    win = PinWindow(Image.new('RGB', (100, 100)), coords=(300, 300, 400, 400),
                    master=tk_root)
    win.root.update()

    class MockEvent:
        delta = -120

    win._on_zoom(MockEvent())
    assert win.current_scale < 1.0


def test_pin_state_is_persisted_and_cleaned_up(tk_root, isolated_config):
    """钉住状态必须落盘，关闭后必须清理干净"""
    win = PinWindow(Image.new('RGB', (80, 80)), coords=(150, 150, 230, 230),
                    master=tk_root)
    win.root.update()
    pin_id = win.pin_id

    items = isolated_config.get_pinned_items()
    assert any(i.get("id") == pin_id for i in items), "钉住状态未写入配置"

    win._on_close()
    assert not any(i.get("id") == pin_id for i in isolated_config.get_pinned_items()), \
        "关闭后钉住状态未从配置中移除"


def test_pin_close_cancels_topmost_timer(tk_root, isolated_config):
    """关闭后不得残留置顶定时器（旧实现每 2 秒触发一次且永不取消）"""
    win = PinWindow(Image.new('RGB', (60, 60)), coords=(100, 100, 160, 160),
                    master=tk_root)
    win.root.update()

    assert win._topmost_job is not None
    win._on_close()
    assert win._topmost_job is None


def test_pin_window_survives_a_dirty_pinned_items_config(tk_root, isolated_config):
    """回归防护：配置里的 ``pinned_items`` 混进非 dict 元素时，「钉住」不得崩。

    这是**真实的生产路径**：``PinWindow._apply_initial_position`` 和 ``_save_state``
    都对列表元素直接调 ``item.get(...)``，且都没有 try/except 包住。列表里混进一个
    字符串就抛 ``AttributeError``，被 ``main._do_screenshot`` 的 except 吞掉 ——
    用户看到的现象是"点了钉住，什么都没发生，也没有任何提示"。

    这里刻意直接往配置里塞脏数据（模拟被外部改坏的文件），而不是走 ``set_pinned_items``
    —— 后者自己会清洗，测不出加载路径的问题。
    """
    isolated_config.config["pinned_items"] = [
        "junk", 123, None, ["nested"],
        {"id": "ok", "path": "x", "pos": [1, 2]},
    ]

    win = PinWindow(Image.new('RGB', (70, 70)), coords=(300, 300, 370, 370),
                    master=tk_root)
    win.root.update()

    # 走到这里没抛异常就说明 _apply_initial_position / _save_state 都挺住了
    assert win.root.winfo_exists()
    assert win.root.winfo_ismapped() or win.root.winfo_viewable() is not None

    # 落盘的内容里也不该再混有非 dict 元素
    assert all(isinstance(i, dict) for i in isolated_config.get_pinned_items())


# ---------------------------------------------------------------------------
# 右键菜单
#
# 旧行为是**右键直接关闭窗口**，于是钉住的图既没法复制、也没法重新识别 ——
# 想复制只能重新 Alt+X 截一次，而截的时候又只能三选一（钉住 or 复制），
# 不能都要。下面两条钉住新的契约。
# ---------------------------------------------------------------------------

def _menu_labels(win):
    return [r["label"] for r in win._menu._rows if r["kind"] == "item"]


def _dib_width_from_clipboard():
    """读剪贴板里 CF_DIB 的宽度。

    **直接读 BITMAPINFOHEADER 的 biWidth 字段**，不去还原 BMP 文件头再喂给
    PIL —— CF_DIB 就是"去掉 14 字节文件头"的 BMP，补文件头那一步（尤其是
    bfOffBits）很容易写错，而这里只关心宽度，读第 4~8 字节就够了。
    """
    win32clipboard.OpenClipboard()
    try:
        if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
            return None
        data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
    finally:
        win32clipboard.CloseClipboard()
    return int.from_bytes(data[4:8], "little", signed=True)


def test_pin_right_click_opens_a_menu_instead_of_closing(tk_root, isolated_config):
    """右键必须弹菜单，不能像旧实现那样直接关掉窗口。

    **必须真的发一个 ``<Button-3>`` 事件**，不能直接调 ``_on_context_menu`` ——
    后者只验证了处理函数本身，把 ``bind`` 改回 ``_on_close`` 照样通过
    （第一版就是这么写的，证伪时才发现是恒真断言）。
    """
    win = PinWindow(Image.new('RGB', (120, 60), 'white'),
                    coords=(50, 50, 170, 110), master=tk_root)
    win.root.update()
    win.root.event_generate("<Button-3>", x=10, y=10)
    tk_root.update()
    try:
        assert win.root.winfo_exists(), "右键把钉住窗口关掉了"
        assert win._menu is not None and win._menu.is_open, "右键没有弹出菜单"
        assert _menu_labels(win) == ["复制图片", "识别文字…", "取消钉住"]
    finally:
        if win._menu is not None:
            win._menu.close()
        tk_root.update()

    # 关闭仍然可用，只是挪进了菜单里
    assert win.root.winfo_exists()


def test_pin_escape_still_closes_the_window(tk_root, isolated_config):
    """Esc 关闭的行为不变（右键让出去了，Esc 还得能关）。

    **必须先 ``focus_force()``**：键盘事件只会送到有焦点的控件，而 ``tk_root``
    是会话级共享的，前面的用例销毁过窗口之后焦点会落空。实测真实运行时新建的
    钉住窗口是拿得到焦点的（探针验证过），这里只是为了不受用例执行顺序影响。
    """
    win = PinWindow(Image.new('RGB', (120, 60), 'white'),
                    coords=(50, 50, 170, 110), master=tk_root)
    win.root.update()
    win.root.focus_force()
    tk_root.update()
    win.root.event_generate("<Escape>")
    tk_root.update()
    assert win not in PinWindow.active_windows, "Esc 关不掉窗口了"


def test_pin_menu_close_item_actually_closes(tk_root, isolated_config):
    """菜单里的「取消钉住」要真的能关掉窗口（否则右键就再也关不掉了）。"""
    win = PinWindow(Image.new('RGB', (80, 40), 'white'),
                    coords=(50, 50, 130, 90), master=tk_root)
    win.root.update()

    win._on_context_menu(SimpleNamespace(x_root=400, y_root=300))
    tk_root.update()
    close_row = next(r for r in win._menu._rows
                     if r["kind"] == "item" and r["label"] == "取消钉住")
    win._menu._on_click(SimpleNamespace(y=close_row["y"] + close_row["h"] // 2))
    tk_root.update()

    assert win not in PinWindow.active_windows, "「取消钉住」没有把窗口关掉"


def test_pin_copy_uses_the_original_image_not_the_scaled_one(tk_root, isolated_config):
    """回归防护：复制出去的必须是**原始分辨率**。

    ``label`` 上显示的图是滚轮缩放过的，直接拿它去复制会掉画质 —— 而钉住窗口
    一直留着 ``original_image``。这个区别只有在缩放之后才暴露，所以这里刻意先
    缩到 50%。
    """
    original = Image.new('RGB', (200, 100), 'white')
    win = PinWindow(original, coords=(50, 50, 250, 150), master=tk_root)
    win.root.update()

    win.current_scale = 0.5
    win._update_display()
    tk_root.update()
    assert win.tk_image.width() == 100, "缩放没生效，这条测试就白测了"

    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.CloseClipboard()

    win._copy_image()

    width = _dib_width_from_clipboard()
    assert width is not None, "点「复制图片」之后剪贴板里没有图片"
    assert width == original.width, (
        f"复制出来的是缩放后的图（宽 {width}）而不是原图（宽 {original.width}）"
    )


def test_pin_copy_reports_success_through_the_notify_callback(tk_root, isolated_config):
    """复制要给出反馈 —— 静默失败时用户只会以为"点了没反应"。"""
    messages = []
    win = PinWindow(Image.new('RGB', (60, 30), 'white'),
                    coords=(50, 50, 110, 80), master=tk_root,
                    notify=lambda title, body: messages.append((title, body)))
    win.root.update()

    win._copy_image()

    assert messages, "复制成功却没有发出任何通知"
    assert messages[0][0] == "复制成功", f"通知内容不对: {messages}"


def test_pin_context_menu_is_reused_when_already_open(tk_root, isolated_config):
    """连点右键不能叠出多层菜单。"""
    win = PinWindow(Image.new('RGB', (60, 30), 'white'),
                    coords=(50, 50, 110, 80), master=tk_root)
    win.root.update()

    win._on_context_menu(SimpleNamespace(x_root=400, y_root=300))
    tk_root.update()
    first = win._menu
    win._on_context_menu(SimpleNamespace(x_root=400, y_root=300))
    tk_root.update()
    try:
        assert win._menu is first, "连点右键叠出了第二个菜单"
    finally:
        first.close()
        tk_root.update()


def test_pin_close_releases_an_open_menu(tk_root, isolated_config):
    """关掉钉住窗口时，正开着的菜单也要一起收掉（它还持有 grab）。"""
    win = PinWindow(Image.new('RGB', (60, 30), 'white'),
                    coords=(50, 50, 110, 80), master=tk_root)
    win.root.update()

    win._on_context_menu(SimpleNamespace(x_root=400, y_root=300))
    tk_root.update()
    menu = win._menu
    assert menu.is_open

    win._on_close()
    tk_root.update()

    assert not menu.is_open, "窗口关了但菜单还开着"
    assert win._menu is None
