import asyncio
import logging
import aiosqlite
import datetime
import pytz
import re
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
    """Performs a high-speed migration from MongoDB to SQLite."""
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

        # --- Begin a single transaction for the entire collection ---
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
                    if total_saved_current_collection % PROGRESS_STEP == 0:
                        logging.info(f"    ...inserted {total_saved_current_collection} / {doc_count} files")
            
            # Insert the final, smaller batch if it exists
            if batch:
                await insert_batch_no_commit(sql_db, batch)
                total_saved_current_collection += len(batch)
            
            # --- Commit the transaction once all documents are processed ---
            await sql_db.commit()
            logging.info("  Transaction committed successfully.")

            logging.info(f"✅ Migration completed for '{current_collection_name}': {total_saved_current_collection} files saved.")
            total_files_saved_across_all_sources += total_saved_current_collection

        except Exception as e:
            await sql_db.rollback() # Rollback on error to maintain data integrity
            logging.error(f"  ❌ An error occurred during migration: {e}. Transaction has been rolled back.", exc_info=True)

    logging.info(f"\n✨ Overall Migration Summary: {total_files_saved_across_all_sources} files saved across all specified sources.")


# --- Regular Bot Operation Functions ---

async def get_search_results(search_query: str, offset: int = 0) -> Tuple[List[dict], int]:
    """Searches the SQLite database for files matching the query."""
    db = get_aiosqlite_connection()
    search_terms = search_query.split()
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
    params.extend([MAX_FILES+1, offset])
    
    async with db.execute(query, tuple(params)) as cursor:
        rows = await cursor.fetchall()
    
    files = [{"file_id": row[0], "file_name": row[1], "size": row[2]} for row in rows]
    return files, offset + len(files)


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
