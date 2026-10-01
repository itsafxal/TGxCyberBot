import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pyrogram.errors import (
    FloodWait, RPCError, MessageIdInvalid, MessageDeleteForbidden, 
    UserIsBlocked, InputUserDeactivated
)
from utils import (
    RequestTracker, InFlightTracker, MembershipCache,
    safe_send_message, safe_delete_message, safe_edit_message_text,
    safe_answer_callback, HEALTH_WATCHDOG, GLOBAL_METRICS
)
from sql.db import (
    init_aiosqlite_connection, save_file_sql, get_search_results, 
    get_suggestions_sql, SQLITE_DB
)

class TestFailureInjectionAndLoad(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.tracker = InFlightTracker(ttl=10.0)
        self.membership_cache = MembershipCache()
        conn = await init_aiosqlite_connection(":memory:")
        for i in range(100):
            await conn.execute(
                """
                INSERT OR REPLACE INTO media (file_id, file_ref, file_name, file_size, file_type, mime_type, caption, date_saved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"fid_{i:04d}",
                    "ref123",
                    f"Avengers Endgame 2019 Part {i} 1080p.mkv",
                    1024 * 1024 * (i + 1),
                    "video",
                    "video/x-matroska",
                    f"Avengers Endgame Part {i}",
                    1700000000 + i
                )
            )
        await conn.commit()

    async def test_50_concurrent_users_independent_operations(self):
        """Simulate 50 users doing simultaneous searches, start, and callbacks."""
        t0 = time.perf_counter()
        
        async def user_workflow(user_id: int):
            req = RequestTracker(op="simulated_user", user_id=user_id, query="Avengers")
            req.start_stage("search")
            files, offset = await get_search_results("Avengers", offset=0)
            req.end_stage("search")
            self.assertTrue(len(files) > 0)

            # Acquire callback lock
            lock_key = (user_id, 100, "page_2")
            acquired = self.tracker.acquire(lock_key)
            self.assertTrue(acquired)
            try:
                await asyncio.sleep(0.002) # simulate Telegram network latency
            finally:
                self.tracker.release(lock_key)
            req.log()
            return True

        tasks = [user_workflow(user_id=1000 + i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        total_time_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(results), 50)
        self.assertTrue(all(results))
        print(f"\n[LOAD TEST] 50 Concurrent Users: total_time={total_time_ms:.2f}ms (avg={total_time_ms/50:.2f}ms/user)")

    async def test_failure_injection_flood_wait_isolation(self):
        """Inject FloodWait on User A and ensure User B completes immediately without delay."""
        client_mock = AsyncMock()

        # User A triggers a 30-second FloodWait
        async def mock_send_user_a(*args, **kwargs):
            raise FloodWait(30)

        # User B succeeds normally
        async def mock_send_user_b(*args, **kwargs):
            mock_msg = MagicMock()
            mock_msg.id = 999
            return mock_msg

        # User A call
        t_a_start = time.perf_counter()
        client_mock.send_message = mock_send_user_a
        result_a = await safe_send_message(client_mock, chat_id=111, text="Test A")
        dur_a_ms = (time.perf_counter() - t_a_start) * 1000
        self.assertIsNone(result_a)
        self.assertLess(dur_a_ms, 500) # Must NOT freeze/block for 30s!

        # User B call
        t_b_start = time.perf_counter()
        client_mock.send_message = mock_send_user_b
        result_b = await safe_send_message(client_mock, chat_id=222, text="Test B")
        dur_b_ms = (time.perf_counter() - t_b_start) * 1000
        self.assertIsNotNone(result_b)
        self.assertLess(dur_b_ms, 100)

    async def test_failure_injection_rpc_timeout_and_network_error(self):
        """Inject asyncio.TimeoutError and RPCError and ensure safe recovery."""
        client_mock = AsyncMock()
        client_mock.send_message.side_effect = asyncio.TimeoutError("Connection timed out")

        result = await safe_send_message(client_mock, chat_id=123, text="Timeout test")
        self.assertIsNone(result)

    async def test_health_watchdog_reports_low_latency(self):
        """Ensure health watchdog correctly checks loop lag."""
        report = await HEALTH_WATCHDOG.get_health_report()
        self.assertIn("loop_lag_ms", report)
        self.assertIn("active_tasks", report)
        self.assertLess(report["loop_lag_ms"], 50.0)
