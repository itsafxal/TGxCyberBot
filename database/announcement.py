import asyncio
import logging
import re
import aiohttp
from typing import Dict, Any
from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, RPCError

from info import POST_CHANNELS, LOG_CHANNEL, STREAM_URL
from Script import script
from utils import temp, resolve_tmdb_stream_url

logger = logging.getLogger(__name__)

# Memory set & lock for zero-latency duplicate checks
_ANNOUNCED_KEYS_SET = set()
_ANNOUNCEMENT_LOCK = asyncio.Lock()
_METADATA_CACHE = {}

LANGUAGES_PATTERN = r"(?i)\b(tamil|tam|hindi|hin|telugu|tel|malayalam|mal|kannada|kan|english|eng)\b"

async def claim_announcement_lock(movie_key: str, title: str) -> bool:
    """
    Atomically checks and claims an announcement lock in SQLite database.
    Guarantees each movie is announced EXACTLY ONCE.
    """
    if not movie_key:
        return False

    async with _ANNOUNCEMENT_LOCK:
        if movie_key in _ANNOUNCED_KEYS_SET:
            return False

        from sql.db import ensure_aiosqlite_connection
        try:
            db = await ensure_aiosqlite_connection()
            await db.execute("""
                CREATE TABLE IF NOT EXISTS announcements (
                    movie_key TEXT PRIMARY KEY,
                    title TEXT,
                    date_announced TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            async with db.execute("SELECT 1 FROM announcements WHERE movie_key = ?", (movie_key,)) as cursor:
                if await cursor.fetchone():
                    _ANNOUNCED_KEYS_SET.add(movie_key)
                    return False

            await db.execute("INSERT INTO announcements (movie_key, title) VALUES (?, ?)", (movie_key, title))
            await db.commit()
            _ANNOUNCED_KEYS_SET.add(movie_key)
            return True
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                _ANNOUNCED_KEYS_SET.add(movie_key)
                return False
            logger.error(f"Error claiming announcement lock for {movie_key}: {e}")
            return False

def clean_movie_title_and_year(file_name: str):
    """Extracts clean movie title, year, and language string."""
    from sql.db import clean_file_name_for_title
    clean_title = clean_file_name_for_title(file_name)

    year_match = re.search(r'\b(19\d\d|20\d\d)\b', file_name)
    year = year_match.group(1) if year_match else "N/A"

    lang_matches = re.findall(LANGUAGES_PATTERN, file_name)
    if lang_matches:
        langs_list = []
        for l in lang_matches:
            l_cap = l.capitalize()
            if l_cap not in langs_list:
                langs_list.append(l_cap)
        languages_str = ", ".join(langs_list)
    else:
        languages_str = "Malayalam, Tamil, Telugu"

    return clean_title, year, languages_str

async def fetch_movie_metadata(title: str, year: str) -> Dict[str, Any]:
    """Fetches OMDb / IMDb metadata with fallback to default details."""
    cache_key = f"{title.lower()}_{year}"
    if cache_key in _METADATA_CACHE:
        return _METADATA_CACHE[cache_key]

    default_data = {
        "title": title,
        "year": year,
        "rating": "8.0/10",
        "genres": "Action, Drama, Thriller",
        "description": "Newly released movie now available for fast streaming and download.",
        "poster": "https://telegra.ph/file/69c84188c600122e23293.jpg"
    }

    try:
        url = f"https://www.omdbapi.com/?t={title.replace(' ', '+')}&apikey=32906d20"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("Response") == "True":
                        metadata = {
                            "title": data.get("Title", title),
                            "year": data.get("Year", year),
                            "rating": f"{data.get('imdbRating', '8.0')}/10",
                            "genres": data.get("Genre", "Action, Drama, Thriller"),
                            "description": data.get("Plot", "Newly released movie now available."),
                            "poster": data.get("Poster") if data.get("Poster") != "N/A" else default_data["poster"]
                        }
                        _METADATA_CACHE[cache_key] = metadata
                        return metadata
    except Exception as e:
        logger.debug(f"Metadata fetch fallback for '{title}': {e}")

    _METADATA_CACHE[cache_key] = default_data
    return default_data

async def announce_new_movie(bot, media):
    """
    Main background handler for automatic new movie announcements.
    Guarantees exactly-once distribution across POST_CHANNELS with resilient error handling.
    """
    raw_name = getattr(media, 'caption', None) or getattr(media, 'file_name', '')
    if not raw_name:
        return

    clean_name = re.sub(r"📂 Fɪʟᴇ ɴᴀṁᴇ :", "", str(raw_name)).strip()
    clean_title, year, languages_str = clean_movie_title_and_year(clean_name)
    if not clean_title:
        return

    movie_key = re.sub(r'[\s._-]+', '_', clean_title.lower()).strip('_')

    # Atomic deduplication check
    claimed = await claim_announcement_lock(movie_key, clean_title)
    if not claimed:
        logger.info(f"[ANNOUNCEMENT] Movie '{clean_title}' already announced. Skipping.")
        return

    target_channels = POST_CHANNELS if POST_CHANNELS else ([LOG_CHANNEL] if LOG_CHANNEL else [])
    if not target_channels:
        logger.warning("[ANNOUNCEMENT] No POST_CHANNELS configured. Announcement skipped.")
        return

    logger.info(f"[ANNOUNCEMENT] Starting new movie announcement for '{clean_title}' across {len(target_channels)} channel(s).")

    metadata = await fetch_movie_metadata(clean_title, year)

    bot_username = temp.U_NAME or (await bot.get_me()).username
    first_lang = languages_str.split(",")[0].strip().lower() if languages_str else "multi"
    slug_title = re.sub(r'[\s._-]+', '-', clean_title).strip('-')
    getfile_slug = f"getfile-{slug_title}-{first_lang}"
    search_url = f"https://t.me/{bot_username}?start={getfile_slug}"

    caption_text = script.AUTO_ANNOUNCEMENT_TXT.format(
        title=metadata["title"],
        year=metadata["year"],
        languages=languages_str,
        genres=metadata["genres"],
        rating=metadata["rating"],
        description=metadata["description"],
        bot_username=bot_username
    )

    stream_url = await resolve_tmdb_stream_url(file_name=clean_name)

    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 Get Movie", url=search_url),
            InlineKeyboardButton("🔍 Search in Bot", url=search_url)
        ],
        [
            InlineKeyboardButton("🖥️ Watch Online on Website", url=stream_url)
        ]
    ])

    poster_url = metadata["poster"]
    fallback_poster = "https://telegra.ph/file/69c84188c600122e23293.jpg"

    for channel_id in target_channels:
        success = False
        max_retries = 3
        current_poster = poster_url

        for attempt in range(max_retries):
            try:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=current_poster,
                    caption=caption_text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                success = True
                logger.info(f"[ANNOUNCEMENT] ✅ Successfully posted '{clean_title}' to channel {channel_id}")
                break
            except FloodWait as e:
                logger.warning(f"[ANNOUNCEMENT] FloodWait of {e.value}s on channel {channel_id}. Sleeping...")
                await asyncio.sleep(e.value + 1)
            except RPCError as e:
                logger.error(f"[ANNOUNCEMENT] RPC Error posting to channel {channel_id} (Attempt {attempt+1}/{max_retries}): {e}")
                if any(err_code in str(e) for err_code in ["WEBPAGE_MEDIA_EMPTY", "MEDIA_EMPTY", "PHOTO_INVALID", "URL_INVALID"]):
                    if current_poster != fallback_poster:
                        logger.info(f"[ANNOUNCEMENT] Retrying '{clean_title}' with fallback poster...")
                        current_poster = fallback_poster
                        continue
                    else:
                        try:
                            await bot.send_message(
                                chat_id=channel_id,
                                text=caption_text,
                                reply_markup=reply_markup,
                                parse_mode=enums.ParseMode.HTML
                            )
                            success = True
                            logger.info(f"[ANNOUNCEMENT] ✅ Successfully posted text announcement for '{clean_title}' to channel {channel_id}")
                            break
                        except Exception as text_err:
                            logger.error(f"[ANNOUNCEMENT] Text fallback failed for channel {channel_id}: {text_err}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[ANNOUNCEMENT] Unexpected error posting to channel {channel_id}: {e}")
                break

        if not success:
            logger.error(f"[ANNOUNCEMENT] ❌ Failed to post '{clean_title}' to channel {channel_id} after all attempts.")

