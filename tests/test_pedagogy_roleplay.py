# -*- coding: utf-8 -*-
"""
Unit tests for Pedagogical Error Correction and Interactive Role-play Module.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

from server.llm import engine as llm
from server.llm.pedagogy import (
    fast_pedagogical_correction,
    detect_pedagogical_context,
    is_role_play_request,
    is_role_play_exit,
    match_role_play_scenario,
    format_role_play_system_instruction,
    format_pedagogical_error_instruction,
)
from server.llm.dictionary_router import get_role_play, get_entertainment, _ENTERTAIN_LIST


class PedagogicalErrorCorrectionTests(unittest.TestCase):
    """Kiểm tra cơ chế phản hồi lỗi sai tự động (Pedagogical Error Correction)."""

    def test_english_subject_verb_agreement_correction(self):
        # Trẻ nói "I goes to school"
        res = fast_pedagogical_correction("Con nói I goes to school có đúng không Moon?")
        self.assertIsNotNone(res)
        # 1. Khích lệ
        self.assertTrue(any(word in res for word in ("Bé giỏi", "tự tin", "khen")))
        # 2. Câu chuẩn xác
        self.assertIn("I go to school", res)
        # 3. Giải thích ngắn bằng tiếng Việt
        self.assertTrue(any(word in res for word in ("chủ ngữ", "động từ", "nguyên mẫu", "-es")))

    def test_english_negative_doesn_t_correction(self):
        # Trẻ nói "He don't like apple"
        res = fast_pedagogical_correction("He don't like apple")
        self.assertIsNotNone(res)
        self.assertIn("He doesn't", res)
        self.assertTrue("doesn't" in res)

    def test_english_has_have_correction(self):
        # Trẻ nói "She have a cute cat"
        res = fast_pedagogical_correction("She have a cute cat")
        self.assertIsNotNone(res)
        self.assertIn("She has", res)

    def test_japanese_verb_desu_correction(self):
        # Trẻ nói "taberu desu"
        res = fast_pedagogical_correction("Nói taberu desu đúng ngữ pháp không?")
        self.assertIsNotNone(res)
        self.assertTrue("Tabemasu" in res or "食べます" in res)
        self.assertTrue("taberu" in res)

    def test_pedagogical_context_detection(self):
        # Nhận diện khi bé đang nhờ sửa lỗi hoặc luyện nói
        is_ped, lang = detect_pedagogical_context("Sửa giúp con câu này với")
        self.assertTrue(is_ped)
        self.assertEqual(lang, "en")

        is_ped_ja, lang_ja = detect_pedagogical_context("Câu này nói thế đúng chưa: 食べるです")
        self.assertTrue(is_ped_ja)
        self.assertEqual(lang_ja, "ja")

    def test_chat_fast_pedagogy_response(self):
        # Kiểm tra qua hàm chat() chính
        ans = llm.chat("I goes to school")
        self.assertIn("I go to school", ans)
        # Đảm bảo có giải thích tiếng Việt
        self.assertTrue(any(w in ans for w in ("chủ ngữ", "động từ", "bé")))


class InteractiveRolePlayTests(unittest.TestCase):
    """Kiểm tra module tương tác Nhập vai (Role-play & Interactive Practice)."""

    def setUp(self):
        llm.clear_history()

    def tearDown(self):
        llm.clear_history()

    def test_entertainment_kids_contains_roleplay_scenarios(self):
        roleplays = [i for i in _ENTERTAIN_LIST if i.get("type") == "role_play"]
        self.assertGreaterEqual(len(roleplays), 6)
        ids = {r["id"] for r in roleplays}
        self.assertIn("roleplay_bakery_en", ids)
        self.assertIn("roleplay_store_ja", ids)
        self.assertIn("roleplay_friends_en", ids)
        self.assertIn("roleplay_directions_en", ids)

    def test_detect_role_play_trigger_and_exit(self):
        self.assertTrue(is_role_play_request("Moon ơi, chơi đóng vai với bé đi!"))
        self.assertTrue(is_role_play_request("Chơi tiệm bánh nhé"))
        self.assertTrue(is_role_play_request("Bé muốn chơi bán đồ hàng"))
        self.assertFalse(is_role_play_request("Con mèo tiếng Nhật là gì?"))

        self.assertTrue(is_role_play_exit("Dừng chơi nha Moon"))
        self.assertTrue(is_role_play_exit("Nghỉ chơi thôi"))
        self.assertTrue(is_role_play_exit("Không chơi nữa"))
        self.assertFalse(is_role_play_exit("I want a cupcake"))

    def test_match_role_play_scenario_by_keyword(self):
        scenarios = [i for i in _ENTERTAIN_LIST if i.get("type") == "role_play"]
        # Mua bánh
        sc_bakery = match_role_play_scenario("chơi tiệm bánh ngọt", scenarios)
        self.assertEqual(sc_bakery["id"], "roleplay_bakery_en")

        # Cửa hàng tiện lợi tiếng Nhật
        sc_konbini = match_role_play_scenario("chơi cửa hàng tiện lợi Nhật Bản", scenarios)
        self.assertEqual(sc_konbini["id"], "roleplay_store_ja")

        # Làm quen bạn mới
        sc_friends = match_role_play_scenario("chơi làm quen kết bạn", scenarios)
        self.assertEqual(sc_friends["id"], "roleplay_friends_en")

    def test_chat_starts_role_play_and_exits(self):
        # Bắt đầu kịch bản tiệm bánh
        ans_start = llm.chat("Moon ơi chơi tiệm bánh với bé đi!")
        self.assertIn("tiệm bánh", ans_start.lower())
        self.assertIn("Welcome to Moon's Bakery", ans_start)
        self.assertIsNotNone(llm.get_active_role_play())
        self.assertEqual(llm.get_active_role_play()["id"], "roleplay_bakery_en")

        # Đang trong vai, tin nhắn của system được inject
        messages = llm._get_messages("I want a cookie, please!")
        contents = [m["content"] for m in messages if m["role"] == "system"]
        self.assertTrue(any("ROLE-PLAY" in c for c in contents))

        # Bé yêu cầu dừng chơi
        ans_exit = llm.chat("Dừng chơi nha Moon")
        self.assertIn("Cảm ơn bé đã cùng chơi", ans_exit)
        self.assertIsNone(llm.get_active_role_play())


if __name__ == "__main__":
    unittest.main()
