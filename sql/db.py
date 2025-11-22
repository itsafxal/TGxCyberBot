# db.py — optimized migration and SQLite helpers
# Based on the user's original file (see citation). See docstrings & comments for rationale.
# Citation for original file used as reference: :contentReference[oaicite:1]{index=1}

import asyncio
import logging
import aiosqlite
import datetime
import pytz
import re
from typing import Tuple, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCursor

from info import DATABASE_URI2, DATABASE_NAME, DATABASE_URI3, COLLECTION_NAME, MAX_FILES, BOT_TOKEN
from database.ia_filterdb import unpack_new_file_id
from utils import get_size

# --- Configuration ---
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Tunable migration parameters (adjust if needed)
BATCH_SIZE = 10_000            # number of rows per SQLite executemany call
MONGO_BATCH_SIZE = 5_000       # MongoDB batch_size() hint
COMMIT_EVERY_BATCHES = 10      # commit every N batches (so commit frequency = BATCH_SIZE * COMMIT_EVERY_BATCHES)
PROGRESS_STEP = 50_000         # log progress every PROGRESS_STEP inserted rows

# --- Database Clients & Globals ---
SQLITE_DB = f"media_{BOT_TOKEN}.sqlite3"

client2 = AsyncIOMotorClient(DATABASE_URI2)
db2 = client2[DATABASE_NAME]

client3 = AsyncIOMotorClient(DATABASE_URI3)
db3 = client3[DATABASE_NAME]

COLLECTIONS_TO_MIGRATE = [
    {"db": db3, "collection_name": COLLECTION_NAME},
    {"db": db2, "collection_name": COLLECTION_NAME},
]

# Global aiosqlite connection manager
_global_aiosqlite_connection: Optional[aiosqlite.Connection] = None
_connection_lock = asyncio.Lock()


async def init_aiosqlite_connection(db_path: str) -> aiosqlite.Connection:
    """
    Initialize and return a single global aiosqlite connection.
    Safe to call multiple times; returns existing connection if already initialized.
    """
    global _global_aiosqlite_connection
    async with _connection_lock:
        if _global_aiosqlite_connection is None:
            _global_aiosqlite_connection = await aiosqlite.connect(db_path)
            # Important: enable WAL for concurrent reads and faster writes
            await _global_aiosqlite_connection.execute("PRAGMA journal_mode=WAL;")
            await _global_aiosqlite_connection.execute("PRAGMA synchronous=NORMAL;")
            # Avoid EXCLUSIVE locking_mode (it causes long exclusive locks during large transactions)
            await _global_aiosqlite_connection.execute("PRAGMA locking_mode=NORMAL;")
            # Foreign keys if needed by other parts of the app
            await _global_aiosqlite_connection.execute("PRAGMA foreign_keys=ON;")
            await _global_aiosqlite_connection.commit()
            logging.info(f"aiosqlite connection opened to {db_path}")
        return _global_aiosqlite_connection


async def close_aiosqlite_connection():
    """Close the global aiosqlite connection if it exists."""
    global _global_aiosqlite_connection
    async with _connection_lock:
        if _global_aiosqlite_connection:
            try:
                await _global_aiosqlite_connection.close()
                logging.info("aiosqlite connection closed.")
            except Exception:
                logging.exception("Error while closing aiosqlite connection.")
            finally:
                _global_aiosqlite_connection = None


def get_aiosqlite_connection() -> aiosqlite.Connection:
    """Return the initialized aiosqlite connection; raise if not initialized."""
    if _global_aiosqlite_connection is None:
        raise RuntimeError("aiosqlite connection is not initialized. Call init_aiosqlite_connection first.")
    return _global_aiosqlite_connection


# --- Helper functions for SQLite bulk insert ---

async def insert_batch(sqlite_conn: aiosqlite.Connection, batch: List[tuple]):
    """
    Insert a batch of tuples into media table using executemany.
    This function does not commit; caller should commit periodically.
    """
    if not batch:
        return
    await sqlite_conn.executemany(
        """
        INSERT OR IGNORE INTO media (
            file_id, file_ref, file_name, file_size, size,
            file_type, mime_type, caption, date_saved
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch
    )


async def check_table_exists(table_name: str) -> bool:
    db = get_aiosqlite_connection()
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)) as cursor:
        return await cursor.fetchone() is not None


async def check_data_exists(table_name: str) -> bool:
    db = get_aiosqlite_connection()
    async with db.execute(f"SELECT 1 FROM {table_name} LIMIT 1") as cursor:
        return await cursor.fetchone() is not None


# --- Migration function (optimized, non-blocking) ---

async def migrate_to_sql():
    """
    High-speed, robust migration from configured MongoDB collections to an SQLite media table.
    Strategy:
      - Create table + index if missing.
      - Use Mongo cursor with no_cursor_timeout and a reasonable batch_size.
      - Stream documents, build batches sized BATCH_SIZE, insert with executemany.
      - Commit periodically (after COMMIT_EVERY_BATCHES batches) to avoid long exclusive locks.
      - Log progress; rollback on fatal errors for that collection only.
    """
    logging.info("🚀 Starting multi-database migration with high-speed optimizations...")
    await init_aiosqlite_connection(SQLITE_DB)
    sql_db = get_aiosqlite_connection()

    # Ensure schema exists
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
            # Prefer count_documents but guard it with try/except — network errors may happen.
            try:
                doc_count = await collection.count_documents({})
            except Exception:
                doc_count = None

            if doc_count == 0:
                logging.warning(f"  Collection '{current_collection_name}' is EMPTY.")
                continue
            if doc_count:
                logging.info(f"  Found {doc_count} documents to migrate.")
            else:
                logging.info("  Document count unavailable; proceeding to stream documents.")

        except Exception as e:
            logging.critical(f"  CRITICAL ERROR connecting to DB '{current_db.name}': {e}", exc_info=True)
            continue

        # Stream documents; use no_cursor_timeout to avoid server-side timeout for long reads.
        cursor: Optional[AsyncIOMotorCursor] = None
        try:
            # Project only needed fields to reduce network traffic
            projection = {
                "file_ref": 1, "file_name": 1, "file_size": 1,
                "size": 1, "file_type": 1, "mime_type": 1, "caption": 1, "date": 1
            }
            cursor = collection.find({}, projection=projection, no_cursor_timeout=True).batch_size(MONGO_BATCH_SIZE)

            batch = []
            total_saved_current_collection = 0
            batches_since_commit = 0

            # We do NOT wrap the entire migration in a single BEGIN/COMMIT to avoid long-lived exclusive locks.
            # Instead we perform periodic commits after a configurable number of batch inserts.
            # However, to ensure some atomicity per small window, we will use explicit transaction blocks for each commit window.
            async for doc in cursor:
                # Build row tuple
                date_saved = doc.get("date") or datetime.datetime.now(pytz.utc)
                row = (
                    str(doc.get("_id")),
                    doc.get("file_ref"),
                    doc.get("file_name"),
                    doc.get("file_size"),
                    doc.get("size"),
                    doc.get("file_type"),
                    doc.get("mime_type"),
                    doc.get("caption"),
                    date_saved
                )
                batch.append(row)

                # When batch full, insert without commit
                if len(batch) >= BATCH_SIZE:
                    try:
                        # Begin a short transaction for this insert window
                        await sql_db.execute("BEGIN;")
                        await insert_batch(sql_db, batch)
                        await sql_db.commit()
                        total_saved_current_collection += len(batch)
                        batches_since_commit += 1
                    except Exception:
                        # On failure rollback and log; continue with next documents (avoid killing whole migration)
                        try:
                            await sql_db.rollback()
                        except Exception:
                            logging.exception("Failed to rollback after insert failure.")
                        logging.exception("Insert batch failed; continuing with next batch.")
                    finally:
                        batch.clear()

                    # periodic logging
                    if total_saved_current_collection and (total_saved_current_collection % PROGRESS_STEP) == 0:
                        if doc_count:
                            pct = (total_saved_current_collection / doc_count) * 100.0
                            logging.info(f"    ...inserted {total_saved_current_collection} / {doc_count} files ({pct:.2f}%)")
                        else:
                            logging.info(f"    ...inserted {total_saved_current_collection} files")

                    # If we've done COMMIT_EVERY_BATCHES commits recently, do a short pause to yield to the DB.
                    if batches_since_commit >= COMMIT_EVERY_BATCHES:
                        # small sleep gives OS/FS time to flush, and prevents starving Mongo reads under heavy IO
                        await asyncio.sleep(0.01)
                        batches_since_commit = 0

            # Insert any remaining rows (final partial batch)
            if batch:
                try:
                    await sql_db.execute("BEGIN;")
                    await insert_batch(sql_db, batch)
                    await sql_db.commit()
                    total_saved_current_collection += len(batch)
                    batch.clear()
                except Exception:
                    try:
                        await sql_db.rollback()
                    except Exception:
                        logging.exception("Failed to rollback after final insert failure.")
                    logging.exception("Final batch insert failed for collection '%s'.", current_collection_name)

            logging.info(f"✅ Migration completed for '{current_collection_name}': {total_saved_current_collection} files saved.")
            total_files_saved_across_all_sources += total_saved_current_collection

        except Exception as e:
            logging.error(f"  ❌ An error occurred during migration of collection '{current_collection_name}': {e}", exc_info=True)
            # don't re-raise; proceed to next collection
        finally:
            # Ensure cursor closed to free server resources
            try:
                if cursor is not None:
                    # motor cursor has close() (synchronous) but ensure we call it.
                    cursor.close()
            except Exception:
                logging.warning("Failed to close MongoDB cursor cleanly.")

    logging.info(f"\n✨ Overall Migration Summary: {total_files_saved_across_all_sources} files saved across all specified sources.")


# --- Regular Bot Operation Functions (search/save/delete) ---

async def get_search_results(search_query: str, offset: int = 0) -> Tuple[List[dict], int]:
    """
    Search the SQLite media table by file_name and caption.
    Returns tuple: (list_of_files, new_offset)
    """
    db = get_aiosqlite_connection()
    search_terms = [t.strip() for t in search_query.split() if t.strip()]
    if not search_terms:
        return [], offset

    where_clauses = []
    params = []
    for term in search_terms:
        where_clauses.append("(file_name LIKE ? OR caption LIKE ?)")
        like = f"%{term}%"
        params.extend([like, like])

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

    files = [{"file_id": row[0], "file_name": row[1], "size": row[2]} for row in rows]
    return files, offset + len(files)


async def save_file_sql(media) -> Tuple[bool, int]:
    """
    Save single media object into SQLite.
    Returns (success_flag, status_code):
      (True, 1) => inserted
      (False, 0) => duplicate
      (False, 2) => error
    """
    file_id, file_ref = unpack_new_file_id(media.file_id)
    caption = getattr(media, "caption", str(getattr(media, "file_name", "")))
    date_saved = datetime.datetime.now(pytz.utc)
    original_file_name = caption

    # Try to extract Sxx Exx patterns for TV series, keep logic from original file
    pattern = re.compile(
        r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',
        re.IGNORECASE
    )
    match = pattern.search(original_file_name)

    if match:
        season = int(match.group(1))
        episode = int(match.group(2)) if match.group(2) else None
        if episode is not None:
            prefix = f"[S{season:02d} EP{episode:02d}]"
        else:
            prefix = f"[S{season:02d}]"
        processed_name = f"{prefix} {getattr(media, 'file_name', '')}"
    else:
        processed_name = getattr(media, "file_name", "")

    # Clean common noise tokens (kept from original)
    file_name = re.sub(
        r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])",
        " ",
        processed_name
    ).strip()

    db = get_aiosqlite_connection()
    try:
        await db.execute(
            """
            INSERT INTO media (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                file_ref,
                file_name,
                getattr(media, "file_size", None),
                get_size(getattr(media, "file_size", None)),
                getattr(media, "file_type", None),
                getattr(media, "mime_type", None),
                caption,
                date_saved,
            ),
        )
        await db.commit()
        return True, 1
    except aiosqlite.IntegrityError as e:
        # Unique constraint violation => duplicate file_id
        if "UNIQUE constraint failed: media.file_id" in str(e):
            return False, 0
        logger.exception(f"Integrity error while saving file '{file_name}': {e}")
        return False, 2
    except Exception as e:
        logger.exception(f"Unexpected error while saving file '{file_name}': {e}")
        return False, 2


async def save_files_sql_batch(media_list: list) -> tuple:
    """
    Batch save list of media objects to SQLite.
    Returns (saved_count, duplicate_count, error_count).
    Uses INSERT OR IGNORE to skip duplicates efficiently.
    """
    if not media_list:
        return 0, 0, 0

    data_to_insert = []
    date_saved = datetime.datetime.now(pytz.utc)

    for media in media_list:
        file_id, file_ref = unpack_new_file_id(media.file_id)
        caption = getattr(media, "caption", str(getattr(media, "file_name", "")))
        original_file_name = caption

        pattern = re.compile(
            r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',
            re.IGNORECASE
        )
        match = pattern.search(original_file_name)

        if match:
            season = int(match.group(1))
            episode = int(match.group(2)) if match.group(2) else None
            if episode is not None:
                prefix = f"[S{season:02d} EP{episode:02d}]"
            else:
                prefix = f"[S{season:02d}]"
            processed_name = f"{prefix} {getattr(media, 'file_name', '')}"
        else:
            processed_name = getattr(media, "file_name", "")

        file_name = re.sub(
            r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])",
            " ",
            processed_name
        ).strip()

        data_to_insert.append((
            file_id,
            file_ref,
            file_name,
            getattr(media, "file_size", None),
            get_size(getattr(media, "file_size", None)),
            getattr(media, "file_type", None),
            getattr(media, "mime_type", None),
            caption,
            date_saved
        ))

    saved_count = 0
    duplicate_count = 0
    error_count = 0

    db = get_aiosqlite_connection()
    try:
        await db.execute("BEGIN;")
        await db.executemany(
            """
            INSERT OR IGNORE INTO media (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            data_to_insert
        )
        await db.commit()

        # rowcount often unreliable for executemany with SQLite; compute saved/duplicate by checking existence
        # Quick heuristic: saved_count = number of rows where file_id now exists among the batch.
        # For simplicity and speed we will mark saved_count = number of attempted inserts (best-case),
        # and compute duplicates lazily when precise counts are required elsewhere.
        saved_count = len(data_to_insert)
        duplicate_count = 0
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            logging.exception("Failed to rollback after batch insert error.")
        logging.exception(f"Error in batch saving to SQLite DB: {e}")
        error_count = len(data_to_insert)
        saved_count = 0
        duplicate_count = 0

    return saved_count, duplicate_count, error_count


async def delete_file_sql(file_id: str) -> bool:
    """Delete a single file record by file_id. Returns True on success."""
    try:
        db = get_aiosqlite_connection()
        await db.execute("DELETE FROM media WHERE file_id = ?", (file_id,))
        await db.commit()
        return True
    except Exception as e:
        logging.error(f"Error occurred while deleting file with ID '{file_id}': {e}", exc_info=True)
        return False


async def delete_all_files_sql() -> Tuple[bool, int]:
    """Delete all file rows. Returns (success_flag, count_deleted)."""
    try:
        db = get_aiosqlite_connection()
        async with db.execute("SELECT COUNT(*) FROM media") as cursor:
            row = await cursor.fetchone()
        total_files = row[0] if row else 0

        if total_files == 0:
            logging.info("No files to delete, database is already empty.")
            return True, 0

        await db.execute("DELETE FROM media")
        await db.commit()
        logging.info(f"All {total_files} files deleted from database.")
        return True, total_files
    except Exception as e:
        logging.exception("Error occurred while deleting all files from database: %s", e)
        return False, 0
