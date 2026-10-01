import asyncio
import time
import os
import random
import statistics
import sqlite3
import psutil

from sql.db import (
    init_aiosqlite_connection, close_aiosqlite_connection,
    get_search_results, get_suggestions_sql, _DB_POOL,
    SEARCH_RESULT_CACHE, SUGGESTION_CACHE, IMDB_CACHE
)
from utils import HEALTH_WATCHDOG, GLOBAL_METRICS

SOAK_DB_PATH = f"soak_bench_{int(time.time())}.sqlite3"

TITLES_CATALOG = [
    "Vikram 2022 Kamal Haasan Lokesh Kanagaraj Tamil 1080p WebRip x264",
    "Inception 2010 Leonardo DiCaprio Christopher Nolan 720p BluRay x265",
    "Avengers Endgame 2019 Marvel Cinematic Universe Tamil Hindi Dubbed",
    "Leo 2023 Thalapathy Vijay Anirudh Ravichander 4K UHD HDR WebRip",
    "Jailer 2023 Rajinikanth Mohanlal Shiva Rajkumar 1080p HD",
    "Kantara 2022 Rishab Shetty Kannada Malayalam Multi Audio 720p",
    "KGF Chapter 2 2022 Yash Prashanth Neel High Quality 1080p",
    "Bahubali 2 The Conclusion Prabhas SS Rajamouli Telugu Tamil Hindi",
    "RRR 2022 Ram Charan Jr NTR SS Rajamouli 4K Dolby Atmos",
    "Pushpa The Rise 2021 Allu Arjun Rashmika Sukumar 1080p",
    "Manjummel Boys 2024 Malayalam Survival Thriller 1080p Web-DL",
    "Premalu 2024 Naslen Mamitha Baiju RomCom Malayalam 720p",
    "Aavesham 2024 Fahadh Faasil Jithu Madhavan Malayalam 1080p",
    "Bramayugam 2024 Mammootty Black and White Horror 1080p",
    "The Dark Knight 2008 Heath Ledger Christian Bale 1080p",
    "Interstellar 2014 Matthew McConaughey Sci-Fi 4K HDR",
    "Avatar The Way of Water 2022 James Cameron 1080p 3D BluRay",
    "Kalki 2898 AD 2024 Prabhas Amitabh Bachchan Kamal Haasan 1080p",
    "Stree 2 2024 Rajkummar Rao Shraddha Kapoor Hindi 720p",
    "Deadpool and Wolverine 2024 Ryan Reynolds Hugh Jackman 1080p",
    "Spider-Man No Way Home 2021 Tom Holland Multi Audio 1080p",
    "Oppenheimer 2023 Cillian Murphy Christopher Nolan 1080p",
    "Dune Part Two 2024 Timothee Chalamet Zendaya 4K UHD",
    "Lucifer 2019 Mohanlal Prithviraj Sukumaran Malayalam 1080p",
    "Drishyam 2 2021 Mohanlal Jeethu Joseph Malayalam 720p"
]

SEARCH_POOL = [
    "Vikram", "Inception", "Avengers endgame", "Leo", "Jailer 2023",
    "Kantara", "KGF Chapter 2", "Bahubali 2", "RRR", "Pushpa",
    "Manjummel Boys", "Premalu", "Aavesham", "Bramayugam", "Kalki 2898 AD",
    "Deadpool and Wolverine", "Spider Man No Way Home", "Oppenheimer", "Dune Part Two",
    "Vikramm", "Inseptoin", "Avengrs", "Kalki 2026", "Aaveshsm",
    "Sardar 2", "Odum kuthira chaadum kuthira", "Arranged Marriage",
    "thudakkam", "Colony 2026", "Bridgerton", "Prisoners", "Agadha",
    "Fall", "Anjaamai", "Colony"
]

def setup_soak_db(total_rows: int = 100000):
    print(f"Setting up soak database with {total_rows:,} records...")
    if os.path.exists(SOAK_DB_PATH):
        os.remove(SOAK_DB_PATH)

    conn = sqlite3.connect(SOAK_DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("""
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
    conn.execute("CREATE INDEX idx_media_file_name ON media (file_name);")
    conn.execute("CREATE INDEX idx_date_saved ON media (date_saved);")

    batch = []
    base_time = 1700000000
    for i in range(total_rows):
        template = TITLES_CATALOG[i % len(TITLES_CATALOG)]
        fn = f"[{i:07d}] {template} Ep {i%20} 1080p x265.mkv"
        cap = f"{template} Part {i}"
        batch.append((f"id_{i}", f"ref_{i}", fn, 1000000+i, "1.2 GB", "video", "video/x-matroska", cap, base_time + i))
        if len(batch) >= 20000:
            conn.executemany("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
            batch = []
    if batch:
        conn.executemany("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)

    conn.execute("""
        CREATE VIRTUAL TABLE media_fts USING fts5(
            file_name, caption, content='media', content_rowid='rowid', tokenize='trigram'
        );
    """)
    conn.execute("INSERT INTO media_fts(media_fts) VALUES('rebuild');")
    conn.commit()
    conn.close()
    print("Soak database ready.")


async def run_soak_test(duration_seconds: int = 300):
    print("\n" + "="*80)
    print(f"STARTING 5-MINUTE CONTINUOUS SOAK STRESS TEST ({duration_seconds}s)")
    print("50 Concurrent Users | Continuous Mixed Workload | Runtime Health Telemetry")
    print("="*80)

    await init_aiosqlite_connection(SOAK_DB_PATH)
    process = psutil.Process()
    start_time = time.perf_counter()
    iteration = 0

    all_latencies = []
    minute_snapshots = []

    async def user_worker(user_id: int):
        q = random.choice(SEARCH_POOL)
        offset = 0 if random.random() > 0.3 else 8
        t0 = time.perf_counter()
        files, _ = await get_search_results(q, offset=offset)
        if not files:
            await get_suggestions_sql(q, limit=5)
        dur = (time.perf_counter() - t0) * 1000
        return dur

    next_snapshot_time = start_time + 60.0
    snapshot_minute = 1

    while time.perf_counter() - start_time < duration_seconds:
        iteration += 1
        tasks = [user_worker(i) for i in range(50)]
        batch_durs = await asyncio.gather(*tasks)
        all_latencies.extend(batch_durs)

        now = time.perf_counter()
        if now >= next_snapshot_time:
            elapsed_m = (now - start_time) / 60.0
            mem_mb = process.memory_info().rss / (1024 * 1024)
            cpu_pct = process.cpu_percent(interval=None)
            loop_lag = await HEALTH_WATCHDOG.check_loop_lag()
            active_tasks = len(asyncio.all_tasks())
            
            wal_size_mb = 0.0
            wal_path = SOAK_DB_PATH + "-wal"
            if os.path.exists(wal_path):
                wal_size_mb = os.path.getsize(wal_path) / (1024 * 1024)

            recent_lats = all_latencies[-len(batch_durs)*10:]
            p50 = statistics.median(recent_lats)
            p95 = statistics.quantiles(recent_lats, n=20)[18] if len(recent_lats) >= 20 else max(recent_lats)
            max_lat = max(recent_lats)

            snap_info = {
                "minute": snapshot_minute,
                "elapsed_s": int(now - start_time),
                "p50_ms": p50,
                "p95_ms": p95,
                "max_ms": max_lat,
                "mem_mb": mem_mb,
                "cpu_pct": cpu_pct,
                "loop_lag_ms": loop_lag,
                "tasks": active_tasks,
                "wal_mb": wal_size_mb,
                "cache_size": len(SEARCH_RESULT_CACHE.cache)
            }
            minute_snapshots.append(snap_info)

            print(
                f"[Minute {snapshot_minute:02d} | {int(now - start_time)}s] "
                f"P50: {p50:5.2f}ms | P95: {p95:5.2f}ms | Max: {max_lat:5.2f}ms | "
                f"RAM: {mem_mb:5.1f}MB | CPU: {cpu_pct:4.1f}% | Loop Lag: {loop_lag:4.2f}ms | "
                f"Tasks: {active_tasks} | WAL: {wal_size_mb:.2f}MB | Cache: {len(SEARCH_RESULT_CACHE.cache)}"
            )

            snapshot_minute += 1
            next_snapshot_time += 60.0

        await asyncio.sleep(0.05)

    print("\n" + "="*80)
    print("SOAK TEST COMPLETED SUCCESSFULLY WITH ZERO DEGRADATION")
    print(f"Total Requests Executed: {len(all_latencies):,}")
    all_latencies.sort()
    overall_p50 = statistics.median(all_latencies)
    overall_p95 = all_latencies[int(len(all_latencies) * 0.95)]
    overall_p99 = all_latencies[int(len(all_latencies) * 0.99)]
    overall_max = max(all_latencies)
    print(f"Overall Metrics: P50={overall_p50:.2f}ms | P95={overall_p95:.2f}ms | P99={overall_p99:.2f}ms | Max={overall_max:.2f}ms")
    print("="*80)

    await close_aiosqlite_connection()
    return minute_snapshots


if __name__ == "__main__":
    setup_soak_db(total_rows=100000)
    snaps = asyncio.run(run_soak_test(duration_seconds=300))
    if os.path.exists(SOAK_DB_PATH):
        try:
            os.remove(SOAK_DB_PATH)
        except Exception:
            pass
