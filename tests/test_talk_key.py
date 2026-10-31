"""电脑上的说话键（右 Ctrl）：单独按住一会儿才叫 Friday；和别的键一起按是快捷键，不叫；每按一次最多叫一次。"""

from __future__ import annotations

import unittest

from src.talk_key import SUMMON_AFTER_S, VK_RCONTROL, TalkKey

VK_LCONTROL, VK_C = 0xA2, 0x43


class TalkKeyTests(unittest.TestCase):
    def test_held_alone_for_a_moment_calls_her_once(self) -> None:
        key = TalkKey()
        key.key_down(VK_RCONTROL, 10.0)
        self.assertFalse(key.due(10.0 + SUMMON_AFTER_S / 2))
        key.key_down(VK_RCONTROL, 10.1)  # 按住时的自动重复
        self.assertTrue(key.due(10.0 + SUMMON_AFTER_S))
        self.assertFalse(key.due(11.0))  # 还按着：不会再叫一次

    def test_ctrl_c_with_the_right_ctrl_is_a_shortcut(self) -> None:
        key = TalkKey()
        key.key_down(VK_RCONTROL, 10.0)
        key.key_down(VK_C, 10.1)
        self.assertFalse(key.due(11.0))

    def test_a_quick_tap_does_not_call_her(self) -> None:
        key = TalkKey()
        key.key_down(VK_RCONTROL, 10.0)
        key.key_up(VK_RCONTROL, 10.1)
        self.assertFalse(key.due(11.0))

    def test_left_ctrl_is_left_alone(self) -> None:
        key = TalkKey()
        key.key_down(VK_LCONTROL, 10.0)
        self.assertFalse(key.due(11.0))

    def test_each_press_can_call_her_again(self) -> None:
        key = TalkKey()
        key.key_down(VK_RCONTROL, 10.0)
        self.assertTrue(key.due(10.5))
        key.key_up(VK_RCONTROL, 11.0)
        key.key_down(VK_RCONTROL, 12.0)
        key.key_down(VK_C, 12.05)  # 上一次的「夹着别的键」不会带到下一次
        key.key_up(VK_RCONTROL, 12.1)
        key.key_down(VK_RCONTROL, 13.0)
        self.assertTrue(key.due(13.5))


if __name__ == "__main__":
    unittest.main()
