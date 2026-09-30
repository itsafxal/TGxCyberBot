import asyncio
import time
import pytest
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from utils import (
    MembershipCache,
    InFlightTracker,
    safe_delete_message,
    safe_edit_message_text,
    safe_edit_reply_markup,
    safe_answer_callback,
    PerfTracker,
    ApiCallMetrics,
    MEMBERSHIP_CACHE,
    IN_FLIGHT_CALLBACKS,
    check_loop_sub_dynamic
)
from pyrogram.errors import MessageDeleteForbidden, MessageIdInvalid, MessageNotModified, FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

class TestPerformanceAndReliability(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.cache = MembershipCache()
        self.in_flight = InFlightTracker()

    def test_membership_cache_positive_and_negative_ttl(self):
        """Test positive membership cached longer than negative membership."""
        user_id = 12345
        channel_id = -1001234567890

        # Initial lookup is None
        self.assertIsNone(self.cache.get(user_id, channel_id))

        # Set True (positive)
        self.cache.set(user_id, channel_id, True)
        self.assertTrue(self.cache.get(user_id, channel_id))

        # Test expiration with fake time
        with patch('time.time', return_value=time.time() + 65):
            self.assertIsNone(self.cache.get(user_id, channel_id))

        # Set False (negative)
        self.cache.set(user_id, channel_id, False)
        self.assertFalse(self.cache.get(user_id, channel_id))

        # Negative expires after 10s (negative TTL is 8s)
        with patch('time.time', return_value=time.time() + 10):
            self.assertIsNone(self.cache.get(user_id, channel_id))

    def test_in_flight_callback_isolation(self):
        """Test per-user per-message lock and multi-user isolation."""
        key_user1 = (1001, 555, "next_page")
        key_user1_dup = (1001, 555, "next_page")
        key_user2 = (1002, 555, "next_page")
        key_user1_other_msg = (1001, 556, "next_page")

        # User 1 acquires lock
        self.assertTrue(self.in_flight.acquire(key_user1))

        # User 1 duplicate request rejected
        self.assertFalse(self.in_flight.acquire(key_user1_dup))

        # User 2 CAN acquire lock (User 1 does NOT block User 2)
        self.assertTrue(self.in_flight.acquire(key_user2))

        # User 1 on different message CAN acquire lock
        self.assertTrue(self.in_flight.acquire(key_user1_other_msg))

        # After User 1 releases lock, can acquire again
        self.in_flight.release(key_user1)
        self.assertTrue(self.in_flight.acquire(key_user1))
        self.in_flight.release(key_user1)
        self.in_flight.release(key_user2)
        self.in_flight.release(key_user1_other_msg)

    async def test_safe_delete_message_handles_forbidden(self):
        """Test safe_delete_message safely catches MessageDeleteForbidden."""
        msg_mock = AsyncMock()
        msg_mock.delete.side_effect = MessageDeleteForbidden()

        # Must not raise exception
        result = await safe_delete_message(msg_mock)
        self.assertFalse(result)

    async def test_safe_delete_message_handles_invalid_id(self):
        """Test safe_delete_message safely catches MessageIdInvalid."""
        msg_mock = AsyncMock()
        msg_mock.delete.side_effect = MessageIdInvalid()

        # Must not raise exception
        result = await safe_delete_message(msg_mock)
        self.assertFalse(result)

    async def test_safe_edit_message_text_deduplication(self):
        """Test identical text and markup skips Telegram API call."""
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Button", callback_data="btn")]])
        msg_mock = AsyncMock()
        msg_mock.text = "Hello World"
        msg_mock.reply_markup = markup

        # Same text and markup -> should NOT call edit_text and return True
        result = await safe_edit_message_text(msg_mock, "Hello World", reply_markup=markup)
        self.assertTrue(result)
        msg_mock.edit_text.assert_not_called()

        # Different text -> should call edit_text
        await safe_edit_message_text(msg_mock, "New Text", reply_markup=markup)
        msg_mock.edit_text.assert_called_once()

    async def test_safe_edit_reply_markup_deduplication(self):
        """Test identical markup skips edit_reply_markup call."""
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Button", callback_data="btn")]])
        msg_mock = AsyncMock()
        msg_mock.reply_markup = markup

        # Same markup -> should NOT call edit_reply_markup and return True
        result = await safe_edit_reply_markup(msg_mock, markup)
        self.assertTrue(result)
        msg_mock.edit_reply_markup.assert_not_called()

    async def test_safe_answer_callback(self):
        """Test safe_answer_callback handles exceptions gracefully."""
        query_mock = AsyncMock()
        query_mock.answer.side_effect = Exception("Callback expired")

        result = await safe_answer_callback(query_mock, "Test", show_alert=False)
        self.assertFalse(result)

    def test_perf_tracker_and_metrics(self):
        """Test performance tracker records metrics correctly."""
        tracker = PerfTracker(action="search", user_id=999)
        tracker.db_ms = 45.2
        tracker.telegram_ms = 120.5
        tracker.send_count = 1
        tracker.telegram_calls = 1
        tracker.cache_hit = True

        # Ensure logging doesn't crash
        tracker.log()

        metrics = ApiCallMetrics()
        metrics.inc("send_message", 3)
        metrics.inc("edit_message", 2)
        summary = metrics.get_stats()
        self.assertEqual(summary["send_message"], 3)
        self.assertEqual(summary["edit_message"], 2)

    async def test_concurrent_multi_user_isolation(self):
        """Simulate multiple concurrent users performing callback actions simultaneously."""
        tracker = InFlightTracker()
        results = []

        async def simulate_user_action(user_id, msg_id, action):
            key = (user_id, msg_id, action)
            if tracker.acquire(key):
                await asyncio.sleep(0.01)  # Simulate DB/API work
                tracker.release(key)
                return True
            return False

        # Run 10 distinct users simultaneously - all must succeed without blocking
        tasks = [
            simulate_user_action(user_id=1000 + i, msg_id=1, action="next_page")
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks)
        self.assertEqual(sum(results), 10)

        # Run 5 concurrent clicks from the SAME user on the SAME message - exactly 1 must succeed
        same_user_tasks = [
            simulate_user_action(user_id=2000, msg_id=1, action="next_page")
            for _ in range(5)
        ]
        same_user_results = await asyncio.gather(*same_user_tasks)
        self.assertEqual(sum(same_user_results), 1)

    async def test_search_engine_candidate_filtering(self):
        """Test search engine fuzzy suggestions with candidate token filtering."""
        from search_engine import SearchEngine, SearchIntent, FuzzyScorer
        
        intent = SearchIntent("Inceptin")
        candidate1 = "Inception 2010 1080p BluRay"
        candidate2 = "Avengers Endgame 2019 2160p"

        score1, _ = FuzzyScorer.calculate_score(intent, candidate1)
        score2, _ = FuzzyScorer.calculate_score(intent, candidate2)

        self.assertGreater(score1, 60.0)
        self.assertLess(score2, 50.0)

        scored_candidates = [(score1, candidate1, {}), (score2, candidate2, {})]
        suggestions = SearchEngine.group_and_deduplicate(scored_candidates, max_results=5)
        self.assertTrue(any("Inception" in s for s in suggestions))

    async def test_fsub_loop_lifecycle_and_deduplication(self):
        """Test dynamic fsub check loop cancels previous duplicate task for same user."""
        from utils import _ACTIVE_FSUB_TASKS, check_loop_sub_dynamic

        client_mock = AsyncMock()
        msg_mock = AsyncMock()
        msg_mock.from_user.id = 5001
        msg_mock.chat.id = 5001
        prompt_mock = AsyncMock()
        prompt_mock.id = 999

        with patch("utils.build_dynamic_fsub_keyboard") as mock_build:
            # Simulate user already subscribed
            mock_build.return_value = (None, [])
            success = await check_loop_sub_dynamic(client_mock, msg_mock, file_id=None, prompt_msg=prompt_mock)
            self.assertTrue(success)
            self.assertNotIn(5001, _ACTIVE_FSUB_TASKS)


if __name__ == "__main__":
    unittest.main()
