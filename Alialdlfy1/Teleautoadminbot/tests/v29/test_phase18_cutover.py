import os, tempfile, unittest
from unittest.mock import MagicMock

class FakeDB:
    def get_blocked_words(self): return []
    def get_channel_blocked_words(self, channel_id): return []
    def is_published(self, fp): return False
    def get_article(self, fp): return None
    def get_all_articles(self): return []

from core.runtime.integration import RuntimeIntegration
from core.runtime.legacy_bridge import LegacyRuntimeBridge


class TestPhase18Cutover(unittest.TestCase):
    def test_legacy_bridge_routes_before_ai(self):
        with tempfile.TemporaryDirectory() as td:
            rt = RuntimeIntegration(db=FakeDB(), db_path=os.path.join(td, "rt.sqlite"))
            rt._sections["blogger"].blocked_words = ["BLOCKME"]
            bridge = LegacyRuntimeBridge(rt, "blogger")
            rejected = bridge.ingest("hello BLOCKME", "a1", source="telegram", channel_id="1")
            self.assertEqual(rejected.status, "rejected")
            self.assertEqual(rt.queue.store.get_stats().get("queued", 0), 0)

    def test_bridge_preserves_section_target(self):
        with tempfile.TemporaryDirectory() as td:
            rt = RuntimeIntegration(db=FakeDB(), db_path=os.path.join(td, "rt.sqlite"))
            bridge = LegacyRuntimeBridge(rt, "blogger")
            result = bridge.ingest("hello world", "a1", source="telegram", channel_id="1")
            self.assertEqual(result.status, "queued")
            self.assertEqual(result.data["target"], "blogger")


if __name__ == "__main__":
    unittest.main()
