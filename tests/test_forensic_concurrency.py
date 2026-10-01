import asyncio
import time
import os
import random
import statistics
import sqlite3
import psutil

from sql.db import (
    init_aiosqlite_connection, close_aiosqlite_connection,
    get_search_results, get_suggestions_sql, _DB_POOL, SQLITE_DB
)

TEST_DB_PATH = f"prod_bench_{int(time.time())}.sqlite3"

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

REALISTIC_SEARCH_QUERIES = [
    # Hit queries
    "Vikram", "Inception", "Avengers endgame", "Leo", "Jailer 2023",
    "Kantara", "KGF Chapter 2", "Bahubali 2", "RRR", "Pushpa",
    "Manjummel Boys", "Premalu", "Aavesham", "Bramayugam", "Kalki 2898 AD",
    "Deadpool and Wolverine", "Spider Man No Way Home", "Oppenheimer", "Dune Part Two",
    # Typos / Spell check candidates
    "Vikramm", "Inseptoin", "Avengrs", "Kalki 2026", "Aaveshsm",
    # Unmatched queries from production logs
    "Sardar 2", "Odum kuthira chaadum kuthira", "Arranged Marriage",
    "thudakkam", "Colony 2026", "Bridgerton", "Prisoners", "Agadha",
    "Fall", "Anjaamai", "Colony"
]

def generate_production_test_db(total_rows: int = 150000):
    print(f"Generating realistic production database with {total_rows:,} records at {TEST_DB_PATH}...")
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -64000;")
    conn.execute("PRAGMA mmap_size = 268435456;")
    conn.execute("PRAGMA temp_store = MEMORY;")

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
    conn.execute("CREATE INDEX idx_media_caption ON media (caption);")
    conn.execute("CREATE INDEX idx_date_saved ON media (date_saved);")
    conn.execute("CREATE INDEX idx_media_date_name ON media (date_saved DESC, file_name);")

    t0 = time.perf_counter()
    batch = []
    base_time = 1700000000
    for i in range(total_rows):
        template = TITLES_CATALOG[i % len(TITLES_CATALOG)]
        season = (i % 8) + 1
        ep = (i % 24) + 1
        fn = f"[{i:07d}] {template} Season {season} Episode {ep} Dual Audio [CyberTG].mkv"
        cap = f"{template} S{season:02d}E{ep:02d} High Definition Download @TGxCyberBot"
        f_size = 1024 * 1024 * (300 + (i % 1700))
        batch.append((
            f"file_id_{i:08d}",
            f"ref_{i:08d}",
            fn,
            f_size,
            f"{f_size / (1024*1024):.1f} MB",
            "video",
            "video/x-matroska",
            cap,
            base_time + i
        ))
        if len(batch) >= 25000:
            conn.executemany("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)
            batch = []
    if batch:
        conn.executemany("INSERT INTO media VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)

    print(f"Building FTS5 trigram virtual table across {total_rows:,} rows...")
    t_fts = time.perf_counter()
    conn.execute("""
        CREATE VIRTUAL TABLE media_fts USING fts5(
            file_name, caption, content='media', content_rowid='rowid', tokenize='trigram'
        );
    """)
    conn.execute("""
        CREATE TRIGGER media_ai AFTER INSERT ON media BEGIN
            INSERT INTO media_fts(rowid, file_name, caption) VALUES (new.rowid, new.file_name, new.caption);
        END;
    """)
    conn.execute("""
        CREATE TRIGGER media_ad AFTER DELETE ON media BEGIN
            INSERT INTO media_fts(media_fts, rowid, file_name, caption) VALUES('delete', old.rowid, old.file_name, old.caption);
        END;
    """)
    conn.execute("""
        CREATE TRIGGER media_au AFTER UPDATE ON media BEGIN
            INSERT INTO media_fts(media_fts, rowid, file_name, caption) VALUES('delete', old.rowid, old.file_name, old.caption);
            INSERT INTO media_fts(rowid, file_name, caption) VALUES (new.rowid, new.file_name, new.caption);
        END;
    """)
    conn.execute("INSERT INTO media_fts(media_fts) VALUES('rebuild');")
    conn.commit()
    conn.close()
    print(f"Database generation completed in {time.perf_counter() - t0:.2f}s (FTS build: {time.perf_counter() - t_fts:.2f}s)")


async def run_realistic_concurrency_suite():
    await init_aiosqlite_connection(TEST_DB_PATH)

    async def single_user_search(user_id: int, query: str):
        t_start = time.perf_counter()
        files, offset = await get_search_results(query, offset=0)
        
        # If no results, simulate spell check suggestion fallback
        suggestions = []
        t_sp_start = time.perf_counter()
        if not files:
            suggestions = await get_suggestions_sql(query, limit=5)
        sp_dur_ms = (time.perf_counter() - t_sp_start) * 1000 if not files else 0.0

        total_dur_ms = (time.perf_counter() - t_start) * 1000
        return {
            "user_id": user_id,
            "query": query,
            "total_ms": total_dur_ms,
            "spellcheck_ms": sp_dur_ms,
            "results_count": len(files),
            "suggestions_count": len(suggestions)
        }

    print("\n" + "="*80)
    print("REALISTIC PRODUCTION CONCURRENCY BENCHMARK (150,000 ROWS ON-DISK SQLITE)")
    print("="*80)

    concurrency_levels = [1, 5, 10, 20, 50, 100]
    results_summary = {}

    for c in concurrency_levels:
        user_queries = [random.choice(REALISTIC_SEARCH_QUERIES) for _ in range(c)]
        
        t0 = time.perf_counter()
        tasks = [single_user_search(1000 + i, user_queries[i]) for i in range(c)]
        responses = await asyncio.gather(*tasks)
        batch_time_ms = (time.perf_counter() - t0) * 1000

        latencies = [r["total_ms"] for r in responses]
        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        max_lat = max(latencies)
        avg_lat = statistics.mean(latencies)

        results_summary[c] = {
            "p50": p50,
            "p95": p95,
            "p99": p99,
            "max": max_lat,
            "avg": avg_lat,
            "batch_time_ms": batch_time_ms
        }

        print(
            f"Concurrency={c:3d} users | Total Wall: {batch_time_ms:7.2f}ms | "
            f"P50: {p50:5.2f}ms | P95: {p95:5.2f}ms | P99: {p99:5.2f}ms | Max: {max_lat:5.2f}ms | "
            f"Avg: {avg_lat:5.2f}ms"
        )

    await close_aiosqlite_connection()
    return results_summary


if __name__ == "__main__":
    generate_production_test_db(total_rows=150000)
    summary = asyncio.run(run_realistic_concurrency_suite())
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
