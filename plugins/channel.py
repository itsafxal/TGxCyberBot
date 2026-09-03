import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from info import CHANNELS, DATABASE_URI, LOG_CHANNEL
from database.ia_filterdb import save_file2, save_file3, check_file
from sql.db import save_file_sql
from Script import script
from utils import temp
import logging
import re
import pytz
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

media_filter = filters.document | filters.video | filters.audio

client = AsyncIOMotorClient(DATABASE_URI)
db = client["autopost"]
collection = db["latest"]
collection_m = db["latestm"]
collection_h = db["latesth"]
collection_e = db["lateste"]
collection_ta = db["latestta"]
collection_te = db["latestte"]
collection_k = db["latestk"]

MOVIE_NAME_PATTERN = r"^(?P<title>.*?)(?=\s+(?:S\d+E\d+|\(\d{4}\)|\d{4}\b|\d+p|WEBRip|BluRay|HDRip|WEB-DL|PreDVD|HEVC|AAC|x264|DD|ESub|\[|\(|-)|\s*$)"
YEAR_PATTERN = r"\b\d{4}\b"
LANGUAGES = r"(?i)\b(tamil|tam|hindi|hin|telugu|tel|malayalam|mal|kannada|kan|english|eng)\b"

async def auto_post_new_file(bot, media):
    """Automatically posts a formatted Latest Release post to LOG_CHANNEL or target channel when a new file is added."""
    target_chat = LOG_CHANNEL
    if not target_chat:
        return

    try:
        raw_name = getattr(media, 'caption', None) or getattr(media, 'file_name', '')
        file_name = re.sub(r"📂 Fɪʟᴇ ɴᴀᴍᴇ :", "", str(raw_name)).strip()

        from sql.db import clean_file_name_for_title
        clean_title = clean_file_name_for_title(file_name)
        if not clean_title:
            clean_title = file_name

        lang_matches = re.findall(LANGUAGES, file_name)
        if lang_matches:
            langs_list = []
            for l in lang_matches:
                l_cap = l.capitalize()
                if l_cap not in langs_list:
                    langs_list.append(l_cap)
            languages_str = ", ".join(langs_list)
        else:
            languages_str = "Malayalam, Tamil, Telugu"

        first_lang = lang_matches[0].lower() if lang_matches else "multi"
        title_slug = re.sub(r'[\s._-]+', '-', clean_title).strip('-')
        getfile_param = f"getfile-{title_slug}-{first_lang}"

        bot_username = temp.U_NAME or (await bot.get_me()).username
        search_link = f"https://t.me/{bot_username}?start={getfile_param}"

        post_text = script.LATEST_POST_TXT.format(
            channel=f"@{bot_username}",
            title=clean_title,
            languages=languages_str,
            imdb_url=f"https://www.imdb.com/find/?q={clean_title.replace(' ', '+')}",
            genres="Action, Drama, Thriller",
            ott="OTT Release"
        )

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Click to Search 🔍", url=search_link)]
        ])

        await bot.send_message(
            chat_id=target_chat,
            text=post_text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    except Exception as e:
        logging.error(f"Error in auto_post_new_file: {e}")

async def get_all_movies(col):
    movies = col.find().sort("_id", -1)
    return [{"name": movie["name"], "year": movie.get("year", "N/A")} async for movie in movies]

@Client.on_message(filters.command("latest"))
async def handle_latest_command(client, message):
    collections = {
        "Malayalam": collection_m,
        "Tamil": collection_ta,
        "Telugu": collection_te,
        "Hindi": collection_h,
        "English": collection_e,
        "Kannada": collection_k,
        "Uncategorized": collection
    }

    response = "🎬 **Latest Movies by Language:**\n\n"
    for language, col in collections.items():
        movies = await get_all_movies(col)
        if movies:
            response += f"**{language}:**\n"
            for movie in movies:
                response += f"• {movie['name']} ({movie['year']})\n"
            response += "\n"

    if response.strip() != "🎬 **Latest Movies by Language:**":
        await message.reply_text(response)
    else:
        await message.reply_text("No movies found in the database.")

async def maintain_movie_limit(col, MAX_MOVIES):
    movie_count = await col.count_documents({})
    if movie_count > MAX_MOVIES:
        oldest_movie = await col.find_one(sort=[("_id", 1)])
        if oldest_movie:
            await col.delete_one({"_id": oldest_movie["_id"]})

async def match_file(caption):
    try:
        file_name = re.sub(r"📂 Fɪʟᴇ ɴᴀᴍᴇ :", "", caption)
        cleaned = re.sub(r"[.\-]", " ", file_name)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        match = re.match(MOVIE_NAME_PATTERN, cleaned)

        if match:
            movie_name = match.group("title").strip()

            year_match = re.search(YEAR_PATTERN, file_name)
            year = int(year_match.group(0)) if year_match else None

            today_ist = datetime.now(pytz.timezone('Asia/Kolkata')).date()
            today_str = today_ist.strftime("%Y%m%d")

            language_matches = re.findall(LANGUAGES, file_name)
            inserted = False

            if language_matches:
                for language_l in language_matches:
                    language = language_l.lower()

                    if language in ["malayalam", "mal"]:
                        target_collection = collection_m
                        document = {"name": movie_name, "year": year, "today": today_str}
                        if not await target_collection.find_one({"name": movie_name}):
                            await target_collection.insert_one(document)
                            await maintain_movie_limit(target_collection, 7)
                            inserted = True
                    if language in ["hindi", "hin"]:
                        target_collection = collection_h
                        document = {"name": movie_name, "year": year, "today": today_str}
                        if not await target_collection.find_one({"name": movie_name}):
                            await target_collection.insert_one(document)
                            await maintain_movie_limit(target_collection, 7)
                            inserted = True
                    if language in ["english", "eng"]:
                        target_collection = collection_e
                        document = {"name": movie_name, "year": year, "today": today_str}
                        if not await target_collection.find_one({"name": movie_name}):
                            await target_collection.insert_one(document)
                            await maintain_movie_limit(target_collection, 7)
                            inserted = True
                    if language in ["tamil", "tam"]:
                        target_collection = collection_ta
                        document = {"name": movie_name, "year": year, "today": today_str}
                        if not await target_collection.find_one({"name": movie_name}):
                            await target_collection.insert_one(document)
                            await maintain_movie_limit(target_collection, 7)
                            inserted = True
                    if language in ["telugu", "tel"]:
                        target_collection = collection_te
                        document = {"name": movie_name, "year": year, "today": today_str}
                        if not await target_collection.find_one({"name": movie_name}):
                            await target_collection.insert_one(document)
                            await maintain_movie_limit(target_collection, 7)
                            inserted = True
                    if language in ["kannada", "kan"]:
                        target_collection = collection_k
                        document = {"name": movie_name, "year": year, "today": today_str}
                        if not await target_collection.find_one({"name": movie_name}):
                            await target_collection.insert_one(document)
                            await maintain_movie_limit(target_collection, 7)
                            inserted = True
                    
            if not inserted:
                target_collection = collection
                document = {"name": movie_name, "year": year, "today": today_str}
                if not await target_collection.find_one({"name": movie_name}):
                    await target_collection.insert_one(document)
                    await maintain_movie_limit(target_collection, 7)

    except Exception as e:
        logging.info(f"Error in saving latest movie: {e}")
    return 0

@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    for file_type in ("document", "video", "audio"):
        media = getattr(message, file_type, None)
        if media is not None:
            break
    else:
        return

    media.file_type = file_type
    media.caption = message.caption
    await match_file(message.caption)

    tru = await check_file(media)
    if tru == "okda":
        is_saved_sql, save_response_sql = await save_file_sql(media)
        if message.id % 2 == 0:
            await save_file2(media)
        else:
            await save_file3(media)

        if is_saved_sql:
            from database.announcement import announce_new_movie
            asyncio.create_task(announce_new_movie(bot, media))
    else:
        logging.debug("Skipped duplicate file from saving to db")

