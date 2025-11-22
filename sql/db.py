import asyncio
import logging
import aiosqlite
import datetime
import pytz
import re
from typing import Tuple, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from info import DATABASE_URI2, DATABASE_NAME, DATABASE_URI3, COLLECTION_NAME, MAX_FILES, BOT_TOKEN
from database.ia_filterdb import unpack_new_file_id
from utils import get_size

# --- Logging / Config ---
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Migration tuning parameters
MONGO_BATCH_SIZE = 5000            # how many docs per Mongo page
PROGRESS_STEP = 50_000             # log progress every N inserted rows

# SQLite DB path
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

# --- Global SQLite Connection Manager ---
_global_aiosqlite_connection: Optional[aiosqlite.Connection] = None
_connection_lock = asyncio.Lock()


async def init_aiosqlite_connection(db_path: str) -> aiosqlite.Connection:
    global _global_aiosqlite_connection
    async with _connection_lock:
        if _global_aiosqlite_connection is None:
            _global_aiosqlite_connection = await aiosqlite.connect(db_path)
            await _global_aiosqlite_connection.execute("PRAGMA journal_mode=WAL;")
            await _global_aiosqlite_connection.execute("PRAGMA synchronous=NORMAL;")
            await _global_aiosqlite_connection.execute("PRAGMA locking_mode=NORMAL;")
            await _global_aiosqlite_connection.execute("PRAGMA foreign_keys=ON;")
            await _global_aiosqlite_connection.commit()
            logging.info(f"aiosqlite connection opened to {db_path}")
        return _global_aiosqlite_connection


def get_aiosqlite_connection():
    if _global_aiosqlite_connection is None:
        raise RuntimeError("aiosqlite not initialized")
    return _global_aiosqlite_connection


async def insert_batch(sqlite_conn, batch):
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


async def migrate_collection_integer_id(sql_db, collection, collection_name, db_name, doc_count):
    """
    Atlas-compatible migration using integer _id pagination.
    _id is INTEGER (user confirmed).
    """

    total_saved = 0
    last_id = 0  # integer pagination start

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

    while True:
        query = {"_id": {"$gt": last_id}}

        try:
            cursor = (
                collection.find(query, projection=projection)
                .sort("_id", 1)
                .limit(MONGO_BATCH_SIZE)
            )
            docs = await cursor.to_list(length=MONGO_BATCH_SIZE)
        except Exception as e:
            logging.error(f"Mongo read error for collection {collection_name}: {e}", exc_info=True)
            break

        if not docs:
            break

        batch_rows = []
        for doc in docs:
            _id = doc["_id"]
            if isinstance(_id, int):
                last_id = _id
            else:
                try:
                    last_id = int(_id)
                except:
                    continue

            date_saved = doc.get("date") or datetime.datetime.now(pytz.utc)

            row = (
                str(_id),
                doc.get("file_ref"),
                doc.get("file_name"),
                doc.get("file_size"),
                doc.get("size"),
                doc.get("file_type"),
                doc.get("mime_type"),
                doc.get("caption"),
                date_saved
            )
            batch_rows.append(row)

        try:
            await sql_db.execute("BEGIN;")
            await insert_batch(sql_db, batch_rows)
            await sql_db.commit()
            total_saved += len(batch_rows)
        except Exception as e:
            await sql_db.rollback()
            logging.error(f"SQLite insert error: {e}", exc_info=True)
            continue

        if total_saved % PROGRESS_STEP == 0:
            if doc_count:
                pct = (total_saved / doc_count) * 100
                logging.info(f"...inserted {total_saved}/{doc_count} ({pct:.2f}%)")
            else:
                logging.info(f"...inserted {total_saved}")

        await asyncio.sleep(0)

    logging.info(f"✔ Completed migration for {collection_name} from DB {db_name}: {total_saved} rows")
    return total_saved


async def migrate_to_sql():
    logging.info("🚀 Starting Atlas-safe migration (integer _id)...")

    await init_aiosqlite_connection(SQLITE_DB)
    sql_db = get_aiosqlite_connection()

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

    total_all = 0

    for item in COLLECTIONS_TO_MIGRATE:
        collection = item["db"][item["collection_name"]]
        db_name = item["db"].name
        col_name = item["collection_name"]

        try:
            doc_count = await collection.count_documents({})
            logging.info(f"Found {doc_count} docs in {db_name}.{col_name}")
        except:
            doc_count = None
            logging.info(f"Counting failed for {db_name}.{col_name}, migrating blindly")

        saved = await migrate_collection_integer_id(sql_db, collection, col_name, db_name, doc_count)
        total_all += saved

    logging.info(f"✨ Overall migration complete: {total_all} rows inserted.")


# --- Search, Save, Delete Below (same structure as before) ---

async def get_search_results(search_query: str, offset: int = 0):
    db = get_aiosqlite_connection()
    terms = [t for t in search_query.split() if t.strip()]
    if not terms:
        return [], offset

    where = []
    params = []

    for t in terms:
        where.append("(file_name LIKE ? OR caption LIKE ?)")
        like = f"%{t}%"
        params.extend([like, like])

    where_sql = " AND ".join(where)

    query = f"""
        SELECT file_id, file_name, size
        FROM media
        WHERE {where_sql}
        ORDER BY date_saved DESC
        LIMIT ? OFFSET ?
    """

    params.extend([MAX_FILES + 1, offset])

    async with db.execute(query, params) as cur:
        rows = await cur.fetchall()

    return (
        [{"file_id": r[0], "file_name": r[1], "size": r[2]} for r in rows],
        offset + len(rows)
    )

async def save_files_sql_batch(media_list: list) -> tuple:
    """
    Batch-save media objects to SQLite.
    Returns (saved_count, duplicate_count, error_count).

    Fast, safe, WAL-optimized INSERT OR IGNORE behavior.
    """
    if not media_list:
        return 0, 0, 0

    db = get_aiosqlite_connection()
    date_saved = datetime.datetime.now(pytz.utc)

    # Regex used in your media cleanup logic
    cleanup_regex = re.compile(
        r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|"
        r"\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|"
        r"MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|"
        r"\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|"
        r"\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|"
        r"\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])"
    )

    pattern_tv = re.compile(
        r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',
        re.IGNORECASE
    )

    rows = []

    for media in media_list:
        file_id, file_ref = unpack_new_file_id(media.file_id)
        caption = getattr(media, "caption", str(media.file_name))
        original_file_name = caption

        # Detect SxxExx
        match = pattern_tv.search(original_file_name)
        if match:
            season = int(match.group(1))
            ep = int(match.group(2))
            prefix = f"[S{season:02d} EP{ep:02d}]"
            processed_name = f"{prefix} {media.file_name}"
        else:
            processed_name = media.file_name

        cleaned_name = cleanup_regex.sub(" ", processed_name).strip()

        rows.append(
            (
                file_id,
                file_ref,
                cleaned_name,
                media.file_size,
                get_size(media.file_size),
                media.file_type,
                media.mime_type,
                caption,
                date_saved
            )
        )

    saved_count = 0
    duplicate_count = 0
    error_count = 0

    try:
        await db.execute("BEGIN;")
        cursor = await db.executemany(
            """
            INSERT OR IGNORE INTO media
            (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows
        )
        await db.commit()

        # SQLite rowcount for INSERT OR IGNORE is not accurate per-row,
        # but the safe method is:
        saved_count = cursor.rowcount if cursor.rowcount != -1 else len(rows)

        duplicate_count = len(rows) - saved_count

    except Exception as e:
        await db.rollback()
        logging.error(f"Batch insert error: {e}", exc_info=True)
        error_count = len(rows)

    return saved_count, duplicate_count, error_count

async def save_file_sql(media):
    db = get_aiosqlite_connection()
    file_id, file_ref = unpack_new_file_id(media.file_id)
    caption = getattr(media, "caption", media.file_name)
    date_saved = datetime.datetime.now(pytz.utc)

    cleaned = re.sub(
        r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])",
        " ",
        media.file_name
    ).strip()

    try:
        await db.execute(
            """
            INSERT INTO media
            (file_id, file_ref, file_name, file_size, size, file_type, mime_type, caption, date_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (file_id, file_ref, cleaned, media.file_size, get_size(media.file_size),
             media.file_type, media.mime_type, caption, date_saved)
        )
        await db.commit()
        return True, 1
    except aiosqlite.IntegrityError:
        return False, 0
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        return False, 2


async def delete_file_sql(file_id: str):
    db = get_aiosqlite_connection()
    try:
        await db.execute("DELETE FROM media WHERE file_id=?", (file_id,))
        await db.commit()
        return True
    except:
        return False


async def delete_all_files_sql():
    db = get_aiosqlite_connection()
    try:
        cur = await db.execute("SELECT COUNT(*) FROM media")
        count = (await cur.fetchone())[0]
        await db.execute("DELETE FROM media")
        await db.commit()
        return True, count
    except:
        return False, 0
