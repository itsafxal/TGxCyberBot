import asyncio
import time
import unittest
import sqlite3
import aiosqlite
from unittest.mock import AsyncMock, patch

from sql.db import (
    compute_accuracy_score,
    clean_file_name_for_title,
    LRUCache
)
from search_engine import SearchEngine, SearchIntent, FuzzyScorer
from utils import (
    MembershipCache,
    InFlightTracker,
    safe_edit_message_text,
    safe_edit_reply_markup,
    safe_delete_message,
    safe_answer_callback,
    ApiCallMetrics,
    PerfTracker
)
from pyrogram.errors import FloodWait, MessageDeleteForbidden, MessageIdInvalid
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

class TestBenchmarkAndAudit(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Create an in-memory SQLite database with sample catalog
        self.db = await aiosqlite.connect(":memory:")
        await self.db.execute("""
            CREATE TABLE media (
                file_id TEXT PRIMARY KEY,
                file_ref TEXT,
                file_name TEXT,
                file_size INTEGER,
                size TEXT,
                file_type TEXT,
                mime_type TEXT,
                caption TEXT,
                date_saved TIMESTAMP
            )
        """)
        await self.db.execute("CREATE INDEX idx_media_file_name ON media (file_name);")
        await self.db.execute("CREATE INDEX idx_media_caption ON media (caption);")
        await self.db.execute("CREATE INDEX idx_date_saved ON media (date_saved);")

        # Insert 1000 sample movie records
        sample_movies = [
            "Inception 2010 1080p BluRay x264 DTS-HD",
            "Interstellar 2014 IMAX 720p WEB-DL Dual Audio",
            "The Dark Knight 2008 2160p UHD HDR REMUX",
            "The Dark Knight Rises 2012 1080p BluRay",
            "Oppenheimer 2023 1080p WEB-DL Malayalam Sub",
            "Dune Part Two 2024 1080p HQ HDRip",
            "Avengers Endgame 2019 4K UHD Multi Audio",
            "Spider-Man No Way Home 2021 1080p Hindi Dubbed",
            "Premam 2015 720p Malayalam Movie HDRip",
            "Manjummel Boys 2024 1080p True WEB-DL"
        ]
        records = []
        for i in range(1000):
            base = sample_movies[i % len(sample_movies)]
            fn = f"{base} Release_{i}.mkv"
            records.append((f"id_{i}", f"ref_{i}", fn, 1024*1024*1500, "1.5 GB", "video", "video/x-matroska", fn, f"2024-01-01 {i%24:02d}:00:00"))
        
        await self.db.executemany("INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?)", records)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_local_sqlite_search_latency_benchmark(self):
        """[Local DB Benchmark] Measure real search latency over 1000 records."""
        query = "SELECT file_id, file_name, size FROM media WHERE (file_name LIKE ? OR caption LIKE ?) ORDER BY date_saved DESC LIMIT 11 OFFSET 0"
        
        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            async with self.db.execute(query, ("%Inception%", "%Inception%")) as cursor:
                rows = await cursor.fetchall()
            latencies.append((time.perf_counter() - t0) * 1000)
            self.assertGreater(len(rows), 0)

        avg_ms = sum(latencies) / len(latencies)
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)]
        print(f"\n[BENCHMARK - Local SQLite Search] 50 queries: avg={avg_ms:.3f}ms, p95={p95_ms:.3f}ms, min={min(latencies):.3f}ms, max={max(latencies):.3f}ms")
        self.assertLess(avg_ms, 25.0)  # Must be fast

    async def test_local_spell_check_fuzzy_scoring_benchmark(self):
        """[Local DB Benchmark] Measure spell-check candidate retrieval and fuzzy scoring."""
        latencies = []
        for _ in range(30):
            t0 = time.perf_counter()
            suggestions = await SearchEngine.get_suggestions_sql(self.db, "Inceptin", limit=5)
            latencies.append((time.perf_counter() - t0) * 1000)
            self.assertGreater(len(suggestions), 0)

        avg_ms = sum(latencies) / len(latencies)
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)]
        print(f"\n[BENCHMARK - Spell Check Fuzzy Scorer] 30 runs: avg={avg_ms:.3f}ms, p95={p95_ms:.3f}ms, min={min(latencies):.3f}ms, max={max(latencies):.3f}ms")
        self.assertLess(avg_ms, 30.0)

    async def test_multi_user_concurrent_lock_isolation_benchmark(self):
        """[Concurrency Benchmark] 20 concurrent users simulating 100 total requests."""
        tracker = InFlightTracker()
        processed = 0

        async def worker(user_id, msg_id, action):
            nonlocal processed
            key = (user_id, msg_id, action)
            if tracker.acquire(key):
                await asyncio.sleep(0.001)  # Micro simulated DB wait
                processed += 1
                tracker.release(key)
                return True
            return False

        # 20 distinct users
        t0 = time.perf_counter()
        tasks = [worker(u, 1, "next") for u in range(20)]
        results = await asyncio.gather(*tasks)
        total_time_ms = (time.perf_counter() - t0) * 1000

        print(f"\n[BENCHMARK - Concurrency Isolation] 20 users concurrent: total={total_time_ms:.3f}ms, all_succeeded={all(results)}")
        self.assertEqual(sum(results), 20)
        self.assertEqual(processed, 20)

    async def test_flood_wait_fail_fast_on_large_delays(self):
        """[Audit] Verify safe_edit_message_text does NOT hang or prematurely retry on FloodWait > 3s."""
        msg_mock = AsyncMock()
        msg_mock.text = "Old Text"
        msg_mock.edit_text.side_effect = FloodWait(20)  # 20s Telegram cooldown

        t0 = time.perf_counter()
        result = await safe_edit_message_text(msg_mock, "New Text")
        elapsed = time.perf_counter() - t0

        # Should fail fast immediately (< 0.1s) and return False rather than sleeping 4s or 20s
        self.assertFalse(result)
        self.assertLess(elapsed, 0.5)
        msg_mock.edit_text.assert_called_once()

    async def test_flood_wait_retry_on_small_delay(self):
        """[Audit] Verify safe_edit_message_text sleeps full duration and retries once for small FloodWait (<=3s)."""
        msg_mock = AsyncMock()
        msg_mock.text = "Old Text"
        # First call raises FloodWait(1), second succeeds
        msg_mock.edit_text.side_effect = [FloodWait(1), True]

        t0 = time.perf_counter()
        result = await safe_edit_message_text(msg_mock, "New Text")
        elapsed = time.perf_counter() - t0

        self.assertTrue(result)
        self.assertGreaterEqual(elapsed, 1.0)  # Must have respected the 1.0s wait
        self.assertEqual(msg_mock.edit_text.call_count, 2)


if __name__ == "__main__":
    unittest.main()
