import asyncio
import logging
import aiosqlite
import datetime
import pytz
import re
import difflib
import aiohttp
from collections import defaultdict
from typing import Tuple, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from info import DATABASE_URI2, DATABASE_NAME, DATABASE_URI3, COLLECTION_NAME, MAX_FILES, BOT_TOKEN
from database.ia_filterdb import unpack_new_file_id
from utils import get_size

# --- Configuration ---
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Optimization: Increased batch size for fewer DB calls
BATCH_SIZE = 10000
PROGRESS_STEP = 50000
SUPER_BATCH_SIZE = 100000  # Commit every 100,000 files to prevent single massive transaction

# --- Database Clients ---
SQLITE_DB = f"media_{BOT_TOKEN}.sqlite3"

client2 = AsyncIOMotorClient(DATABASE_URI2)
db2 = client2[DATABASE_NAME]

client3 = AsyncIOMotorClient(DATABASE_URI3)
db3 = client3[DATABASE_NAME]

COLLECTIONS_TO_MIGRATE = [
    {"db": db3, "collection_name": COLLECTION_NAME},
    {"db": db2, "collection_name": COLLECTION_NAME},
]

# --- Global SQLite Connection Manager ---
_global_aiosqlite_connection: Optional[aiosqlite.Connection] = None
_connection_lock = asyncio.Lock()

async def init_aiosqlite_connection(db_path: str):
    """Initializes a single, reusable aiosqlite connection."""
    global _global_aiosqlite_connection
    async with _connection_lock:
        if _global_aiosqlite_connection is None:
            _global_aiosqlite_connection = await aiosqlite.connect(db_path)
            await _global_aiosqlite_connection.execute("PRAGMA foreign_keys = ON;")
            logging.info(f"aiosqlite connection opened to {db_path}")
        return _global_aiosqlite_connection

async def close_aiosqlite_connection():
    """Closes the global aiosqlite connection."""
    global _global_aiosqlite_connection
    async with _connection_lock:
        if _global_aiosqlite_connection:
            await _global_aiosqlite_connection.close()
            _global_aiosqlite_connection = None
            logging.info("aiosqlite connection closed.")

def get_aiosqlite_connection() -> aiosqlite.Connection:
    """Gets the initialized aiosqlite connection, raising an error if not connected."""
    if _global_aiosqlite_connection is None:
        raise RuntimeError("aiosqlite connection is not initialized. Call init_aiosqlite_connection first.")
    return _global_aiosqlite_connection

# --- Helper Functions ---
async def check_table_exists(table_name: str) -> bool:
    """Checks if a table exists in the SQLite database."""
    db = get_aiosqlite_connection()
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ) as cursor:
        return await cursor.fetchone() is not None

async def check_data_exists(table_name: str) -> bool:
    """Checks if a table contains any data."""
    db = get_aiosqlite_connection()
    async with db.execute(f"SELECT 1 FROM {table_name} LIMIT 1") as cursor:
        return await cursor.fetchone() is not None

# --- High-Speed Migration Functions ---

async def set_sqlite_pragmas(db: aiosqlite.Connection):
    """Sets optimal PRAGMA settings for fast bulk inserts."""
    # Use WAL mode and reduced sync for maximal write throughput during migration
    await db.execute("PRAGMA journal_mode = WAL;")
    await db.execute("PRAGMA synchronous = NORMAL;")
    await db.execute("PRAGMA locking_mode = EXCLUSIVE;")
    await db.commit()
    logging.info("🚀 Set fast PRAGMA settings for SQLite.")

async def insert_batch_no_commit(db, batch):
    """Inserts a batch of data without committing, for use within a transaction."""
    await db.executemany("""
        INSERT OR REPLACE INTO media (
            file_id, file_ref, file_name, file_size, size,
            file_type, mime_type, caption, date_saved
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch)

async def migrate_to_sql():
    """
    Performs a high-speed migration from MongoDB to SQLite.
    Uses batching, a single transaction per collection (broken up by SUPER_BATCH_SIZE),
    and optimal PRAGMA settings.
    """
    logging.info("🚀 Starting multi-database migration with high-speed optimizations...")
    await init_aiosqlite_connection(SQLITE_DB)
    sql_db = get_aiosqlite_connection()

    # Create table if it doesn't exist
    await sql_db.execute("""
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
    await sql_db.execute("CREATE INDEX IF NOT EXISTS idx_date_saved ON media (date_saved);")
    await sql_db.commit()

    # Apply performance settings for the migration
    await set_sqlite_pragmas(sql_db)

    data_exists_in_table = await check_data_exists("media")
    if data_exists_in_table:
        logging.warning("Migration note: Data already exists. New/updated columns may not be populated for old records.")
    else:
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

        # --- Begin a single transaction for the current batch ---
        await sql_db.execute("BEGIN;")
        logging.info("  Transaction started.")

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
                    
                    # --- Intermittent Commit Logic for huge collections ---
                    if total_saved_current_collection % SUPER_BATCH_SIZE == 0:
                        await sql_db.commit() # Commit the current transaction
                        await sql_db.execute("BEGIN;") # Start a new transaction
                        logging.info(f"    ...SUPER-BATCH inserted and committed: {total_saved_current_collection} / {doc_count} files")
                    # --- Regular Progress Update ---
                    elif total_saved_current_collection % PROGRESS_STEP == 0:
                        logging.info(f"    ...batch inserted: {total_saved_current_collection} / {doc_count} files")
            
            # Insert the final, smaller batch if it exists
            if batch:
                await insert_batch_no_commit(sql_db, batch)
                total_saved_current_collection += len(batch)
            
            # --- Commit the final transaction for the collection ---
            await sql_db.commit()
            logging.info("  Final transaction committed successfully.")

            logging.info(f"✅ Migration completed for '{current_collection_name}': {total_saved_current_collection} files saved.")
            total_files_saved_across_all_sources += total_saved_current_collection

        except Exception as e:
            await sql_db.rollback() # Rollback on error to maintain data integrity
            logging.error(f"  ❌ An error occurred during migration: {e}. Transaction has been rolled back.", exc_info=True)

    logging.info(f"\n✨ Overall Migration Summary: {total_files_saved_across_all_sources} files saved across all specified sources.")


# --- Regular Bot Operation Functions ---

async def fetch_imdb_titles(search_query: str) -> List[str]:
    """Fetches movie title candidates from IMDb suggestion API with OMDb fallback."""
    if not search_query or len(search_query.strip()) < 2:
        return []
    clean_q = re.sub(r'[^a-zA-Z0-9]+', '', search_query.strip().lower())
    if not clean_q:
        return []

    url_imdb = f"https://v3.sg.media-imdb.com/suggestion/x/{clean_q}.json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url_imdb, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("d", [])
                    titles = [item.get("l") for item in items if item.get("l")]
                    if titles:
                        return titles
    except Exception as e:
        logger.debug(f"IMDb v3 suggestion fetch exception for '{search_query}': {e}")

    try:
        url_omdb = f"https://www.omdbapi.com/?s={clean_q}&apikey=32906d20"
        async with aiohttp.ClientSession() as session:
            async with session.get(url_omdb, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("Response") == "True":
                        items = data.get("Search", [])
                        return [item.get("Title") for item in items if item.get("Title")]
    except Exception as e:
        logger.debug(f"OMDb fallback exception for '{search_query}': {e}")

    return []

def compute_accuracy_score(query: str, title: str) -> float:
    """Computes similarity / accuracy score between search query and title (0.0 to 1.0)."""
    q_raw = query.strip().lower()
    t_raw = title.strip().lower()
    if not q_raw or not t_raw:
        return 0.0

    q_norm = re.sub(r'[^a-z0-9]+', ' ', q_raw).strip()
    t_norm = re.sub(r'[^a-z0-9]+', ' ', t_raw).strip()

    if q_norm == t_norm:
        return 1.0

    q_compact = re.sub(r'[^a-z0-9]+', '', q_raw)
    t_compact = re.sub(r'[^a-z0-9]+', '', t_raw)

    seq_ratio = difflib.SequenceMatcher(None, q_norm, t_norm).ratio()
    compact_ratio = difflib.SequenceMatcher(None, q_compact, t_compact).ratio()

    q_words = [w for w in re.findall(r'\w+', q_norm) if len(w) >= 2]
    t_words = [w for w in re.findall(r'\w+', t_norm) if len(w) >= 2]

    if not q_words or not t_words:
        return max(seq_ratio, compact_ratio)

    word_scores = []
    for qw in q_words:
        best_w_score = 0.0
        for tw in t_words:
            w_ratio = difflib.SequenceMatcher(None, qw, tw).ratio()
            if w_ratio > best_w_score:
                best_w_score = w_ratio
        word_scores.append(best_w_score)

    avg_word_score = sum(word_scores) / len(word_scores) if word_scores else 0.0

    q_set, t_set = set(q_words), set(t_words)
    intersection = q_set & t_set
    union = q_set | t_set
    jaccard_ratio = len(intersection) / float(len(union)) if union else 0.0

    compact_boost = 0.15 if (q_compact in t_compact or t_compact in q_compact) else 0.0
    query_contained = q_set.issubset(t_set) if q_set else False
    contained_boost = 0.15 if query_contained else 0.0

    final_score = max(seq_ratio, compact_ratio, avg_word_score, jaccard_ratio) + max(compact_boost, contained_boost)
    return min(1.0, final_score)

async def get_search_results(search_query: str, offset: int = 0) -> Tuple[List[dict], int]:
    """
    Searches the SQLite database for files matching the query with 80% accuracy matching,
    fuzzy candidate fallback, and IMDb spell-check correction integration.
    """
    db = get_aiosqlite_connection()
    search_terms = search_query.strip().split()
    if not search_terms:
        return [], 0

    # 1. Primary Search: Exact SQL LIKE query with AND
    where_clauses = []
    params = []
    for term in search_terms:
        where_clauses.append("(file_name LIKE ? OR caption LIKE ?)")
        params.extend([f"%{term}%", f"%{term}%"])

    where_statement = " AND ".join(where_clauses)
    query = f"""
        SELECT file_id, file_name, size
        FROM media
        WHERE {where_statement}
        ORDER BY date_saved DESC
        LIMIT ? OFFSET ?
    """
    params.extend([MAX_FILES + 1, offset])

    async with db.execute(query, tuple(params)) as cursor:
        rows = await cursor.fetchall()

    if rows:
        scored_files = []
        for row in rows:
            accuracy = compute_accuracy_score(search_query, clean_file_name_for_title(row[1]))
            scored_files.append({"file_id": row[0], "file_name": row[1], "size": row[2], "accuracy": accuracy})
        scored_files.sort(key=lambda x: x["accuracy"], reverse=True)
        files = [{"file_id": f["file_id"], "file_name": f["file_name"], "size": f["size"]} for f in scored_files]
        return files, offset + len(files)

    # 2. Secondary Search: Fuzzy OR Candidate Search with 80% Accuracy Threshold
    if offset == 0 and len(search_query.strip()) >= 3:
        raw_words = [w for w in re.findall(r'\w+', search_query.lower()) if len(w) >= 2]
        if raw_words:
            or_clauses = []
            or_params = []
            for w in raw_words:
                or_clauses.append("file_name LIKE ?")
                or_params.append(f"%{w}%")

            or_stmt = " OR ".join(or_clauses)
            fuzzy_query = f"""
                SELECT file_id, file_name, size
                FROM media
                WHERE {or_stmt}
                ORDER BY date_saved DESC
                LIMIT 500
            """
            async with db.execute(fuzzy_query, tuple(or_params)) as cursor:
                fuzzy_rows = await cursor.fetchall()

            scored_fuzzy = []
            for row in fuzzy_rows:
                acc = compute_accuracy_score(search_query, clean_file_name_for_title(row[1]))
                if acc >= 0.80:  # 80% Accuracy Filter
                    scored_fuzzy.append((acc, {"file_id": row[0], "file_name": row[1], "size": row[2]}))

            if scored_fuzzy:
                scored_fuzzy.sort(key=lambda x: x[0], reverse=True)
                fuzzy_files = [item[1] for item in scored_fuzzy[:MAX_FILES]]
                return fuzzy_files, len(fuzzy_files)

    # 3. Tertiary Search: IMDb Correction Lookup Fallback
    if offset == 0 and len(search_query.strip()) >= 3:
        try:
            imdb_suggestions = await fetch_imdb_titles(search_query)
            for title in imdb_suggestions:
                acc = compute_accuracy_score(search_query, title)
                if acc >= 0.75:  # High IMDb match confidence
                    corrected_terms = title.strip().split()
                    c_where = []
                    c_params = []
                    for ct in corrected_terms:
                        c_where.append("(file_name LIKE ? OR caption LIKE ?)")
                        c_params.extend([f"%{ct}%", f"%{ct}%"])
                    c_stmt = " AND ".join(c_where)
                    c_query = f"SELECT file_id, file_name, size FROM media WHERE {c_stmt} ORDER BY date_saved DESC LIMIT ?"
                    c_params.append(MAX_FILES + 1)

                    async with db.execute(c_query, tuple(c_params)) as cursor:
                        c_rows = await cursor.fetchall()
                    if c_rows:
                        corrected_files = [{"file_id": r[0], "file_name": r[1], "size": r[2]} for r in c_rows]
                        return corrected_files, len(corrected_files)
        except Exception as e:
            logger.debug(f"IMDb search fallback exception: {e}")

    return [], 0


async def save_file_sql(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    caption = getattr(media, 'caption', str(media.file_name))
    date_saved = datetime.datetime.now(pytz.utc)
    original_file_name = caption

    pattern = re.compile(r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',re.IGNORECASE)
    match = pattern.search(original_file_name)

    if match:
        season = int(match.group(1))
        if match.group(2):
            episode = int(match.group(2))
            prefix = f"[S{season:02d} EP{episode:02d}]"
        else:
            prefix = f"[S{season:02d}]"

        cleaned_name = pattern.sub('', original_file_name).strip()
        cleaned_name = re.sub(r'[\s._-]+', ' ', cleaned_name).strip()
        cleaned_name = re.sub(r'\s{2,}', ' ', cleaned_name)
        processed_name = f"{prefix} {media.file_name}"
    else:
        processed_name = media.file_name
    file_name = re.sub(r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])", " ", processed_name)
    try:
        db = get_aiosqlite_connection()
        await db.execute(
            """
            INSERT INTO media (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                file_ref,
                file_name,
                media.file_size,
                get_size(media.file_size),
                media.file_type,
                media.mime_type,
                caption,
                date_saved
            ),
        )
        await db.commit()
        return True, 1
    except aiosqlite.IntegrityError as e:
        if "UNIQUE constraint failed: media.file_id" in str(e):
            return False, 0
        else:
            logger.exception(f"Error occurred while saving file '{file_name}': {e}")
            return False, 2
    except Exception as e:
        logger.exception(f"Unexpected error occurred while saving file '{file_name}': {e}")
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

        pattern = re.compile(r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',re.IGNORECASE)
        match = pattern.search(original_file_name)

        if match:
            season = int(match.group(1))
            if match.group(2):
                episode = int(match.group(2))
                prefix = f"[S{season:02d} EP{episode:02d}]"
            else:
                prefix = f"[S{season:02d}]"

            cleaned_name = pattern.sub('', original_file_name).strip()
            cleaned_name = re.sub(r'[\s._-]+', ' ', cleaned_name).strip()
            cleaned_name = re.sub(r'\s{2,}', ' ', cleaned_name)
            processed_name = f"{prefix} {media.file_name}"
        else:
            processed_name = media.file_name
        file_name = re.sub(r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])", " ", processed_name)
        data_to_insert.append((
            file_id,
            file_ref,
            file_name,
            media.file_size,
            get_size(media.file_size),
            media.file_type,
            media.mime_type,
            caption,
            date_saved
        ))
    saved_count = 0
    duplicate_count = 0
    error_count = 0
    try:
        db = get_aiosqlite_connection()
        cursor = await db.executemany(
            """
            INSERT OR IGNORE INTO media (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            data_to_insert,
        )
        await db.commit()
        saved_count = cursor.rowcount
        duplicate_count = len(data_to_insert) - saved_count
    except Exception as e:
        logger.error(f"Error in batch saving to SQLite DB: {e}", exc_info=True)
        error_count = len(data_to_insert)
        saved_count = 0
        duplicate_count = 0
    return saved_count, duplicate_count, error_count


async def delete_file_sql(file_id: str) -> bool:
    """Deletes a single file record from the SQLite database."""
    try:
        db = get_aiosqlite_connection()
        await db.execute("DELETE FROM media WHERE file_id = ?", (file_id,))
        await db.commit()
        return True
    except Exception as e:
        logging.error(f"Error occurred while deleting file with ID '{file_id}': {e}", exc_info=True)
        return False


async def delete_all_files_sql() -> Tuple[bool, int]:
    """Deletes all file records from the SQLite database."""
    try:
        db = get_aiosqlite_connection()
        cursor = await db.execute("SELECT COUNT(*) FROM media")
        count_row = await cursor.fetchone()
        total_files = count_row[0] if count_row else 0
        
        if total_files == 0:
            logging.info("No files to delete, database is already empty.")
            return True, 0
            
        await db.execute("DELETE FROM media")
        await db.commit()
        logging.info(f"All {total_files} files deleted from database.")
        return True, total_files
    except Exception as e:
        logging.exception(f"Error occurred while deleting all files from database: {e}")
        return False, 0


# Memory cache for fast repeated suggestion lookups
SUGGESTION_CACHE = {}
MAX_SUGGESTION_CACHE_SIZE = 1000

def clean_file_name_for_title(file_name: str) -> str:
    """Cleans raw file name into a clean movie/series title."""
    if not file_name:
        return ""
    # Strip file extension
    title = re.sub(r'\.(mkv|mp4|avi|webm|flv|mov|m4v|3gp|zip|rar|tar|gz|7z)$', '', file_name, flags=re.IGNORECASE)
    # Remove Season/Episode tags
    title = re.sub(r'\[?(?:S\d{1,2}|Season\s*\d{1,2})(?:[\s._-]*?(?:EP?\d{1,2}|Episode\s*\d{1,2}))?\]?', '', title, flags=re.IGNORECASE)
    # Remove quality / resolution / codec / year / language tags
    pattern = r'(?i)\b(1080p|720p|480p|360p|2160p|4k|hdr|webrip|web-dl|web|bluray|hdrip|dvdrip|x264|x265|hevc|h264|esub|msub|sub|hindi|malayalam|tamil|telugu|kannada|english|multi|dual|aac|dd5\.1|atmos|19\d\d|20\d\d)\b'
    title = re.sub(pattern, '', title)
    # Remove website / telegram channel tags e.g. @channel
    title = re.sub(r'@[a-zA-Z0-9_]+', '', title)
    # Replace symbols with spaces
    title = re.sub(r'[\._\-\[\(\]\)]+', ' ', title)
    # Remove extra spaces
    title = re.sub(r'\s+', ' ', title).strip()
    return title

async def get_suggestions_sql(search_query: str, limit: int = 8, min_accuracy: float = 0.80) -> List[str]:
    """Generates spell check suggestions from SQLite media table + IMDb with 80% accuracy filter."""
    if not search_query or len(search_query.strip()) < 2:
        return []

    cache_key = search_query.strip().lower()
    if cache_key in SUGGESTION_CACHE:
        return SUGGESTION_CACHE[cache_key]

    raw_words = [w for w in re.findall(r'\w+', search_query.lower()) if len(w) >= 2]
    if not raw_words:
        return []

    # Fetch candidates asynchronously from IMDb and SQLite in parallel
    imdb_task = asyncio.create_task(fetch_imdb_titles(search_query))

    sql_rows = []
    try:
        db = get_aiosqlite_connection()
        where_clauses = []
        params = []
        for word in raw_words:
            where_clauses.append("file_name LIKE ?")
            params.append(f"%{word}%")
            if len(word) >= 4:
                prefix = word[:3]
                where_clauses.append("file_name LIKE ?")
                params.append(f"%{prefix}%")

        where_stmt = " OR ".join(where_clauses)
        query = f"SELECT DISTINCT file_name FROM media WHERE {where_stmt} LIMIT 300"
        async with db.execute(query, tuple(params)) as cursor:
            sql_rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"Error fetching SQLite suggestion candidates: {e}")

    if not sql_rows:
        try:
            db = get_aiosqlite_connection()
            async with db.execute("SELECT DISTINCT file_name FROM media ORDER BY date_saved DESC LIMIT 200") as cursor:
                sql_rows = await cursor.fetchall()
        except Exception:
            sql_rows = []

    imdb_titles = []
    try:
        imdb_titles = await imdb_task
    except Exception as e:
        logger.debug(f"IMDb task error: {e}")

    candidates_map = {}

    # Add IMDb candidates
    for title in imdb_titles:
        if not title or len(title) < 2:
            continue
        score = compute_accuracy_score(search_query, title)
        if score >= min_accuracy or score >= 0.60:
            candidates_map[title] = max(candidates_map.get(title, 0), score)

    # Add SQLite candidates
    for row in sql_rows:
        fn = row[0]
        if not fn:
            continue
        clean_t = clean_file_name_for_title(fn)
        if not clean_t or len(clean_t) < 2:
            continue

        score = compute_accuracy_score(search_query, clean_t)
        if score >= min_accuracy or score >= 0.60:
            candidates_map[clean_t] = max(candidates_map.get(clean_t, 0), score)

    # Filter with min_accuracy (0.80) first
    accurate_candidates = {k: v for k, v in candidates_map.items() if v >= min_accuracy}

    # Fallback to score >= 0.60 if no candidate reaches 80% accuracy threshold
    final_candidates = accurate_candidates if accurate_candidates else candidates_map

    sorted_suggestions = sorted(final_candidates.keys(), key=lambda k: final_candidates[k], reverse=True)
    top_suggestions = sorted_suggestions[:limit]

    if len(SUGGESTION_CACHE) > MAX_SUGGESTION_CACHE_SIZE:
        SUGGESTION_CACHE.clear()
    SUGGESTION_CACHE[cache_key] = top_suggestions

    return top_suggestions

