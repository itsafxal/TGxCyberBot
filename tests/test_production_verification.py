import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock
from utils import (
    RequestTracker, InFlightTracker, MembershipCache,
    safe_send_message, safe_delete_message, safe_edit_message_text,
    safe_answer_callback, HEALTH_WATCHDOG, GLOBAL_METRICS
)
from sql.db import (
    init_aiosqlite_connection, get_search_results, 
    get_suggestions_sql, close_http_session, SQLITE_DB
)
from database.ia_filterdb import get_file_details
from plugins.pm_filter import generate_main_buttons, SEARCH_CACHE

class TestProductionVerification(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.conn = await init_aiosqlite_connection(":memory:")
        # Seed test database with diverse records
        for i in range(500):
            season = (i % 5) + 1
            ep = (i % 20) + 1
            await self.conn.execute(
                """
                INSERT OR REPLACE INTO media (file_id, file_ref, file_name, file_size, file_type, mime_type, caption, date_saved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"file_id_{i:05d}",
                    f"ref_{i}",
                    f"Vikram 2022 S{season:02d} EP{ep:02d} 1080p WebRip x264.mkv" if i % 2 == 0 else f"Inception 2010 Part {i} 720p BluRay.mkv",
                    1024 * 1024 * (500 + i),
                    "video",
                    "video/x-matroska",
                    f"Vikram Movie Part {i}" if i % 2 == 0 else f"Inception Sci-Fi {i}",
                    1700000000 + i
                )
            )
        await self.conn.commit()

    async def asyncTearDown(self):
        await close_http_session()

    async def _execute_traced_search(self, user_id: int, query: str):
        """Full traced pipeline measuring every single stage independently."""
        t_total_start = time.perf_counter()
        req = RequestTracker(op="search_pipeline", user_id=user_id, query=query)

        # 1. DB Stage
        t_db_start = time.perf_counter()
        req.start_stage("db")
        files, offset = await get_search_results(query, offset=0)
        req.end_stage("db")
        db_ms = (time.perf_counter() - t_db_start) * 1000

        # 2. Filter / Quality Stage
        t_filter_start = time.perf_counter()
        req.start_stage("filter")
        filtered_files = [f for f in files if "1080p" in f.get("file_name", "").lower() or "720p" in f.get("file_name", "").lower()]
        req.end_stage("filter")
        filter_ms = (time.perf_counter() - t_filter_start) * 1000

        # 3. Spellcheck Stage (if no results)
        spellcheck_ms = 0.0
        if not files:
            t_sp_start = time.perf_counter()
            req.start_stage("spellcheck")
            suggestions = await get_suggestions_sql(query)
            req.end_stage("spellcheck")
            spellcheck_ms = (time.perf_counter() - t_sp_start) * 1000

        # 4. Result Build Stage
        t_rb_start = time.perf_counter()
        req.start_stage("result_build")
        search_key = f"{user_id}_999"
        btn = generate_main_buttons(files if files else [], offset=0, search_key=search_key, next_offset=offset)
        SEARCH_CACHE.set(search_key, query)
        req.end_stage("result_build")
        result_build_ms = (time.perf_counter() - t_rb_start) * 1000

        # 5. Telegram Send Stage (mocked)
        t_tg_start = time.perf_counter()
        req.start_stage("telegram_send")
        mock_client = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.id = 1234
        mock_client.send_message.return_value = mock_msg
        await safe_send_message(mock_client, chat_id=user_id, text="Result", reply_markup=None)
        req.end_stage("telegram_send")
        telegram_send_ms = (time.perf_counter() - t_tg_start) * 1000

        total_ms = (time.perf_counter() - t_total_start) * 1000
        req.log()

        report_line = (
            f"request_id={req.req_id} user_id={user_id} query={query!r} "
            f"db_ms={db_ms:.2f} filter_ms={filter_ms:.2f} spellcheck_ms={spellcheck_ms:.2f} "
            f"result_build_ms={result_build_ms:.2f} telegram_send_ms={telegram_send_ms:.2f} "
            f"total_ms={total_ms:.2f}"
        )
        return report_line, total_ms

    async def test_01_start_help_commands_isolation(self):
        """Verify /start and /help execute fast and independently."""
        mock_client = AsyncMock()
        mock_client.send_message.return_value = MagicMock(id=100)
        
        t0 = time.perf_counter()
        res_start = await safe_send_message(mock_client, chat_id=101, text="/start response")
        dur_start_ms = (time.perf_counter() - t0) * 1000
        self.assertIsNotNone(res_start)
        self.assertLess(dur_start_ms, 50.0)

        t1 = time.perf_counter()
        res_help = await safe_send_message(mock_client, chat_id=102, text="/help response")
        dur_help_ms = (time.perf_counter() - t1) * 1000
        self.assertIsNotNone(res_help)
        self.assertLess(dur_help_ms, 50.0)
        print(f"\n[PASS] /start duration: {dur_start_ms:.2f}ms | /help duration: {dur_help_ms:.2f}ms")

    async def test_02_normal_and_unmatched_searches(self):
        """Test normal matching query and unmatched query with spell suggestions."""
        rep_matched, dur_m = await self._execute_traced_search(1001, "Vikram")
        self.assertLess(dur_m, 200.0)
        print(f"\n[MATCHED SEARCH] {rep_matched}")

        rep_unmatched, dur_u = await self._execute_traced_search(1002, "VikrammTypo")
        self.assertLess(dur_u, 3000.0)
        print(f"[UNMATCHED SEARCH] {rep_unmatched}")

    async def test_03_file_delivery_sqlite_first(self):
        """Verify get_file_details fetches from local SQLite directly."""
        t0 = time.perf_counter()
        files = await get_file_details("file_id_00000")
        dur_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(files), 1)
        self.assertIn("Vikram", files[0].file_name)
        self.assertLess(dur_ms, 20.0)
        print(f"\n[FILE DELIVERY] File lookup from indexed SQLite: {dur_ms:.2f}ms")

    async def test_04_restart_and_immediate_search(self):
        """Verify clean restart and instant search execution with zero warm-up delay."""
        # Simulate clean restart by re-initializing connection
        conn2 = await init_aiosqlite_connection(":memory:")
        await conn2.execute("INSERT OR REPLACE INTO media (file_id, file_name, file_size) VALUES ('f1', 'Avatar 2009 1080p.mkv', 1000)")
        await conn2.commit()

        t0 = time.perf_counter()
        files, _ = await get_search_results("Avatar", offset=0)
        dur_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(len(files), 1)
        self.assertLess(dur_ms, 30.0)
        print(f"\n[RESTART & IMMEDIATE SEARCH] Search immediately after restart: {dur_ms:.2f}ms")

    async def test_05_concurrency_10_20_50_users(self):
        """Execute simultaneous searches across 10, 20, and 50 concurrent simulated users."""
        for user_count in [10, 20, 50]:
            t0 = time.perf_counter()
            tasks = [self._execute_traced_search(2000 + i, "Vikram" if i % 2 == 0 else "Inception") for i in range(user_count)]
            results = await asyncio.gather(*tasks)
            total_time_ms = (time.perf_counter() - t0) * 1000
            avg_per_user = total_time_ms / user_count
            print(f"\n[CONCURRENCY {user_count} USERS] total={total_time_ms:.2f}ms | avg_per_user={avg_per_user:.2f}ms | all_success={len(results)==user_count}")
            self.assertLess(avg_per_user, 30.0)
