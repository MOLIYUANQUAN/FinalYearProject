"""日历标题说成人话：第一次在后台起短名、记下来，以后开场直接用；起不好就照原样。"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from src import agenda, names, presence
from src.calendar_providers.mock import _load_raw_events


class NameTests(unittest.TestCase):
    def setUp(self) -> None:
        names.NAMES_PATH.unlink(missing_ok=True)
        names._cache = None
        self.addCleanup(names.NAMES_PATH.unlink, missing_ok=True)
        self.addCleanup(setattr, names, "_cache", None)

    def test_unknown_titles_show_as_they_are_and_get_named_in_the_background(self) -> None:
        queued = []
        with patch.object(names, "_queue", side_effect=queued.append):
            self.assertEqual(names.short("FYP meeting with mentor"), "FYP meeting with mentor")
        self.assertEqual(queued, ["FYP meeting with mentor"])

    def test_named_titles_are_used_everywhere(self) -> None:
        names.remember({"FYP meeting with mentor": "见导师", "Comp30291 lecture": "COMP30291 讲座"})
        names._cache = None  # 从磁盘读回来
        event = {"id": "e", "title": "FYP meeting with mentor", "location": "Kilburn Building"}
        self.assertEqual(agenda.spoken(event), "见导师")
        self.assertEqual(agenda.shown(event), "见导师")
        # 「要不要紧」仍然看原标题：起了短名也不会漏掉 meeting / mentor
        _, say, focus = presence.today_view(datetime(2026, 10, 13, 12, 0), _load_raw_events(), [])
        self.assertEqual(say.replace(" ", " "), "下午 2 点见导师。Kilburn Building · 还有 2 小时。")
        self.assertEqual(focus["actions"][0]["id"], "prepare")

    def test_bad_names_are_ignored(self) -> None:
        names.remember({"Gym": "", "Lab": "一个非常非常非常非常非常长的名字超过了上限"})
        self.assertEqual(names.short("Gym"), "Gym")
        self.assertEqual(names.short("Lab"), "Lab")

    def test_course_codes_keep_their_own_names(self) -> None:
        names.remember({"COMP34111/LECTURE1A/": "不该用这个"})
        event = {"title": "COMP34111/LECTURE1A/"}
        self.assertNotEqual(agenda.spoken(event), "不该用这个")


if __name__ == "__main__":
    unittest.main()
