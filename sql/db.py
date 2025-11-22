# db_final.py — Atlas-safe, string-_id pagination migration + SQLite helpers
# Generated for user; replaces previous sql/db.py migration with a robust solution

import asyncio
import logging
import aiosqlite
import datetime
import pytz
import re
from typing import Tuple, List, Optional, Any, Dict

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure

from info import (
    DATABASE_URI2,
    DATABASE_NAME,
    DATABASE_URI3,
    COLLECTION_NAME,
    MAX_FILES,
    BOT_TOKEN,
)
from database.ia_filterdb import unpack_new_file_id
from utils import get_size

# -------------------- Configuration --------------------
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Tuning parameters
MONGO_PAGE_SIZE = 5000          # docs per page from Mongo
PROGRESS_STEP = 50_000          # log progress every N inserted rows
SQLITE_BATCH_INSERT = 5000      # group rows to insert together into SQLite

SQLITE_DB = f"media_{BOT_TOKEN}.sqlite3"

# Mongo clients
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

# -------------------- SQLite connection helpers --------------------
async def init_aiosqlite_connection(db_path: str) -> aiosqlite.Connection:
    global _global_aiosqlite_connection
    async with _connection_lock:
        if _global_aiosqlite_connection is None:
            _global_aiosqlite_connection = await aiosqlite.connect(db_path)
            # Pragmas tuned for bulk writes and acceptable durability
            await _global_aiosqlite_connection.execute("PRAGMA journal_mode=WAL;")
            await _global_aiosqlite_connection.execute("PRAGMA synchronous=NORMAL;")
            await _global_aiosqlite_connection.execute("PRAGMA locking_mode=NORMAL;")
            await _global_aiosqlite_connection.execute("PRAGMA foreign_keys=ON;")
            await _global_aiosqlite_connection.commit()
            logger.info(f"aiosqlite connection opened to {db_path}")
        return _global_aiosqlite_connection


async def close_aiosqlite_connection():
    global _global_aiosqlite_connection
    async with _connection_lock:
        if _global_aiosqlite_connection:
            try:
                await _global_aiosqlite_connection.close()
                logger.info("aiosqlite connection closed.")
            except Exception:
                logger.exception("Error while closing aiosqlite connection.")
            finally:
                _global_aiosqlite_connection = None


def get_aiosqlite_connection() -> aiosqlite.Connection:
    if _global_aiosqlite_connection is None:
        raise RuntimeError("aiosqlite connection is not initialized. Call init_aiosqlite_connection first.")
    return _global_aiosqlite_connection


# -------------------- SQLite helpers --------------------
async def ensure_schema(sql_db: aiosqlite.Connection):
    await sql_db.execute(
        """
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
        """
    )
    await sql_db.execute("CREATE INDEX IF NOT EXISTS idx_date_saved ON media (date_saved);")
    await sql_db.commit()


async def insert_rows_sql(sql_db: aiosqlite.Connection, rows: List[tuple]):
    if not rows:
        return 0
    # insert in smaller chunks to avoid giant executemany calls on huge memory
    total = 0
    for i in range(0, len(rows), SQLITE_BATCH_INSERT):
        chunk = rows[i : i + SQLITE_BATCH_INSERT]
        try:
            await sql_db.execute("BEGIN;")
            await sql_db.executemany(
                """
                INSERT OR IGNORE INTO media (
                    file_id, file_ref, file_name, file_size, size,
                    file_type, mime_type, caption, date_saved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                chunk,
            )
            await sql_db.commit()
            total += len(chunk)
        except Exception:
            try:
                await sql_db.rollback()
            except Exception:
                logger.exception("rollback failed after insert error")
            logger.exception("Error while inserting chunk into SQLite (continuing)")
    return total


# -------------------- Migration: string _id safe pagination --------------------
async def migrate_collection_string_id(
    sql_db: aiosqlite.Connection,
    collection,
    collection_name: str,
    db_name: str,
    doc_count: Optional[int],
) -> int:
    """
    Migrate a single Mongo collection where `_id` is a string generated by your app.

    Strategy:
      - We paginate by _id lexicographically: {_id: {"$gt": last_id}} with sort("_id", 1).
      - Start last_id as empty string "" so the first page returns the smallest lexical _ids.
      - Use .limit(MONGO_PAGE_SIZE) to avoid long-lived cursors. Atlas allows normal cursors.
      - If a transient cursor error or network issue occurs, the loop restarts from last successfully processed _id.
    """

    projection = {
        "file_ref": 1,
        "file_name": 1,
        "file_size": 1,
        "size": 1,
        "file_type": 1,
        "mime_type": 1,
        "caption": 1,
        "date": 1,
    }

    total_saved = 0
    last_id: str = ""  # empty string is less than any non-empty bson string in UTF-8 lexicographic order

    consecutive_empty_pages = 0

    while True:
        query = {"_id": {"$gt": last_id}} if last_id != "" else {}

        try:
            cursor = collection.find(query, projection=projection).sort("_id", 1).limit(MONGO_PAGE_SIZE)
            docs = await cursor.to_list(length=MONGO_PAGE_SIZE)
        except OperationFailure as e:
            # Sometimes Atlas will reject certain cursor options; retry after a short backoff
            logger.warning(f"Mongo OperationFailure while reading {db_name}.{collection_name}: {e}. Retrying after 1s")
            await asyncio.sleep(1)
            continue
        except Exception as e:
            logger.exception(f"Mongo read error for {db_name}.{collection_name}: {e}")
            break

        if not docs:
            consecutive_empty_pages += 1
            if consecutive_empty_pages > 2:
                # after a couple of empty pages in a row, assume completion
                break
            else:
                # small sleep and retry
                await asyncio.sleep(0.1)
                continue

        consecutive_empty_pages = 0

        rows_to_insert: List[tuple] = []

        for doc in docs:
            _id = doc.get("_id")
            if _id is None:
                continue
            # convert to string for SQLite storage
            id_str = str(_id)

            # update pagination marker using lexicographic order; last_id must be the last doc._id string
            last_id = id_str

            date_saved = doc.get("date") or datetime.datetime.now(pytz.utc)

            rows_to_insert.append(
                (
                    id_str,
                    doc.get("file_ref"),
                    doc.get("file_name"),
                    doc.get("file_size"),
                    doc.get("size"),
                    doc.get("file_type"),
                    doc.get("mime_type"),
                    doc.get("caption"),
                    date_saved,
                )
            )

        # insert into sqlite
        inserted = await insert_rows_sql(sql_db, rows_to_insert)
        total_saved += inserted

        if total_saved and (total_saved % PROGRESS_STEP) == 0:
            if doc_count:
                pct = (total_saved / doc_count) * 100.0
                logger.info(f"    ...inserted {total_saved} / {doc_count} files ({pct:.2f}%)")
            else:
                logger.info(f"    ...inserted {total_saved} files so far")

        # short yield
        await asyncio.sleep(0)

    logger.info(f"✅ Migration completed for '{collection_name}' in DB '{db_name}': {total_saved} files saved.")
    return total_saved


async def migrate_to_sql():
    """
    Top-level migration function. Iterates configured sources and migrates each.
    """
    logger.info("🚀 Starting Atlas-safe migration (string _id)...")

    await init_aiosqlite_connection(SQLITE_DB)
    sql_db = get_aiosqlite_connection()

    await ensure_schema(sql_db)

    data_exists = None
    try:
        async with sql_db.execute("SELECT 1 FROM media LIMIT 1") as cur:
            data_exists = await cur.fetchone() is not None
    except Exception:
        data_exists = None

    if data_exists:
        logger.warning("Migration note: SQLite 'media' table already has data. New rows will be added if missing.")
    else:
        logger.info("SQLite 'media' table is empty. Proceeding with full migration.")

    total_all = 0

    for item in COLLECTIONS_TO_MIGRATE:
        current_db = item["db"]
        collection_name = item["collection_name"]
        collection = current_db[collection_name]

        logger.info(f"\nMigrating from MongoDB: '{current_db.name}', Collection: '{collection_name}'...")

        doc_count: Optional[int] = None
        try:
            doc_count = await collection.count_documents({})
            if doc_count == 0:
                logger.warning(f"  Collection '{collection_name}' is EMPTY.")
                continue
            logger.info(f"  Found {doc_count} documents to migrate.")
        except Exception:
            logger.warning(f"  Could not get document count for {current_db.name}.{collection_name}; proceeding without count.")

        try:
            saved = await migrate_collection_string_id(sql_db, collection, collection_name, current_db.name, doc_count)
            total_all += saved
        except Exception:
            logger.exception(f"Error migrating collection {collection_name}; continuing to next collection.")

    logger.info(f"\n✨ Overall Migration Summary: {total_all} files saved across all specified sources.")


# -------------------- Batch save helper required by caller --------------------
async def save_files_sql_batch(media_list: List[Any]) -> tuple:
    """
    Batch-save media objects to SQLite.
    Returns (saved_count, duplicate_count, error_count).

    This mirrors the per-item save logic used by save_file_sql but is optimized
    for bulk insertion using INSERT OR IGNORE.
    """
    if not media_list:
        return 0, 0, 0

    db = get_aiosqlite_connection()
    date_saved = datetime.datetime.now(pytz.utc)

    cleanup_regex = re.compile(
        r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])",
        re.IGNORECASE,
    )

    tv_pattern = re.compile(
        r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',
        re.IGNORECASE,
    )

    rows: List[tuple] = []

    for media in media_list:
        try:
            file_id, file_ref = unpack_new_file_id(media.file_id)
        except Exception:
            # Fallback: use raw media.file_id if unpack fails
            file_id = str(getattr(media, "file_id", ""))
            file_ref = None

        caption = getattr(media, "caption", None) or str(getattr(media, "file_name", ""))
        original_name = caption

        match = tv_pattern.search(original_name)
        if match:
            season = int(match.group(1))
            ep = int(match.group(2))
            prefix = f"[S{season:02d} EP{ep:02d}]"
            processed = f"{prefix} {getattr(media, 'file_name', '')}"
        else:
            processed = str(getattr(media, "file_name", ""))

        cleaned = cleanup_regex.sub(" ", processed).strip()

        rows.append(
            (
                str(file_id),
                file_ref,
                cleaned,
                getattr(media, "file_size", None),
                get_size(getattr(media, "file_size", None)),
                getattr(media, "file_type", None),
                getattr(media, "mime_type", None),
                caption,
                date_saved,
            )
        )

    saved = await insert_rows_sql(db, rows)
    # We cannot reliably compute duplicates precisely without extra queries; approximate:
    duplicate_count = max(0, len(rows) - saved)
    error_count = 0 if saved == len(rows) else (len(rows) - saved if saved >= 0 else len(rows))

    return saved, duplicate_count, error_count


# -------------------- Regular helpers: search/save/delete --------------------
async def get_search_results(search_query: str, offset: int = 0) -> Tuple[List[dict], int]:
    db = get_aiosqlite_connection()
    search_terms = [t.strip() for t in search_query.split() if t.strip()]
    if not search_terms:
        return [], offset

    where_clauses = []
    params: List[Any] = []
    for term in search_terms:
        where_clauses.append("(file_name LIKE ? OR caption LIKE ?)")
        like = f"%{term}%"
        params.extend([like, like])

    where_sql = " AND ".join(where_clauses)
    query = f"""
        SELECT file_id, file_name, size
        FROM media
        WHERE {where_sql}
        ORDER BY date_saved DESC
        LIMIT ? OFFSET ?
    """
    params.extend([MAX_FILES + 1, offset])

    async with db.execute(query, tuple(params)) as cursor:
        rows = await cursor.fetchall()

    files = [{"file_id": r[0], "file_name": r[1], "size": r[2]} for r in rows]
    return files, offset + len(files)


async def save_file_sql(media) -> Tuple[bool, int]:
    db = get_aiosqlite_connection()
    file_id, file_ref = unpack_new_file_id(media.file_id)
    caption = getattr(media, "caption", str(getattr(media, "file_name", "")))
    date_saved = datetime.datetime.now(pytz.utc)
    original_file_name = caption

    pattern = re.compile(
        r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',
        re.IGNORECASE,
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
        processed_name,
    )
    try:
        await db.execute(
            """
            INSERT INTO media (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(file_id),
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
        if "UNIQUE constraint failed: media.file_id" in str(e):
            return False, 0
        logger.exception(f"Integrity error while saving file '{file_name}': {e}")
        return False, 2
    except Exception as e:
        logger.exception(f"Unexpected error while saving file '{file_name}': {e}")
        return False, 2


async def delete_file_sql(file_id: str) -> bool:
    try:
        db = get_aiosqlite_connection()
        await db.execute("DELETE FROM media WHERE file_id = ?", (file_id,))
        await db.commit()
        return True
    except Exception:
        logger.exception("Error deleting file from SQLite")
        return False


async def delete_all_files_sql() -> Tuple[bool, int]:
    try:
        db = get_aiosqlite_connection()
        cur = await db.execute("SELECT COUNT(*) FROM media")
        row = await cur.fetchone()
        total_files = row[0] if row else 0
        if total_files == 0:
            logger.info("No files to delete, database is already empty.")
            return True, 0
        await db.execute("DELETE FROM media")
        await db.commit()
        logger.info(f"All {total_files} files deleted from database.")
        return True, total_files
    except Exception:
        logger.exception("Error occurred while deleting all files from database")
        return False, 0
