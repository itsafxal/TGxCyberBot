import asyncio
import logging
import sqlite3
import aiosqlite
import datetime
import pytz
import re
import difflib
import aiohttp
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict, defaultdict
from typing import Tuple, List, Optional, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient

from info import DATABASE_URI2, DATABASE_NAME, DATABASE_URI3, COLLECTION_NAME, MAX_FILES, BOT_TOKEN
from database.ia_filterdb import unpack_new_file_id
from utils import get_size
from search_engine import SearchEngine, QueryNormalizer

# --- Configuration ---
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BATCH_SIZE = 10000
SUPER_BATCH_SIZE = 100000

GENERIC_STOPWORDS = {
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "movie", "film", "series", "season", "episode", "ep", "s", "e", "part", "vol", "volume",
    "all", "full", "hd", "rip", "bluray", "webrip", "dvdrip", "x264", "x265", "hevc",
    "1080p", "720p", "480p", "2160p", "4k", "hindi", "tamil", "telugu", "malayalam", "kannada", "english"
}

SQLITE_DB = f"media_{BOT_TOKEN}.sqlite3"

# --- LRU Cache ---
class LRUCache:
    def __init__(self, max_size=2000, ttl=3600):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self.cache:
                val, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    self.cache.move_to_end(key)
                    return val
                else:
                    del self.cache[key]
            return None

    def set(self, key, val):
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = (val, time.time())
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)

    def clear(self):
        with self._lock:
            self.cache.clear()

IMDB_CACHE = LRUCache(max_size=1000, ttl=86400)
SEARCH_RESULT_CACHE = LRUCache(max_size=5000, ttl=300)
SUGGESTION_CACHE = LRUCache(max_size=2000, ttl=600)

# Anti-stampede in-flight deduplicator
_IN_FLIGHT_SEARCHES: Dict[str, asyncio.Future] = {}
_STAMPEDE_LOCK = asyncio.Lock()

client2 = AsyncIOMotorClient(DATABASE_URI2)
db2 = client2[DATABASE_NAME]

client3 = AsyncIOMotorClient(DATABASE_URI3)
db3 = client3[DATABASE_NAME]

COLLECTIONS_TO_MIGRATE = [
    {"db": db3, "collection_name": COLLECTION_NAME},
    {"db": db2, "collection_name": COLLECTION_NAME},
]


# --- High-Performance Multi-Reader SQLite Pool ---
class SQLitePoolManager:
    """
    Manages concurrent SQLite access using WAL mode.
    - Reader pool: 16 background threads with thread-local persistent connections.
    - Single writer lock: serializes database mutations to avoid lock collisions.
    - Zero global reader blocking.
    """
    def __init__(self, db_path: str = SQLITE_DB, max_readers: int = 16):
        self.db_path = db_path
        self.max_readers = max_readers
        self.executor = ThreadPoolExecutor(max_workers=max_readers, thread_name_prefix="sqlite_reader")
        self._local_conns: Dict[int, sqlite3.Connection] = {}
        self._conns_lock = threading.Lock()
        self._write_lock = asyncio.Lock()
        self._is_memory = (db_path == ":memory:")
        self._mem_conn = None
        if self._is_memory:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=10.0)
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")

    def _get_thread_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            return self._mem_conn
        t_id = threading.get_ident()
        with self._conns_lock:
            conn = self._local_conns.get(t_id)
            if conn is None:
                conn = sqlite3.connect(
                    self.db_path,
                    timeout=10.0,
                    check_same_thread=False,
                    isolation_level=None  # autocommit mode for readers
                )
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute("PRAGMA busy_timeout = 10000;")
                conn.execute("PRAGMA cache_size = -64000;")
                conn.execute("PRAGMA mmap_size = 268435456;")
                conn.execute("PRAGMA temp_store = MEMORY;")
                self._local_conns[t_id] = conn
            return conn

    async def execute_read(self, sql: str, params: tuple = ()) -> Tuple[List[Any], Dict[str, float]]:
        """Executes a read query in the thread pool (or memory connection) and collects detailed metrics."""
        t_acquire_start = time.perf_counter()
        if self._is_memory:
            global _global_aiosqlite_connection
            t_exec_start = time.perf_counter()
            async with _global_aiosqlite_connection.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
            t_fetch_end = time.perf_counter()
            metrics = {
                "conn_wait_ms": (t_exec_start - t_acquire_start) * 1000,
                "sql_exec_ms": (t_fetch_end - t_exec_start) * 1000,
                "sql_fetch_ms": 0.0,
                "row_count": len(rows)
            }
            return rows, metrics

        loop = asyncio.get_running_loop()

        def _worker():
            t_worker_start = time.perf_counter()
            conn_wait_ms = (t_worker_start - t_acquire_start) * 1000
            conn = self._get_thread_connection()
            cur = conn.cursor()
            t_exec_start = time.perf_counter()
            cur.execute(sql, params)
            t_exec_end = time.perf_counter()
            rows = cur.fetchall()
            t_fetch_end = time.perf_counter()

            metrics = {
                "conn_wait_ms": conn_wait_ms,
                "sql_exec_ms": (t_exec_end - t_exec_start) * 1000,
                "sql_fetch_ms": (t_fetch_end - t_exec_end) * 1000,
                "row_count": len(rows)
            }
            return rows, metrics

        return await loop.run_in_executor(self.executor, _worker)

    async def execute_write(self, func, *args, **kwargs):
        """Executes a write operation under an async lock to prevent write-lock collisions."""
        t_lock_start = time.perf_counter()
        async with self._write_lock:
            lock_wait_ms = (time.perf_counter() - t_lock_start) * 1000
            
            if self._is_memory:
                global _global_aiosqlite_connection
                raw_conn = _global_aiosqlite_connection._conn
                result = func(raw_conn, *args, **kwargs)
                await _global_aiosqlite_connection.commit()
                return result, {"lock_wait_ms": lock_wait_ms, "sql_exec_ms": 0.0}

            loop = asyncio.get_running_loop()
            
            def _write_worker():
                t_exec_start = time.perf_counter()
                conn = sqlite3.connect(
                    self.db_path,
                    timeout=20.0,
                    check_same_thread=False
                )
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute("PRAGMA busy_timeout = 15000;")

                try:
                    conn.execute("BEGIN IMMEDIATE;")
                    result = func(conn, *args, **kwargs)
                    conn.commit()
                    t_exec_end = time.perf_counter()
                    metrics = {
                        "lock_wait_ms": lock_wait_ms,
                        "sql_exec_ms": (t_exec_end - t_exec_start) * 1000
                    }
                    return result, metrics
                except Exception as e:
                    conn.rollback()
                    raise e
                finally:
                    conn.close()

            return await loop.run_in_executor(self.executor, _write_worker)

    def close(self):
        with self._conns_lock:
            for conn in self._local_conns.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._local_conns.clear()
        self.executor.shutdown(wait=False)

# Global pool instance
_DB_POOL: Optional[SQLitePoolManager] = None
_global_aiosqlite_connection: Optional[aiosqlite.Connection] = None
_connection_lock = asyncio.Lock()


async def init_aiosqlite_connection(db_path: Optional[str] = None):
    """Initializes SQLite schema, FTS5 virtual tables, triggers, and reader pool."""
    global _global_aiosqlite_connection, _DB_POOL
    if db_path is None:
        db_path = SQLITE_DB

    async with _connection_lock:
        if _DB_POOL is not None and (db_path and _DB_POOL.db_path != db_path):
            _DB_POOL.close()
            _DB_POOL = None
        if _global_aiosqlite_connection is not None and db_path and db_path == ":memory:":
            try:
                await _global_aiosqlite_connection.close()
            except Exception:
                pass
            _global_aiosqlite_connection = None

        if _DB_POOL is None:
            _DB_POOL = SQLitePoolManager(db_path=db_path)

        if _global_aiosqlite_connection is None:
            _global_aiosqlite_connection = await aiosqlite.connect(db_path)
            if db_path != ":memory:":
                await _global_aiosqlite_connection.execute("PRAGMA journal_mode = WAL;")
                await _global_aiosqlite_connection.execute("PRAGMA synchronous = NORMAL;")
                await _global_aiosqlite_connection.execute("PRAGMA busy_timeout = 10000;")
                await _global_aiosqlite_connection.execute("PRAGMA cache_size = -64000;")
                await _global_aiosqlite_connection.execute("PRAGMA mmap_size = 268435456;")
                await _global_aiosqlite_connection.execute("PRAGMA temp_store = MEMORY;")
            await _global_aiosqlite_connection.execute("PRAGMA foreign_keys = ON;")
            
            # 1. Base media table
            await _global_aiosqlite_connection.execute("""
                CREATE TABLE IF NOT EXISTS media (
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
            await _global_aiosqlite_connection.execute("CREATE INDEX IF NOT EXISTS idx_media_file_name ON media (file_name);")
            await _global_aiosqlite_connection.execute("CREATE INDEX IF NOT EXISTS idx_media_caption ON media (caption);")
            await _global_aiosqlite_connection.execute("CREATE INDEX IF NOT EXISTS idx_date_saved ON media (date_saved);")
            await _global_aiosqlite_connection.execute("CREATE INDEX IF NOT EXISTS idx_media_date_name ON media (date_saved DESC, file_name);")
            
            # 2. High-speed FTS5 virtual table for sub-millisecond substring/trigram searches
            try:
                await _global_aiosqlite_connection.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
                        file_name, caption, content='media', content_rowid='rowid', tokenize='trigram'
                    );
                """)
                # Auto-sync triggers for FTS5
                await _global_aiosqlite_connection.execute("""
                    CREATE TRIGGER IF NOT EXISTS media_ai AFTER INSERT ON media BEGIN
                        INSERT INTO media_fts(rowid, file_name, caption) VALUES (new.rowid, new.file_name, new.caption);
                    END;
                """)
                await _global_aiosqlite_connection.execute("""
                    CREATE TRIGGER IF NOT EXISTS media_ad AFTER DELETE ON media BEGIN
                        INSERT INTO media_fts(media_fts, rowid, file_name, caption) VALUES('delete', old.rowid, old.file_name, old.caption);
                    END;
                """)
                await _global_aiosqlite_connection.execute("""
                    CREATE TRIGGER IF NOT EXISTS media_au AFTER UPDATE ON media BEGIN
                        INSERT INTO media_fts(media_fts, rowid, file_name, caption) VALUES('delete', old.rowid, old.file_name, old.caption);
                        INSERT INTO media_fts(rowid, file_name, caption) VALUES (new.rowid, new.file_name, new.caption);
                    END;
                """)
                
                # Check if FTS needs initial population from media
                async with _global_aiosqlite_connection.execute("SELECT COUNT(*) FROM media") as cur_m:
                    m_count = (await cur_m.fetchone())[0]
                if m_count > 0:
                    async with _global_aiosqlite_connection.execute("SELECT COUNT(*) FROM media_fts") as cur_f:
                        f_count = (await cur_f.fetchone())[0]
                    if f_count == 0:
                        logging.info(f"Rebuilding FTS5 index for {m_count} records...")
                        await _global_aiosqlite_connection.execute("INSERT INTO media_fts(media_fts) VALUES('rebuild');")
                        logging.info("FTS5 index build complete.")
            except Exception as e:
                logging.warning(f"FTS5 initialization warning: {e}")

            await _global_aiosqlite_connection.commit()
            logging.info(f"SQLite pool & aiosqlite connection opened with WAL and FTS5 to {db_path}")

        return _global_aiosqlite_connection


async def ensure_aiosqlite_connection() -> aiosqlite.Connection:
    if _global_aiosqlite_connection is None:
        await init_aiosqlite_connection()
    return _global_aiosqlite_connection


async def close_aiosqlite_connection():
    global _global_aiosqlite_connection, _DB_POOL
    async with _connection_lock:
        if _global_aiosqlite_connection:
            await _global_aiosqlite_connection.close()
            _global_aiosqlite_connection = None
        if _DB_POOL:
            _DB_POOL.close()
            _DB_POOL = None
        logging.info("SQLite connections closed.")


def get_aiosqlite_connection() -> aiosqlite.Connection:
    if _global_aiosqlite_connection is None:
        raise RuntimeError("aiosqlite connection is not initialized. Call init_aiosqlite_connection first.")
    return _global_aiosqlite_connection


async def check_table_exists(table_name: str) -> bool:
    db = await ensure_aiosqlite_connection()
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ) as cursor:
        return await cursor.fetchone() is not None


async def check_data_exists(table_name: str) -> bool:
    db = await ensure_aiosqlite_connection()
    async with db.execute(f"SELECT 1 FROM {table_name} LIMIT 1") as cursor:
        return await cursor.fetchone() is not None


async def set_sqlite_pragmas(db: aiosqlite.Connection):
    await db.execute("PRAGMA journal_mode = WAL;")
    await db.execute("PRAGMA synchronous = NORMAL;")
    await db.execute("PRAGMA cache_size = -64000;")
    await db.execute("PRAGMA mmap_size = 268435456;")
    await db.execute("PRAGMA temp_store = MEMORY;")
    await db.commit()


async def insert_batch_no_commit(db, batch):
    await db.executemany("""
        INSERT OR REPLACE INTO media (
            file_id, file_ref, file_name, file_size, size,
            file_type, mime_type, caption, date_saved
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch)


async def migrate_to_sql():
    logging.info("🚀 Starting multi-database migration with high-speed optimizations...")
    sql_db = await ensure_aiosqlite_connection()
    data_exists_in_table = await check_data_exists("media")
    if data_exists_in_table:
        logging.info("SQLite 'media' table already populated. Skipping full migration.")
        return

    logging.info("SQLite 'media' table is empty. Proceeding with full migration.")
    total_files_saved_across_all_sources = 0
    for item in COLLECTIONS_TO_MIGRATE:
        current_db = item["db"]
        current_collection_name = item["collection_name"]
        collection = current_db[current_collection_name]
        logging.info(f"\nMigrating from MongoDB: '{current_db.name}', Collection: '{current_collection_name}'...")

        try:
            doc_count = await collection.count_documents({})
            if doc_count == 0:
                logging.warning(f"  Collection '{current_collection_name}' is EMPTY.")
                continue
            logging.info(f"  Found {doc_count} documents to migrate.")
        except Exception as e:
            logging.critical(f"  CRITICAL ERROR connecting to DB '{current_db.name}': {e}", exc_info=True)
            continue

        try:
            cursor = collection.find({})
            batch = []
            total_saved_current_collection = 0
            
            async for doc in cursor:
                batch.append((
                    str(doc.get("_id")),
                    doc.get("file_ref"),
                    doc.get("file_name"),
                    doc.get("file_size"),
                    doc.get("size"),
                    doc.get("file_type"),
                    doc.get("mime_type"),
                    doc.get("caption"),
                    doc.get("date", datetime.datetime.now(pytz.utc))
                ))
                
                if len(batch) >= BATCH_SIZE:
                    await insert_batch_no_commit(sql_db, batch)
                    total_saved_current_collection += len(batch)
                    batch = []
                    
                    if total_saved_current_collection % SUPER_BATCH_SIZE == 0:
                        await sql_db.commit()
                        logging.info(f"  Super-batch committed ({total_saved_current_collection} files saved).")

            if batch:
                await insert_batch_no_commit(sql_db, batch)
                total_saved_current_collection += len(batch)

            await sql_db.commit()
            logging.info("  Final transaction committed successfully.")
            total_files_saved_across_all_sources += total_saved_current_collection

        except Exception as e:
            await sql_db.rollback()
            logging.error(f"  ❌ An error occurred during migration: {e}. Transaction rolled back.", exc_info=True)

    # Rebuild FTS5 index after bulk import
    try:
        logging.info("Rebuilding FTS5 index after migration...")
        await sql_db.execute("INSERT INTO media_fts(media_fts) VALUES('rebuild');")
        await sql_db.commit()
        logging.info("FTS5 index rebuild complete.")
    except Exception as e:
        logging.warning(f"Post-migration FTS rebuild warning: {e}")

    logging.info(f"\n✨ Overall Migration Summary: {total_files_saved_across_all_sources} files saved across all specified sources.")


# --- Persistent HTTP Session for External Lookups ---
_EXTERNAL_HTTP_SESSION: Optional[aiohttp.ClientSession] = None
_HTTP_LOCK = asyncio.Lock()

async def get_http_session() -> aiohttp.ClientSession:
    global _EXTERNAL_HTTP_SESSION
    if _EXTERNAL_HTTP_SESSION is None or _EXTERNAL_HTTP_SESSION.closed:
        async with _HTTP_LOCK:
            if _EXTERNAL_HTTP_SESSION is None or _EXTERNAL_HTTP_SESSION.closed:
                timeout = aiohttp.ClientTimeout(total=2.0, connect=1.0)
                _EXTERNAL_HTTP_SESSION = aiohttp.ClientSession(timeout=timeout)
    return _EXTERNAL_HTTP_SESSION

async def close_http_session():
    global _EXTERNAL_HTTP_SESSION
    if _EXTERNAL_HTTP_SESSION is not None and not _EXTERNAL_HTTP_SESSION.closed:
        try:
            await _EXTERNAL_HTTP_SESSION.close()
        except Exception:
            pass
        _EXTERNAL_HTTP_SESSION = None

async def fetch_imdb_titles(search_query: str) -> List[str]:
    if not search_query or len(search_query.strip()) < 2:
        return []
    clean_q = re.sub(r'[^a-zA-Z0-9]+', '', search_query.strip().lower())
    if not clean_q:
        return []

    cached = IMDB_CACHE.get(clean_q)
    if cached is not None:
        return cached

    url_imdb = f"https://v3.sg.media-imdb.com/suggestion/x/{clean_q}.json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        session = await get_http_session()
        async with session.get(url_imdb, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("d", [])
                titles = [item.get("l") for item in items if item.get("l")]
                if titles:
                    IMDB_CACHE.set(clean_q, titles)
                    return titles
    except Exception as e:
        logger.debug(f"IMDb suggestion fetch exception for '{search_query}': {e}")

    try:
        url_omdb = f"https://www.omdbapi.com/?s={clean_q}&apikey=32906d20"
        session = await get_http_session()
        async with session.get(url_omdb) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("Response") == "True":
                    items = data.get("Search", [])
                    titles = [item.get("Title") for item in items if item.get("Title")]
                    IMDB_CACHE.set(clean_q, titles)
                    return titles
    except Exception as e:
        logger.debug(f"OMDb fallback exception for '{search_query}': {e}")

    IMDB_CACHE.set(clean_q, [])
    return []


def compute_accuracy_score(query: str, title: str) -> float:
    q_raw = query.strip().lower()
    t_raw = title.strip().lower()
    if not q_raw or not t_raw:
        return 0.0

    q_norm = re.sub(r'[^a-z0-9]+', ' ', q_raw).strip()
    t_norm = re.sub(r'[^a-z0-9]+', ' ', t_raw).strip()

    if q_norm == t_norm:
        return 1.0

    q_words = [w for w in q_norm.split() if len(w) >= 2]
    t_words = [w for w in t_norm.split() if len(w) >= 2]
    q_set, t_set = set(q_words), set(t_words)

    if q_set and q_set == t_set:
        return 1.0
    if q_set and q_set.issubset(t_set):
        return 0.95

    q_compact = re.sub(r'[^a-z0-9]+', '', q_raw)
    t_compact = re.sub(r'[^a-z0-9]+', '', t_raw)
    if q_compact and q_compact == t_compact:
        return 1.0
    if q_compact and len(q_compact) >= 4 and q_compact in t_compact:
        return 0.90

    len_diff = abs(len(q_norm) - len(t_norm))
    max_len = max(len(q_norm), len(t_norm))
    if max_len > 0 and len_diff / float(max_len) > 0.6 and not (q_set & t_set):
        return 0.20

    seq_ratio = difflib.SequenceMatcher(None, q_norm, t_norm).ratio()
    compact_ratio = difflib.SequenceMatcher(None, q_compact, t_compact).ratio()

    if not q_words or not t_words:
        return max(seq_ratio, compact_ratio)

    word_scores = []
    for qw in q_words:
        best_w_score = 0.0
        for tw in t_words:
            if qw == tw:
                best_w_score = 1.0
                break
            w_ratio = difflib.SequenceMatcher(None, qw, tw).ratio()
            if w_ratio > best_w_score:
                best_w_score = w_ratio
        word_scores.append(best_w_score)

    avg_word_score = sum(word_scores) / len(word_scores) if word_scores else 0.0

    intersection = q_set & t_set
    union = q_set | t_set
    jaccard_ratio = len(intersection) / float(len(union)) if union else 0.0

    compact_boost = 0.15 if (q_compact in t_compact or t_compact in q_compact) else 0.0
    contained_boost = 0.15 if (q_set and q_set.issubset(t_set)) else 0.0

    final_score = max(seq_ratio, compact_ratio, avg_word_score, jaccard_ratio) + max(compact_boost, contained_boost)
    return min(1.0, final_score)


# --- Core Search Engine Pipeline ---
async def _execute_search_internal(search_query: str, offset: int = 0) -> Tuple[List[dict], int, Dict[str, Any]]:
    """Internal search executor performing FTS5 trigram queries and collecting stage metrics."""
    t_stage_start = time.perf_counter()
    metrics = {
        "cache_lookup_ms": 0.0,
        "conn_wait_ms": 0.0,
        "lock_wait_ms": 0.0,
        "sql_exec_ms": 0.0,
        "sql_fetch_ms": 0.0,
        "spellcheck_ms": 0.0,
        "fuzzy_ms": 0.0,
        "result_build_ms": 0.0,
        "total_db_stage_ms": 0.0,
        "row_count": 0,
        "strategy": "none"
    }

    clean_search = re.sub(r'[\._\-\[\(\]\)]+', ' ', search_query.strip())
    clean_search = re.sub(r'\s+', ' ', clean_search).strip()
    if not clean_search:
        metrics["total_db_stage_ms"] = (time.perf_counter() - t_stage_start) * 1000
        return [], 0, metrics

    await ensure_aiosqlite_connection()
    pool = _DB_POOL

    search_terms = clean_search.split()
    meaningful_terms = [t for t in search_terms if t.lower() not in GENERIC_STOPWORDS and len(t) >= 2]
    terms_to_use = meaningful_terms if meaningful_terms else search_terms

    # 1. Primary FTS5 Trigram MATCH (Boolean AND)
    fts_terms = [f'"{term}"' for term in terms_to_use if len(term) >= 2]
    rows = []
    fts_attempted_and_ok = False
    if fts_terms and pool:
        fts_expr = " AND ".join(fts_terms)
        query = """
            SELECT m.file_id, m.file_name, m.size
            FROM media_fts f
            JOIN media m ON f.rowid = m.rowid
            WHERE media_fts MATCH ?
            ORDER BY m.date_saved DESC
            LIMIT ? OFFSET ?
        """
        try:
            rows, read_m = await pool.execute_read(query, (fts_expr, MAX_FILES + 1, offset))
            metrics["conn_wait_ms"] += read_m["conn_wait_ms"]
            metrics["sql_exec_ms"] += read_m["sql_exec_ms"]
            metrics["sql_fetch_ms"] += read_m["sql_fetch_ms"]
            metrics["strategy"] = "fts_and"
            fts_attempted_and_ok = True
        except Exception as e:
            logger.debug(f"FTS5 primary query fallback: {e}")
            rows = []
            fts_attempted_and_ok = False

    # Fallback to indexed LIKE ONLY if FTS was NOT available or threw an error
    if not rows and not fts_attempted_and_ok and pool:
        where_clauses = []
        params = []
        for term in terms_to_use[:4]:
            where_clauses.append("(file_name LIKE ? OR caption LIKE ?)")
            params.extend([f"%{term}%", f"%{term}%"])

        if where_clauses:
            where_statement = " AND ".join(where_clauses)
            query = f"""
                SELECT file_id, file_name, size
                FROM media
                WHERE {where_statement}
                ORDER BY date_saved DESC
                LIMIT ? OFFSET ?
            """
            params.extend([MAX_FILES + 1, offset])
            try:
                rows, read_m = await pool.execute_read(query, tuple(params))
                metrics["conn_wait_ms"] += read_m["conn_wait_ms"]
                metrics["sql_exec_ms"] += read_m["sql_exec_ms"]
                metrics["sql_fetch_ms"] += read_m["sql_fetch_ms"]
                metrics["strategy"] = "like_and"
            except Exception as e:
                logger.error(f"LIKE search error: {e}")
                rows = []

    if rows:
        t_rb = time.perf_counter()
        scored_files = []
        for row in rows:
            accuracy = compute_accuracy_score(clean_search, clean_file_name_for_title(row[1]))
            scored_files.append({"file_id": row[0], "file_name": row[1], "size": row[2], "accuracy": accuracy})
        scored_files.sort(key=lambda x: x["accuracy"], reverse=True)
        files = [{"file_id": f["file_id"], "file_name": f["file_name"], "size": f["size"]} for f in scored_files]
        metrics["result_build_ms"] = (time.perf_counter() - t_rb) * 1000
        metrics["row_count"] = len(files)
        metrics["total_db_stage_ms"] = (time.perf_counter() - t_stage_start) * 1000
        return files, offset + len(files), metrics

    # 2. Secondary Search: Fuzzy OR Candidate Search via FTS5 / LIKE
    if offset == 0 and len(clean_search) >= 3 and pool:
        t_fuzzy = time.perf_counter()
        raw_words = terms_to_use[:3]
        fuzzy_rows = []
        if raw_words:
            # Try FTS OR first
            fts_or_terms = [f'"{w}"' for w in raw_words if len(w) >= 2]
            if fts_or_terms:
                fts_or_expr = " OR ".join(fts_or_terms)
                fuzzy_fts_query = """
                    SELECT m.file_id, m.file_name, m.size
                    FROM media_fts f
                    JOIN media m ON f.rowid = m.rowid
                    WHERE media_fts MATCH ?
                    ORDER BY m.date_saved DESC
                    LIMIT 60
                """
                try:
                    fuzzy_rows, read_m = await pool.execute_read(fuzzy_fts_query, (fts_or_expr,))
                    metrics["conn_wait_ms"] += read_m["conn_wait_ms"]
                    metrics["sql_exec_ms"] += read_m["sql_exec_ms"]
                    metrics["sql_fetch_ms"] += read_m["sql_fetch_ms"]
                except Exception:
                    fuzzy_rows = []

            if not fuzzy_rows:
                or_clauses = ["file_name LIKE ?" for _ in raw_words]
                or_params = [f"%{w}%" for w in raw_words]
                or_stmt = " OR ".join(or_clauses)
                fuzzy_query = f"SELECT file_id, file_name, size FROM media WHERE {or_stmt} ORDER BY date_saved DESC LIMIT 50"
                try:
                    fuzzy_rows, read_m = await pool.execute_read(fuzzy_query, tuple(or_params))
                    metrics["conn_wait_ms"] += read_m["conn_wait_ms"]
                    metrics["sql_exec_ms"] += read_m["sql_exec_ms"]
                    metrics["sql_fetch_ms"] += read_m["sql_fetch_ms"]
                except Exception:
                    fuzzy_rows = []

            scored_fuzzy = []
            for row in fuzzy_rows:
                acc = compute_accuracy_score(clean_search, clean_file_name_for_title(row[1]))
                if acc >= 0.80:
                    scored_fuzzy.append((acc, {"file_id": row[0], "file_name": row[1], "size": row[2]}))

            metrics["fuzzy_ms"] = (time.perf_counter() - t_fuzzy) * 1000

            if scored_fuzzy:
                scored_fuzzy.sort(key=lambda x: x[0], reverse=True)
                fuzzy_files = [item[1] for item in scored_fuzzy[:MAX_FILES]]
                metrics["row_count"] = len(fuzzy_files)
                metrics["strategy"] = "fuzzy_or"
                metrics["total_db_stage_ms"] = (time.perf_counter() - t_stage_start) * 1000
                return fuzzy_files, len(fuzzy_files), metrics

    # 3. Tertiary Search: IMDb Correction Fallback
    if offset == 0 and len(clean_search) >= 3:
        t_sp = time.perf_counter()
        try:
            imdb_suggestions = await fetch_imdb_titles(clean_search)
            for title in imdb_suggestions:
                acc = compute_accuracy_score(clean_search, title)
                if acc >= 0.75:
                    c_terms = [t for t in title.strip().split() if len(t) >= 2]
                    c_fts = [f'"{ct}"' for ct in c_terms]
                    c_rows = []
                    if c_fts and pool:
                        c_expr = " AND ".join(c_fts)
                        c_q = "SELECT m.file_id, m.file_name, m.size FROM media_fts f JOIN media m ON f.rowid = m.rowid WHERE media_fts MATCH ? ORDER BY m.date_saved DESC LIMIT ?"
                        try:
                            c_rows, read_m = await pool.execute_read(c_q, (c_expr, MAX_FILES + 1))
                            metrics["conn_wait_ms"] += read_m["conn_wait_ms"]
                            metrics["sql_exec_ms"] += read_m["sql_exec_ms"]
                            metrics["sql_fetch_ms"] += read_m["sql_fetch_ms"]
                        except Exception:
                            c_rows = []
                    if c_rows:
                        corrected_files = [{"file_id": r[0], "file_name": r[1], "size": r[2]} for r in c_rows]
                        metrics["spellcheck_ms"] = (time.perf_counter() - t_sp) * 1000
                        metrics["row_count"] = len(corrected_files)
                        metrics["strategy"] = "imdb_correction"
                        metrics["total_db_stage_ms"] = (time.perf_counter() - t_stage_start) * 1000
                        return corrected_files, len(corrected_files), metrics
        except Exception as e:
            logger.debug(f"IMDb search fallback exception: {e}")
        metrics["spellcheck_ms"] = (time.perf_counter() - t_sp) * 1000

    metrics["total_db_stage_ms"] = (time.perf_counter() - t_stage_start) * 1000
    return [], 0, metrics


async def get_search_results(search_query: str, offset: int = 0) -> Tuple[List[dict], int]:
    """
    Searches the database with LRU caching, anti-stampede deduplication, FTS5 trigram indexing,
    and structured sub-stage tracing.
    """
    t0 = time.perf_counter()
    clean_search = re.sub(r'[\._\-\[\(\]\)]+', ' ', search_query.strip())
    clean_search = re.sub(r'\s+', ' ', clean_search).strip()
    if not clean_search:
        return [], 0

    cache_key = f"{clean_search.lower()}_{offset}"
    
    # 1. Cache lookup
    cached = SEARCH_RESULT_CACHE.get(cache_key)
    if cached is not None:
        cache_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            f"[SEARCH_TRACE] query={clean_search!r} offset={offset} "
            f"cache_lookup_ms={cache_ms:.2f} db_ms=0.00 cache_hit=True rows={len(cached[0])}"
        )
        return cached

    # 2. Anti-Stampede in-flight deduplication
    async with _STAMPEDE_LOCK:
        if cache_key in _IN_FLIGHT_SEARCHES:
            fut = _IN_FLIGHT_SEARCHES[cache_key]
        else:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            _IN_FLIGHT_SEARCHES[cache_key] = fut
            # Schedule task to perform search and resolve future
            asyncio.create_task(_run_and_resolve_search(clean_search, offset, cache_key, fut))

    try:
        files, next_offset = await asyncio.shield(fut)
        return files, next_offset
    except Exception as e:
        logger.error(f"Error in in-flight search for {search_query}: {e}")
        return [], 0


async def _run_and_resolve_search(clean_search: str, offset: int, cache_key: str, future: asyncio.Future):
    try:
        t_db_start = time.perf_counter()
        files, next_offset, metrics = await _execute_search_internal(clean_search, offset)
        res = (files, next_offset)
        SEARCH_RESULT_CACHE.set(cache_key, res)
        
        # Log structured SEARCH_TRACE
        total_stage_ms = (time.perf_counter() - t_db_start) * 1000
        trace_msg = (
            f"[SEARCH_TRACE] query={clean_search!r} offset={offset} "
            f"cache_lookup_ms={metrics['cache_lookup_ms']:.2f} "
            f"db_connection_wait_ms={metrics['conn_wait_ms']:.2f} "
            f"db_lock_wait_ms={metrics['lock_wait_ms']:.2f} "
            f"sql_exec_ms={metrics['sql_exec_ms']:.2f} "
            f"sql_fetch_ms={metrics['sql_fetch_ms']:.2f} "
            f"spellcheck_ms={metrics['spellcheck_ms']:.2f} "
            f"fuzzy_ms={metrics['fuzzy_ms']:.2f} "
            f"result_build_ms={metrics['result_build_ms']:.2f} "
            f"total_db_stage_ms={total_stage_ms:.2f} "
            f"strategy={metrics['strategy']} rows={len(files)}"
        )
        if total_stage_ms > 1000:
            logger.warning(
                f"[SEARCH_DB_WAIT] operation=get_search_results "
                f"connection_wait_ms={metrics['conn_wait_ms']:.2f} "
                f"lock_wait_ms={metrics['lock_wait_ms']:.2f} "
                f"execution_ms={metrics['sql_exec_ms']:.2f} "
                f"total_ms={total_stage_ms:.2f} rows={len(files)} query={clean_search!r}"
            )
            logger.warning(trace_msg)
        else:
            logger.info(trace_msg)

        if not future.done():
            future.set_result(res)
    except Exception as e:
        logger.exception(f"Exception during search resolution: {e}")
        if not future.done():
            future.set_exception(e)
    finally:
        async with _STAMPEDE_LOCK:
            _IN_FLIGHT_SEARCHES.pop(cache_key, None)


# --- Write Operations (Single-Writer Serialization with ACID Safety) ---
async def save_file_sql(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    caption = getattr(media, 'caption', str(media.file_name))
    date_saved = datetime.datetime.now(pytz.utc)
    original_file_name = caption

    pattern = re.compile(r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)', re.IGNORECASE)
    match = pattern.search(original_file_name)

    if match:
        season = int(match.group(1))
        prefix = f"[S{season:02d} EP{int(match.group(2)):02d}]" if match.group(2) else f"[S{season:02d}]"
        processed_name = f"{prefix} {media.file_name}"
    else:
        processed_name = media.file_name

    file_name = re.sub(r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])", " ", processed_name)

    def _sync_insert(conn):
        try:
            conn.execute(
                """
                INSERT INTO media (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, file_ref, file_name, media.file_size, get_size(media.file_size), media.file_type, media.mime_type, caption, date_saved)
            )
            return True, 1
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                return False, 0
            raise e

    try:
        await ensure_aiosqlite_connection()
        res, metrics = await _DB_POOL.execute_write(_sync_insert)
        return res
    except Exception as e:
        logger.exception(f"Unexpected error saving file '{file_name}': {e}")
        return False, 2


async def save_files_sql_batch(media_list: list) -> tuple:
    if not media_list:
        return 0, 0, 0
    data_to_insert = []
    date_saved = datetime.datetime.now(pytz.utc)
    for media in media_list:
        file_id, file_ref = unpack_new_file_id(media.file_id)
        caption = getattr(media, 'caption', str(media.file_name))
        original_file_name = caption

        pattern = re.compile(r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)', re.IGNORECASE)
        match = pattern.search(original_file_name)

        if match:
            season = int(match.group(1))
            prefix = f"[S{season:02d} EP{int(match.group(2)):02d}]" if match.group(2) else f"[S{season:02d}]"
            processed_name = f"{prefix} {media.file_name}"
        else:
            processed_name = media.file_name
        file_name = re.sub(r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])", " ", processed_name)
        data_to_insert.append((
            file_id, file_ref, file_name, media.file_size, get_size(media.file_size),
            media.file_type, media.mime_type, caption, date_saved
        ))

    def _sync_batch(conn):
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO media (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            data_to_insert
        )
        saved = cur.rowcount if cur.rowcount >= 0 else len(data_to_insert)
        dups = len(data_to_insert) - saved
        return saved, dups, 0

    try:
        await ensure_aiosqlite_connection()
        (saved, dups, errs), metrics = await _DB_POOL.execute_write(_sync_batch)
        return saved, dups, errs
    except Exception as e:
        logger.error(f"Error in batch saving to SQLite DB: {e}", exc_info=True)
        return 0, 0, len(data_to_insert)


async def delete_file_sql(file_id: str) -> bool:
    def _sync_del(conn):
        cur = conn.execute("DELETE FROM media WHERE file_id = ?", (file_id,))
        return cur.rowcount > 0

    try:
        await ensure_aiosqlite_connection()
        res, _ = await _DB_POOL.execute_write(_sync_del)
        return res
    except Exception as e:
        logging.error(f"Error deleting file '{file_id}': {e}", exc_info=True)
        return False


async def delete_all_files_sql() -> Tuple[bool, int]:
    def _sync_del_all(conn):
        cur = conn.execute("SELECT COUNT(*) FROM media")
        count = cur.fetchone()[0]
        if count == 0:
            return True, 0
        conn.execute("DELETE FROM media")
        try:
            conn.execute("INSERT INTO media_fts(media_fts) VALUES('rebuild');")
        except Exception:
            pass
        return True, count

    try:
        await ensure_aiosqlite_connection()
        (status, total), _ = await _DB_POOL.execute_write(_sync_del_all)
        return status, total
    except Exception as e:
        logging.exception(f"Error deleting all files from database: {e}")
        return False, 0


def clean_file_name_for_title(file_name: str) -> str:
    return QueryNormalizer.clean_release_name(file_name)


async def get_suggestions_sql(search_query: str, limit: int = 5, min_accuracy: float = 0.80) -> List[str]:
    """Generates high-precision spell check suggestions using FTS5 trigram indexing and SearchEngine."""
    if not search_query or len(search_query.strip()) < 2:
        return []

    cache_key = search_query.strip().lower()
    cached = SUGGESTION_CACHE.get(cache_key)
    if cached is not None:
        return cached

    t0 = time.perf_counter()
    try:
        await ensure_aiosqlite_connection()
        top_suggestions = await SearchEngine.get_suggestions_sql(_DB_POOL, search_query, limit=limit)
    except Exception as e:
        logger.error(f"Error generating suggestions with SearchEngine: {e}")
        top_suggestions = []

    dur_ms = (time.perf_counter() - t0) * 1000
    if dur_ms > 500:
        logger.warning(
            f"[SEARCH_DB_WAIT] operation=get_suggestions_sql "
            f"execution_ms={dur_ms:.2f} rows={len(top_suggestions)} query={search_query!r}"
        )

    SUGGESTION_CACHE.set(cache_key, top_suggestions)
    return top_suggestions
