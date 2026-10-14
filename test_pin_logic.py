"""钉住窗口的位置、边界、重叠避让、缩放与持久化行为。

使用会话级共享 Tk root（conftest.tk_root），并通过 isolated_config
把配置与钉住图片重定向到临时目录 —— 不再写入用户真实配置。
"""
import pytest
from PIL import Image

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
