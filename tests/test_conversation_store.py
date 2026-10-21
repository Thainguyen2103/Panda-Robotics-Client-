import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from server.llm import conversation_store as store


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(__file__).resolve().parent / f".conversation-history-{uuid4().hex}.sqlite3"
        self.path_patch = patch.object(store, "_db_path", self.db_path)
        self.path_patch.start()
        store.initialize()

    def tearDown(self):
        self.path_patch.stop()
        for path in (self.db_path, Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm")):
            path.unlink(missing_ok=True)

    def test_turns_persist_and_are_isolated_by_conversation(self):
        store.save_turn("one", "turn-1", "Con mèo tiếng Nhật là gì?", "猫 đọc là neko.", "vi")
        store.save_turn("two", "turn-1", "Con mèo là gì?", "Một loài vật.", "vi")
        self.assertEqual(len(store.recent_turns("one")), 2)
        self.assertEqual(store.search("one", "mèo tiếng Nhật"), [
            {"role": "user", "content": "Con mèo tiếng Nhật là gì?"},
            {"role": "assistant", "content": "猫 đọc là neko."},
        ])
        self.assertNotIn("猫 đọc là neko.", str(store.recent_turns("two")))

    def test_conversation_deletion_removes_history(self):
        store.save_turn("one", "turn-1", "hello", "hi", "en")
        store.delete_conversation("one")
        self.assertEqual(store.recent_turns("one"), [])


if __name__ == "__main__":
    unittest.main()
