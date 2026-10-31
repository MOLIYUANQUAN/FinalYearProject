"""电脑上的「说话键」：右 Ctrl。

单独按住一会儿（0.25 秒）= 叫 Friday 到前面来听；和别的键一起按（Ctrl+C、Ctrl+V……）是快捷键，不管。
这里只管判断；装键盘钩子、把窗口叫出来在 desktop.py。窗口到了前面，按住和松开会直接交给页面，页面照「按住麦克风」那样走。
"""

from __future__ import annotations

VK_RCONTROL = 0xA3
SUMMON_AFTER_S = 0.25


class TalkKey:
    def __init__(self) -> None:
        self.down_at: float | None = None
        self.mixed = False
        self.fired = False

    def key_down(self, vk: int, now: float) -> None:
        if vk == VK_RCONTROL:
            if self.down_at is None:  # 按住时的自动重复不算新的一次
                self.down_at, self.mixed, self.fired = now, False, False
        elif self.down_at is not None:
            self.mixed = True

    def key_up(self, vk: int, now: float) -> None:
        if vk == VK_RCONTROL:
            self.down_at = None

    def due(self, now: float) -> bool:
        """该把 Friday 叫出来了吗？每按住一次最多一次。"""
        if self.down_at is None or self.mixed or self.fired or now - self.down_at < SUMMON_AFTER_S:
            return False
        self.fired = True
        return True
