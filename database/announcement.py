import asyncio
import logging
import re
import json
import aiohttp
from typing import Dict, Any, List, Tuple
from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from pyrogram.errors import FloodWait, RPCError

from info import POST_CHANNELS, LOG_CHANNEL, STREAM_URL
from Script import script
from utils import temp, resolve_tmdb_stream_url

logger = logging.getLogger(__name__)

# Memory set & locks
_ANNOUNCEMENT_LOCK = asyncio.Lock()
_METADATA_CACHE = {}

ALLOWED_LANGUAGES = {
    "malayalam": "Malayalam",
    "mal": "Malayalam",
    "tamil": "Tamil",
    "tam": "Tamil",
    "telugu": "Telugu",
    "tel": "Telugu",
    "hindi": "Hindi",
    "hin": "Hindi",
    "kannada": "Kannada",
    "kan": "Kannada",
    "marathi": "Marathi",
    "mar": "Marathi",
    "bengali": "Bengali",
    "ben": "Bengali",
    "punjabi": "Punjabi",
    "pun": "Punjabi",
    "pan": "Punjabi",
    "gujarati": "Gujarati",
    "guj": "Gujarati",
    "english": "English",
    "eng": "English",
    "japanese": "Japanese",
    "jap": "Japanese",
    "jpn": "Japanese",
}

DISALLOWED_LANGUAGES = {
    "korean", "kor", "spanish", "spa", "french", "fre", "fra", "german", "ger", "deu",
    "italian", "ita", "russian", "rus", "chinese", "chi", "zho", "portuguese", "por",
    "turkish", "tur"
}

QUALITY_PATTERNS = [
    r"(?i)\b(2160p|4k|1080p|720p|480p|360p)\b",
    r"(?i)\b(web-?dl|webrip|hdrip|bluray|predvd|dvdrip|camrip|hdtv|hevc)\b"
]

QUALITY_ORDER = ["480p", "720p", "1080p", "2160p", "4K", "HEVC", "WEB-DL", "WEBRip", "HDRip", "BluRay", "PreDVD"]

async def init_announcements_db():
    """Ensures announcements table exists with all required columns."""
    from sql.db import ensure_aiosqlite_connection
    db = await ensure_aiosqlite_connection()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            movie_key TEXT PRIMARY KEY,
            title TEXT,
            year TEXT,
            languages TEXT,
            qualities TEXT,
            channel_messages TEXT,
            date_announced TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    async with db.execute("PRAGMA table_info(announcements)") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
    
    for col_name in ["year", "languages", "qualities", "channel_messages"]:
        if col_name not in columns:
            await db.execute(f"ALTER TABLE announcements ADD COLUMN {col_name} TEXT")
    await db.commit()

def extract_and_filter_languages(file_name: str) -> Tuple[List[str], bool]:
    """
    Extracts languages from filename and filters against allowed languages.
    Returns (detected_languages_list, is_allowed).
    """
    words = re.findall(r"(?i)\b[a-z]+\b", file_name)
    detected_allowed = []
    has_disallowed = False
    
    for word in words:
        w_lower = word.lower()
        if w_lower in ALLOWED_LANGUAGES:
            lang_name = ALLOWED_LANGUAGES[w_lower]
            if lang_name not in detected_allowed:
                detected_allowed.append(lang_name)
        elif w_lower in DISALLOWED_LANGUAGES:
            has_disallowed = True

    if has_disallowed and not detected_allowed:
        return [], False

    if not detected_allowed:
        return ["Malayalam", "Tamil", "Telugu"], True

    return detected_allowed, True

def extract_qualities(file_name: str) -> List[str]:
    """Extracts quality and format tags from filename."""
    qualities = []
    for pattern in QUALITY_PATTERNS:
        matches = re.findall(pattern, file_name)
        for m in matches:
            m_upper = m.upper()
            if m_upper in ['4K', 'HEVC', 'WEB-DL', 'WEBDL', 'WEBRIP', 'HDRIP', 'BLURAY', 'PREDVD']:
                if m_upper in ['WEB-DL', 'WEBDL']:
                    q_clean = 'WEB-DL'
                elif m_upper == 'WEBRIP':
                    q_clean = 'WEBRip'
                elif m_upper == 'HDRIP':
                    q_clean = 'HDRip'
                elif m_upper == 'BLURAY':
                    q_clean = 'BluRay'
                elif m_upper == 'PREDVD':
                    q_clean = 'PreDVD'
                else:
                    q_clean = m_upper
            else:
                q_clean = m.lower() if m.lower().endswith('p') else m.capitalize()
            if q_clean not in qualities:
                qualities.append(q_clean)
    if not qualities:
        qualities.append("720p")
    return sort_qualities(qualities)

def sort_qualities(qualities_list: List[str]) -> List[str]:
    """Sorts quality list by standard quality resolution hierarchy."""
    def sort_key(q):
        q_upper = q.upper()
        for idx, known in enumerate(QUALITY_ORDER):
            if q_upper == known.upper():
                return idx
        return 999
    return sorted(list(set(qualities_list)), key=sort_key)

def clean_movie_title_and_year(file_name: str):
    """Extracts clean movie title and year."""
    from sql.db import clean_file_name_for_title
    clean_title = clean_file_name_for_title(file_name)

    year_match = re.search(r'\b(19\d\d|20\d\d)\b', file_name)
    year = year_match.group(1) if year_match else "N/A"

    return clean_title, year

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

def format_post_caption(title: str, year: str, languages: List[str], rating: str, qualities: List[str]) -> str:
    """Formats structured post caption according to exact layout requirements."""
    langs_str = ", ".join(languages) if languages else "N/A"
    qual_str = ", ".join(qualities) if qualities else "N/A"
    year_str = f" ({year})" if year and year != "N/A" else ""
    
    rating_formatted = rating if "⭐" in rating else f"⭐ {rating}"
    
    caption = (
        f"🎬 <b>Title:</b> {title}{year_str}\n"
        f"🎙 <b>Languages:</b> {langs_str}\n"
        f"⭐ <b>Rating:</b> {rating_formatted}\n"
        f"📽 <b>Quality/Formats:</b> {qual_str}"
    )
    return caption

async def announce_new_movie(bot, media):
    """
    Main background handler for automatic new movie announcements.
    Consolidates posts per movie, applies language filtering, clean layout,
    and updates existing channel posts upon receiving new qualities/languages.
    """
    if not POST_CHANNELS:
        return

    raw_name = getattr(media, 'caption', None) or getattr(media, 'file_name', '')
    if not raw_name:
        return

    clean_name = re.sub(r"📂 Fɪʟᴇ ɴᴀṁᴇ :", "", str(raw_name)).strip()
    clean_title, year = clean_movie_title_and_year(clean_name)
    if not clean_title:
        return

    # Language Filtering
    languages, is_allowed = extract_and_filter_languages(clean_name)
    if not is_allowed:
        logger.info(f"[ANNOUNCEMENT] Movie '{clean_title}' language filtered out. Skipping.")
        return

    qualities = extract_qualities(clean_name)
    movie_key = re.sub(r'[\s._-]+', '_', clean_title.lower()).strip('_')

    async with _ANNOUNCEMENT_LOCK:
        await init_announcements_db()
        from sql.db import ensure_aiosqlite_connection
        db = await ensure_aiosqlite_connection()

        # Check existing post in database
        async with db.execute(
            "SELECT title, year, languages, qualities, channel_messages FROM announcements WHERE movie_key = ?",
            (movie_key,)
        ) as cursor:
            row = await cursor.fetchone()

        metadata = await fetch_movie_metadata(clean_title, year)

        bot_username = temp.U_NAME or (await bot.get_me()).username
        first_lang = languages[0].lower() if languages else "multi"
        slug_title = re.sub(r'[\s._-]+', '-', clean_title).strip('-')
        getfile_slug = f"getfile-{slug_title}-{first_lang}"
        search_url = f"https://t.me/{bot_username}?start={getfile_slug}"
        stream_url = await resolve_tmdb_stream_url(file_name=clean_name)

        # Strictly two inline keyboard buttons
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Get Download Link", url=search_url)],
            [InlineKeyboardButton("🌐 Stream Online", url=stream_url)]
        ])

        if row:
            # Movie already posted - Handle Update / Deduplication
            _, stored_year, stored_langs_str, stored_qual_str, channel_msg_json = row
            stored_langs = [l.strip() for l in (stored_langs_str or "").split(",") if l.strip()]
            stored_qual = [q.strip() for q in (stored_qual_str or "").split(",") if q.strip()]
            channel_messages = json.loads(channel_msg_json or "{}")

            # Merge languages & qualities
            merged_langs = list(stored_langs)
            for l in languages:
                if l not in merged_langs:
                    merged_langs.append(l)

            merged_qual = list(stored_qual)
            for q in qualities:
                if q not in merged_qual:
                    merged_qual.append(q)
            merged_qual = sort_qualities(merged_qual)

            # Check if any update is required
            if set(merged_langs) == set(stored_langs) and set(merged_qual) == set(stored_qual):
                logger.info(f"[ANNOUNCEMENT] Movie '{clean_title}' already posted with same qualities/languages. Skipping.")
                return

            logger.info(f"[ANNOUNCEMENT] Updating existing post for '{clean_title}' with new qualities/languages.")
            new_caption = format_post_caption(clean_title, stored_year or year, merged_langs, metadata["rating"], merged_qual)

            for channel_id_str, msg_id in channel_messages.items():
                try:
                    await bot.edit_message_caption(
                        chat_id=int(channel_id_str),
                        message_id=msg_id,
                        caption=new_caption,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.HTML
                    )
                    logger.info(f"[ANNOUNCEMENT] ✅ Updated caption for '{clean_title}' in channel {channel_id_str}")
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        try:
                            await bot.edit_message_text(
                                chat_id=int(channel_id_str),
                                message_id=msg_id,
                                text=new_caption,
                                reply_markup=reply_markup,
                                parse_mode=enums.ParseMode.HTML,
                                link_preview_options=LinkPreviewOptions(is_disabled=True)
                            )
                            logger.info(f"[ANNOUNCEMENT] ✅ Updated text for '{clean_title}' in channel {channel_id_str}")
                        except Exception as text_e:
                            logger.error(f"[ANNOUNCEMENT] Error editing message in {channel_id_str}: {text_e}")

            # Update DB with merged info
            await db.execute(
                "UPDATE announcements SET languages = ?, qualities = ? WHERE movie_key = ?",
                (", ".join(merged_langs), ", ".join(merged_qual), movie_key)
            )
            await db.commit()
            return

        # Movie NOT posted yet - Create First Post
        target_channels = POST_CHANNELS
        logger.info(f"[ANNOUNCEMENT] Posting new movie '{clean_title}' across {len(target_channels)} channel(s).")

        caption_text = format_post_caption(clean_title, year, languages, metadata["rating"], qualities)
        poster_url = metadata["poster"]
        fallback_poster = "https://telegra.ph/file/69c84188c600122e23293.jpg"
        channel_messages = {}

        for channel_id in target_channels:
            if not channel_id or str(channel_id).strip().lower() in ["0", "off", "disable", "false", "none", "null", "no", "n"]:
                continue
            success = False
            max_retries = 3
            current_poster = poster_url

            for attempt in range(max_retries):
                try:
                    sent_msg = await bot.send_photo(
                        chat_id=channel_id,
                        photo=current_poster,
                        caption=caption_text,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.HTML
                    )
                    channel_messages[str(channel_id)] = sent_msg.id
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
                                sent_msg = await bot.send_message(
                                    chat_id=channel_id,
                                    text=caption_text,
                                    reply_markup=reply_markup,
                                    parse_mode=enums.ParseMode.HTML,
                                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                                )
                                channel_messages[str(channel_id)] = sent_msg.id
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

        # Save to SQLite database
        if channel_messages:
            await db.execute(
                """INSERT INTO announcements (movie_key, title, year, languages, qualities, channel_messages)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (movie_key, clean_title, year, ", ".join(languages), ", ".join(qualities), json.dumps(channel_messages))
            )
            await db.commit()
