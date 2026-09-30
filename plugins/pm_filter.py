import asyncio
import re
import ast
import time
import random
from datetime import datetime, timedelta
import logging

from pyrogram import Client, filters, enums
from pyrogram.enums import ButtonStyle
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid, QueryIdInvalid, MessageIdInvalid
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, ReplyParameters, LinkPreviewOptions

from datetime import datetime, timedelta

from plugins.commands import schedule_message_deletion
from Script import script
from database.users_chats_db import db
from database.ia_filterdb import get_file_details, Media2, Media3, db as clientDB, db2 as clientDB2, db3 as clientDB3, fetch_mongo_ids_by_keyword
from database.gfilters_mdb import find_gfilter, get_gfilters
from info import ADMINS, CUSTOM_FILE_CAPTION, AUTO_DEL, MAX_FILES
from sql.db import get_search_results, delete_file_sql, get_suggestions_sql
from utils import (
    get_size, temp, is_requested_one, is_requested_two, add_auto_delete_message,
    premium_emoji, get_stream_buttons, get_stream_buttons_async, build_dynamic_fsub_keyboard,
    safe_delete_message, safe_edit_message_text, safe_edit_reply_markup, safe_answer_callback,
    IN_FLIGHT_CALLBACKS, PerfTracker, GLOBAL_METRICS, format_time_str
)

# --- Configuration ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DELETE_TXT = "🗑️ _This message and the file will be deleted in {} seconds._".format(AUTO_DEL)
GLOBAL_FILTER_CACHE = {}
CACHE_TTL = timedelta(minutes=5)
LANGUAGES = {"മലയാളം":"malayalam","தமிழ்":"tamil","ᴇɴɢʟɪsʜ":"english","हिन्दी":"hindi","తెలుగు":"telugu","కన్నడ":"kannada","🪄 ᴍᴜʟᴛɪ ʟᴀɴɢ 🪄":"multi"}
QUALITIES = ["360P", "480P", "720P", "1080P", "1440P", "2160P", "4K"]

# --- Helper Functions ---

from collections import OrderedDict

class SearchCache:
    def __init__(self, max_size=1500):
        self.cache = OrderedDict()
        self.max_size = max_size

    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)  # Mark as recently used
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)  # Remove oldest

    def get(self, key):
        return self.cache.get(key)

    def delete(self, key):
        if key in self.cache:
            del self.cache[key]

# Global instance
SEARCH_CACHE = SearchCache(max_size=5000)

async def get_gfilters_cached():
    """Caches global filter keywords to reduce DB load."""
    now = datetime.now()
    if "keywords" not in GLOBAL_FILTER_CACHE or now - GLOBAL_FILTER_CACHE.get("timestamp", datetime.min) > CACHE_TTL:
        keywords = await get_gfilters('gfilters')
        if keywords:
            # Combine keywords into a single regex for faster matching
            pattern = r"(?i)\b(" + "|".join(map(re.escape, keywords)) + r")\b"
            GLOBAL_FILTER_CACHE["keywords"] = keywords
            GLOBAL_FILTER_CACHE["pattern"] = re.compile(pattern)
            GLOBAL_FILTER_CACHE["timestamp"] = now
    return GLOBAL_FILTER_CACHE.get("pattern")

def get_file_caption(file_info):
    """Generates a formatted caption for a file."""
    title = file_info.file_name
    size = get_size(file_info.file_size)
    f_caption = file_info.caption
    
    if CUSTOM_FILE_CAPTION:
        try:
            f_caption = CUSTOM_FILE_CAPTION.format(
                file_name='' if title is None else title, 
                file_size='' if size is None else size, 
                file_caption='' if f_caption is None else f_caption
            )
        except Exception as e:
            logger.exception(e)
            f_caption = f_caption
    
    if f_caption is None:
        f_caption = f"{file_info.file_name}"
    
    return f_caption
    
# --- Message Handlers ---

@Client.on_message(filters.text & filters.incoming & filters.group & filters.regex(r'^(?!\/).*'))
async def auto_filter_handler(client, message):
    """Main handler for group messages, checking global filters then auto filters."""
    if not message.from_user:
        return
    logger.debug(f"[auto_filter_handler] user={message.from_user.id} chat={message.chat.id} text={message.text!r}")
    if not temp.AUTO_FILTER: return
    try:
        if not await global_filters(client, message):
            await auto_filter(client, message)
    except FloodWait as e:
        logger.warning(f"FloodWait in auto_filter_handler: {e.value}s")
    except Exception as e:
        logger.error(f"Error in auto_filter_handler: {e}")

@Client.on_message(filters.private & filters.text & filters.incoming & filters.regex(r'^(?!\/).*') & ~filters.forwarded)
async def auto_filter_pm_handler(client, message):
    """Handles non-command messages in private chat."""
    if not message.from_user:
        return
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name or "User")
    logger.debug(f"[auto_filter_pm_handler] user={message.from_user.id} text={message.text!r}")
    if not temp.AUTO_FILTER: 
        return
    if re.search(r'(?im)(?:https?://|www\.|t\.me/|telegram\.dog/)\S+|@[a-z0-9_]{5,32}\b', message.text):
        await safe_delete_message(message)
        return
    try:
        if not await global_filters(client, message):
            await pm_auto_filter(client, message)
    except FloodWait as e:
        logger.warning(f"FloodWait in auto_filter_pm_handler: {e.value}s")
    except Exception as e:
        logger.error(f"Error in auto_filter_pm_handler: {e}")

@Client.on_message(
    (filters.forwarded | filters.document | filters.photo | filters.video | 
     filters.audio | filters.voice | filters.video_note | 
     filters.sticker | filters.animation) & filters.private
)
async def delete_unwanted_messages(client, message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    if user_id in ADMINS: return # ignore admins

    # Skip deleting if message is forwarded from a channel/chat or contains an indexing link
    if getattr(message, "forward_origin", None) or getattr(message, "forward_date", None):
        return
    text_content = message.text or message.caption or ""
    if re.search(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)", text_content):
        return

    await safe_delete_message(message)
    
# --- Callback Handlers ---
@Client.on_callback_query(filters.regex(r"^next"))
async def next_page_cb(bot, query):
    user_id = query.from_user.id
    msg_id = getattr(query.message, "id", query.id)
    lock_key = (user_id, msg_id, "pagination")
    if not IN_FLIGHT_CALLBACKS.acquire(lock_key):
        await safe_answer_callback(query, "⏳ Loading...", show_alert=False)
        return

    tracker = PerfTracker(action="pagination", user_id=user_id, query=query.data)
    try:
        logger.debug(f"[next_page_cb] user={user_id} data={query.data}")
        try:
            _, search_key, offset_str = query.data.split("|")
            offset = int(offset_str)
        except ValueError:
            logger.warning(f"[next_page_cb] Invalid pagination data: {query.data}")
            await safe_answer_callback(query, "Iɴᴠᴀʟɪᴅ ᴘᴀɢɪɴᴀᴛɪᴏɴ ᴅᴀᴛᴀ.", show_alert=True)
            return
        
        cyber = query.from_user.mention
        req = SEARCH_CACHE.get(search_key)

        if not req:
            await safe_answer_callback(query, "🔁 Sᴇᴀʀᴄʜ ᴇxᴘɪʀᴇᴅ ᴏʀ ɴᴏᴛ ғᴏᴜɴᴅ Pʟᴇᴀsᴇ Sᴇᴀʀᴄʜ Aɢᴀɪɴ 😇", show_alert=True)
            return

        try:
            requested_user_id = int(search_key.split("_")[0])
            if user_id != requested_user_id:
                await safe_answer_callback(query, "✋ Tʜɪs ɪs ɴᴏᴛ ғᴏʀ ʏᴏᴜ! Pʟᴇᴀsᴇ ᴍᴀᴋᴇ ʏᴏᴜʀ ᴏᴡɴ sᴇᴀʀᴄʜ.", show_alert=True)
                return
        except Exception:
            pass

        t0 = time.time()
        files, next_offset = await get_search_results(req, offset=offset)
        tracker.db_ms = (time.time() - t0) * 1000

        if not files:
            await safe_answer_callback(query, "🚫Nᴏ ᴍᴏʀᴇ ʀᴇsᴜʟᴛs ғᴏᴜɴᴅ 🚫", show_alert=True)
            return

        btn = generate_main_buttons(files, offset, search_key, next_offset=next_offset)
        current_page = (offset // MAX_FILES) + 1
        new_text = script.MAIN_RESULT_TXT.format(cyber=cyber, search=req, page=current_page)

        t1 = time.time()
        await safe_edit_message_text(
            query,
            text=new_text,
            reply_markup=InlineKeyboardMarkup(btn)
        )
        tracker.telegram_ms = (time.time() - t1) * 1000
        tracker.edit_count = 1
        tracker.telegram_calls = 1

        await safe_answer_callback(query)
    finally:
        IN_FLIGHT_CALLBACKS.release(lock_key)
        tracker.log()


def generate_main_buttons(files, offset, search_key, next_offset=0):
    """Generates the main list of file buttons with smooth single-row navigation and filters."""
    btn = [
        [
            InlineKeyboardButton(
                text=f" {file.get('size', 'N/A')} 🌷 {file.get('file_name', 'No Name')}",
                callback_data=f"file#{file['file_id']}",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5397915559037785261
            ),
        ]
        for file in files
    ]
    
    # Insert Language and Quality buttons at the top
    btn.insert(0, [
        InlineKeyboardButton(
            text="Lᴀɴɢᴜᴀɢᴇs",
            callback_data=f"languages#{search_key}",
            style=ButtonStyle.PRIMARY,
            icon_custom_emoji_id=5888584382553265934
        ),
        InlineKeyboardButton(
            text="Qᴜᴀʟɪᴛʏ",
            callback_data=f"qualities#{search_key}",
            style=ButtonStyle.PRIMARY,
            icon_custom_emoji_id=5802910664150226061
        )
    ])
    
    # Add pagination buttons
    nav_buttons = []
    if offset > 0:
        prev_offset = max(0, offset - MAX_FILES)
        nav_buttons.append(InlineKeyboardButton(
            "◀️ 𝗕𝗮𝗰𝗸",
            callback_data=f"next|{search_key}|{prev_offset}",
            style=ButtonStyle.SUCCESS,
            icon_custom_emoji_id=5210912043019822307
        ))
        
    if next_offset:
        nav_buttons.append(InlineKeyboardButton(
            "𝗡𝗲𝘅𝘁 ▶️",
            callback_data=f"next|{search_key}|{next_offset}",
            style=ButtonStyle.SUCCESS,
            icon_custom_emoji_id=5210912043019822307
        ))

    if nav_buttons:
        btn.append(nav_buttons)
    else:
        btn.append([InlineKeyboardButton(
            text="↭ ɴᴏ ᴍᴏʀᴇ ᴘᴀɢᴇꜱ ᴀᴠᴀɪʟᴀʙʟᴇ ↭",
            callback_data="pages",
            style=ButtonStyle.DEFAULT,
            icon_custom_emoji_id=5215354932598350357
        )])

    return btn

def get_all_language_codes():
    """Returns a list of all language codes in lowercase."""
    try:
        return [code.lower() for code in LANGUAGES.values()]
    except AttributeError:
        return [str(lang).lower() for lang in LANGUAGES]

def get_language_name_from_code(lang_code):
    """Returns the full language name from its code."""
    try:
        inv_map = {v.lower(): k for k, v in LANGUAGES.items()}
        return inv_map.get(str(lang_code).lower(), str(lang_code).title())
    except Exception:
        return str(lang_code).title()

# ---------------------------
# Language Feature Handlers
# ---------------------------

@Client.on_callback_query(filters.regex(r"^languages#"))
async def languages_cb_handler(client: Client, query: CallbackQuery):
    """Displays the list of available language filters."""
    user_id = query.from_user.id
    msg_id = getattr(query.message, "id", query.id)
    lock_key = (user_id, msg_id, "languages")
    if not IN_FLIGHT_CALLBACKS.acquire(lock_key):
        await safe_answer_callback(query, "⏳ Loading...", show_alert=False)
        return

    try:
        logger.debug(f"[languages_cb_handler] user={user_id} data={query.data}")
        try:
            _, search_key = query.data.split("#")
        except ValueError:
            return await safe_answer_callback(query, "Iɴᴠᴀʟɪᴅ ᴄᴀʟʟʙᴀᴄᴋ ᴅᴀᴛᴀ sᴛʀᴜᴄᴛᴜʀᴇ.", show_alert=True)

        try:
            requested_user_id = int(search_key.split("_")[0])
            if user_id != requested_user_id:
                return await safe_answer_callback(
                    query,
                    f"⚠️ ʜᴇʟʟᴏ {query.from_user.first_name},\nᴛʜɪꜱ ɪꜱ ɴᴏᴛ ʏᴏᴜʀ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇꜱᴛ,\nʀᴇǫᴜᴇꜱᴛ ʏᴏᴜʀ'ꜱ...",
                    show_alert=True,
                )
        except Exception:
            pass

        if not SEARCH_CACHE.get(search_key):
            return await safe_answer_callback(query, "Sᴇᴀʀᴄʜ ᴇxᴘɪʀᴇᴅ ᴏʀ ɴᴏᴛ ғᴏᴜɴᴅ. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ. 🔰", show_alert=True)

        items = list(LANGUAGES.items())
        btn = []

        # Create language buttons, 2 per row
        for i in range(0, len(items), 2):
            name1, code1 = items[i]
            row = [InlineKeyboardButton(
                text=name1, 
                callback_data=f"fl#{code1.lower()}#{search_key}",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5888584382553265934
            )]
            if i + 1 < len(items):
                name2, code2 = items[i + 1]
                row.append(InlineKeyboardButton(
                    text=name2, 
                    callback_data=f"fl#{code2.lower()}#{search_key}",
                    style=ButtonStyle.DEFAULT,
                    icon_custom_emoji_id=5888584382553265934
                ))
            btn.append(row)

        btn.insert(0, [InlineKeyboardButton(
            text="⇊ ꜱᴇʟᴇᴄᴛ ʟᴀɴɢᴜᴀɢᴇ ⇊",
            callback_data="ident",
            style=ButtonStyle.DEFAULT,
            icon_custom_emoji_id=5215354932598350357
        )])
                
        btn.append([InlineKeyboardButton(
            text="↭ ʙᴀᴄᴋ ᴛᴏ ꜰɪʟᴇs ↭",
            callback_data=f"next|{search_key}|0",
            style=ButtonStyle.SUCCESS,
            icon_custom_emoji_id=5210912043019822307
        )])

        await safe_edit_reply_markup(query, reply_markup=InlineKeyboardMarkup(btn))
        await safe_answer_callback(query)
    finally:
        IN_FLIGHT_CALLBACKS.release(lock_key)
        
@Client.on_callback_query(filters.regex(r"^fl#"))
async def filter_languages_cb_handler(client: Client, query: CallbackQuery):
    """Handles the application of a language filter."""
    user_id = query.from_user.id
    msg_id = getattr(query.message, "id", query.id)
    lock_key = (user_id, msg_id, "filter_lang")
    if not IN_FLIGHT_CALLBACKS.acquire(lock_key):
        await safe_answer_callback(query, "⏳ Filtering...", show_alert=False)
        return

    tracker = PerfTracker(action="filter_lang", user_id=user_id, query=query.data)
    try:
        try:
            _, lang_code, search_key = query.data.split("#")
        except ValueError:
            return await safe_answer_callback(query, "Iɴᴠᴀʟɪᴅ ʟᴀɴɢᴜᴀɢᴇ ғɪʟᴛᴇʀ ᴅᴀᴛᴀ.", show_alert=True)

        original_search_query = SEARCH_CACHE.get(search_key)
        if not original_search_query:
            return await safe_answer_callback(query, "Sᴇᴀʀᴄʜ ᴇxᴘɪʀᴇᴅ ᴏʀ ɴᴏᴛ ғᴏᴜɴᴅ. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ. 🔰", show_alert=True)

        try:
            requested_user_id = int(search_key.split("_")[0])
            if user_id != requested_user_id:
                return await safe_answer_callback(
                    query,
                    f"⚠️ ʜᴇʟʟᴏ {query.from_user.first_name},\nᴛʜɪꜱ ɪꜱ ɴᴏᴛ ʏᴏᴜʀ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇꜱᴛ,\nʀᴇǫᴜᴇꜱᴛ ʏᴏᴜʀ'ꜱ...",
                    show_alert=True,
                )
        except Exception:
            pass

        lower_lang_code = lang_code.lower()
        search_words = original_search_query.lower().split()
        all_language_codes = get_all_language_codes()

        base_query_words = [word for word in search_words if word not in all_language_codes]
        
        if lower_lang_code in search_words:
            new_filtered_search = " ".join(base_query_words)
            selected_language_name = get_language_name_from_code(lower_lang_code)
            alert_message_success = f"❌ Lᴀɴɢᴜᴀɢᴇ ғɪʟᴛᴇʀ ʀᴇᴍᴏᴠᴇᴅ: {selected_language_name} Sᴜᴄᴄᴇsғᴜʟʟʏ✅"
        else:
            base_query_words.append(lower_lang_code)
            new_filtered_search = " ".join(base_query_words)
            selected_language_name = get_language_name_from_code(lower_lang_code)
            alert_message_success = f"Yᴏᴜʀ ғɪʟᴇs ᴀʀᴇ ɴᴏᴡ ғɪʟᴛᴇʀᴇᴅ ᴛᴏ: {selected_language_name} Sᴜᴄᴄᴇsғᴜʟʟʏ✅ "
        
        t0 = time.time()
        files, offset = await get_search_results(new_filtered_search, offset=0)
        tracker.db_ms = (time.time() - t0) * 1000
        
        if not files:
            files_revert, offset_revert = await get_search_results(original_search_query, offset=0)
            revert_btn = generate_main_buttons(files_revert, offset_revert, search_key)
            
            selected_language_name = get_language_name_from_code(lower_lang_code)
            await safe_answer_callback(
                query,
                f"🚫 Nᴏ Fɪʟᴇ Fᴏᴜɴᴅ Wɪᴛʜ Tʜɪs Lᴀɴɢᴜᴀɢᴇ {selected_language_name}. Bᴀᴄᴋ ᴛᴏ ᴏʀɪɢɪɴᴀʟ sᴇᴀʀᴄʜ ʀᴇsᴜʟᴛs.", 
                show_alert=True
            )

            await safe_edit_reply_markup(query, reply_markup=InlineKeyboardMarkup(revert_btn))
            return

        SEARCH_CACHE.set(search_key, new_filtered_search)
        btn = generate_main_buttons(files, offset, search_key)

        t1 = time.time()
        await safe_edit_reply_markup(query, reply_markup=InlineKeyboardMarkup(btn))
        tracker.telegram_ms = (time.time() - t1) * 1000
        tracker.edit_count = 1
        tracker.telegram_calls = 1

        await safe_answer_callback(query, alert_message_success, show_alert=True)
    finally:
        IN_FLIGHT_CALLBACKS.release(lock_key)
        tracker.log()

# ---------------------------
# Quality Feature Handlers
# ---------------------------

@Client.on_callback_query(filters.regex(r"^qualities#"))
async def qualities_cb_handler(client: Client, query: CallbackQuery):
    """Displays the list of available quality filters."""
    user_id = query.from_user.id
    msg_id = getattr(query.message, "id", query.id)
    lock_key = (user_id, msg_id, "qualities")
    if not IN_FLIGHT_CALLBACKS.acquire(lock_key):
        await safe_answer_callback(query, "⏳ Loading...", show_alert=False)
        return

    try:
        logger.debug(f"[qualities_cb_handler] user={user_id} data={query.data}")
        try:
            _, search_key = query.data.split("#")
        except ValueError:
            return await safe_answer_callback(query, "Iɴᴠᴀʟɪᴅ ᴄᴀʟʟʙᴀᴄᴋ ᴅᴀᴛᴀ sᴛʀᴜᴄᴛᴜʀᴇ.", show_alert=True)

        original_search_query = SEARCH_CACHE.get(search_key)
        if not original_search_query:
            return await safe_answer_callback(query, "Sᴇᴀʀᴄʜ ᴇxᴘɪʀᴇᴅ ᴏʀ ɴᴏᴛ ғᴏᴜɴᴅ. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ. 🔰", show_alert=True)

        try:
            requested_user_id = int(search_key.split("_")[0])
            if user_id != requested_user_id:
                return await safe_answer_callback(
                    query,
                    f"⚠️ ʜᴇʟʟᴏ {query.from_user.first_name},\nᴛʜɪꜱ ɪꜱ ɴᴏᴛ ʏᴏᴜʀ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇꜱᴛ,\nʀᴇǫᴜᴇꜱᴛ ʏᴏᴜʀ'ꜱ...",
                    show_alert=True,
                )
        except Exception:
            pass

        btn = []
        
        # Create quality buttons, 2 per row
        for i in range(0, len(QUALITIES), 2):
            q1 = QUALITIES[i]
            row = [InlineKeyboardButton(
                text=q1,
                callback_data=f"fq#{q1.lower()}#{search_key}",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5802910664150226061
            )]
            if i + 1 < len(QUALITIES):
                q2 = QUALITIES[i + 1]
                row.append(InlineKeyboardButton(
                    text=q2,
                    callback_data=f"fq#{q2.lower()}#{search_key}",
                    style=ButtonStyle.DEFAULT,
                    icon_custom_emoji_id=5802910664150226061
                ))
            btn.append(row)

        btn.insert(0, [
            InlineKeyboardButton(
                text="⇊ ꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ ⇊",
                callback_data="ident",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            )
        ])

        btn.append([
            InlineKeyboardButton(
                text="↭ ʙᴀᴄᴋ ᴛᴏ ꜰɪʟᴇs ↭",
                callback_data=f"next|{search_key}|0",
                style=ButtonStyle.SUCCESS,
                icon_custom_emoji_id=5210912043019822307
            )
        ])

        await safe_edit_reply_markup(query, reply_markup=InlineKeyboardMarkup(btn))
        await safe_answer_callback(query)
    finally:
        IN_FLIGHT_CALLBACKS.release(lock_key)

@Client.on_callback_query(filters.regex(r"^fq#"))
async def filter_quality_cb_handler(client: Client, query: CallbackQuery):
    """Handles the application of a quality filter."""
    user_id = query.from_user.id
    msg_id = getattr(query.message, "id", query.id)
    lock_key = (user_id, msg_id, "filter_quality")
    if not IN_FLIGHT_CALLBACKS.acquire(lock_key):
        await safe_answer_callback(query, "⏳ Filtering...", show_alert=False)
        return

    tracker = PerfTracker(action="filter_quality", user_id=user_id, query=query.data)
    try:
        try:
            _, qual, search_key = query.data.split("#")
        except ValueError:
            return await safe_answer_callback(query, "Iɴᴠᴀʟɪᴅ ǫᴜᴀʟɪᴛʏ ғɪʟᴛᴇʀ ᴅᴀᴛᴀ.", show_alert=True)

        original_search_query = SEARCH_CACHE.get(search_key)
        if not original_search_query:
            return await safe_answer_callback(query, "Sᴇᴀʀᴄʜ ᴇxᴘɪʀᴇᴅ ᴏʀ ɴᴏᴛ ғᴏᴜɴᴅ. Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ. 🔰", show_alert=True)

        try:
            requested_user_id = int(search_key.split("_")[0])
            if user_id != requested_user_id:
                return await safe_answer_callback(
                    query,
                    f"⚠️ ʜᴇʟʟᴏ {query.from_user.first_name},\nᴛʜɪꜱ ɪꜱ ɴᴏᴛ ʏᴏᴜʀ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇꜱᴛ,\nʀᴇǫᴜᴇꜱᴛ ʏᴏᴜʀ'ꜱ...",
                    show_alert=True,
                )
        except Exception:
            pass

        qual_lower = qual.lower()
        search_words = original_search_query.lower().split()
        all_quality_codes = get_all_quality_codes()

        base_query_words = [word for word in search_words if word not in all_quality_codes]

        if qual_lower in search_words:
            new_filtered_search = " ".join(base_query_words)
            alert_message = f"❌ Qᴜᴀʟɪᴛʏ ғɪʟᴛᴇʀ ʀᴇᴍᴏᴠᴇᴅ: {qual.upper()} Sᴜᴄᴄᴇsғᴜʟʟʏ✅"
        else:
            base_query_words.append(qual_lower)
            new_filtered_search = " ".join(base_query_words)
            alert_message = f"Yᴏᴜʀ ғɪʟᴇs ᴀʀᴇ ɴᴏᴡ ғɪʟᴛᴇʀᴇᴅ ᴛᴏ: {qual.upper()} Sᴜᴄᴄᴇsғᴜʟʟʏ✅"
                
        t0 = time.time()
        files, offset = await get_search_results(new_filtered_search, offset=0)
        tracker.db_ms = (time.time() - t0) * 1000
        
        if not files:
            files_revert, offset_revert = await get_search_results(original_search_query, offset=0)
            revert_btn = generate_main_buttons(files_revert, offset_revert, search_key)
            
            await safe_answer_callback(
                query,
                f"🚫 ɴᴏ ꜰɪʟᴇꜱ ᴡᴇʀᴇ ꜰᴏᴜɴᴅ ᴡɪᴛʜ ᴛʜɪꜱ ǫᴜᴀʟɪᴛʏ {qual.upper()}. Bᴀᴄᴋ ᴛᴏ ᴏʀɪɢɪɴᴀʟ sᴇᴀʀᴄʜ ʀᴇsᴜʟᴛs.", 
                show_alert=True
            )
            
            await safe_edit_reply_markup(query, reply_markup=InlineKeyboardMarkup(revert_btn))
            return

        SEARCH_CACHE.set(search_key, new_filtered_search)
        btn = generate_main_buttons(files, offset, search_key)

        t1 = time.time()
        await safe_edit_reply_markup(query, reply_markup=InlineKeyboardMarkup(btn))
        tracker.telegram_ms = (time.time() - t1) * 1000
        tracker.edit_count = 1
        tracker.telegram_calls = 1

        await safe_answer_callback(query, alert_message, show_alert=True)
    finally:
        IN_FLIGHT_CALLBACKS.release(lock_key)
        tracker.log()
        
@Client.on_callback_query(filters.regex(r"^sp#"))
async def spell_check_cb_handler(client: Client, query: CallbackQuery):
    """Handles the user clicking a spell check suggestion button."""
    user_id = query.from_user.id
    msg_id = getattr(query.message, "id", query.id)
    lock_key = (user_id, msg_id, "spell_cb")
    if not IN_FLIGHT_CALLBACKS.acquire(lock_key):
        await safe_answer_callback(query, "⏳ Searching...", show_alert=False)
        return

    tracker = PerfTracker(action="spell_click", user_id=user_id, query=query.data)
    try:
        try:
            _, search_key, index_str = query.data.split("#")
            index = int(index_str)
        except ValueError:
            return await safe_answer_callback(query, "Iɴᴠᴀʟɪᴅ sᴜɢɢᴇsᴛɪᴏɴ ᴅᴀᴛᴀ.", show_alert=True)

        try:
            requested_user_id = int(search_key.split("_")[0])
            if user_id != requested_user_id:
                return await safe_answer_callback(
                    query,
                    f"⚠️ ʜᴇʟʟᴏ {query.from_user.first_name},\nᴛʜɪꜱ ɪꜱ ɴᴏᴛ ʏᴏᴜʀ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇsᴛ,\nʀᴇǫᴜᴇꜱᴛ ʏᴏᴜʀ'ꜱ...",
                    show_alert=True,
                )
        except Exception:
            pass

        suggestions = SEARCH_CACHE.get(f"spell_{search_key}")
        if not suggestions or index >= len(suggestions):
            return await safe_answer_callback(query, "Sᴇᴀʀᴄʜ ᴇxᴘɪʀᴇᴅ ᴏʀ ɴᴏᴛ ғᴏᴜɴᴅ. Pʟᴇᴀsᴇ sᴇᴀʀᴄʜ ᴀɢᴀɪɴ. 🔰", show_alert=True)

        selected_suggestion = suggestions[index]
        await safe_answer_callback(query, f"🔎 Sᴇᴀʀᴄʜɪɴɢ ғᴏʀ: {selected_suggestion}", show_alert=False)

        t0 = time.time()
        files, offset = await get_search_results(selected_suggestion, offset=0)
        tracker.db_ms = (time.time() - t0) * 1000

        if not files:
            await safe_edit_message_text(
                query,
                text=f"🚫 Nᴏ ғɪʟᴇs ғᴏᴜɴᴅ ғᴏʀ <b>{selected_suggestion}</b>.",
                parse_mode=enums.ParseMode.HTML
            )
            return

        cyber = query.from_user.mention
        btn = generate_main_buttons(files, offset, search_key)
        SEARCH_CACHE.set(search_key, selected_suggestion)

        t1 = time.time()
        await safe_edit_message_text(
            query,
            text=script.MAIN_RESULT_TXT.format(cyber=cyber, search=selected_suggestion, page=1),
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.HTML
        )
        tracker.telegram_ms = (time.time() - t1) * 1000
        tracker.edit_count = 1
        tracker.telegram_calls = 1
    finally:
        IN_FLIGHT_CALLBACKS.release(lock_key)
        tracker.log()

@Client.on_callback_query(group=1)
async def main_cb_handler(client: Client, query: CallbackQuery):
    data = query.data
    logger.debug(f"[main_cb_handler] user={query.from_user.id} data={data!r}")
    if data == "close_data":
        if query.message:
            await safe_delete_message(query.message)
        await safe_answer_callback(query)

    elif data.startswith("file#"):
        _, file_id = data.split("#")
        try:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start=file_{file_id}")
        except (UserIsBlocked, PeerIdInvalid):
            await safe_answer_callback(query, "Bot blocked or not started! Please start the bot in private first.", url=f"https://t.me/{temp.U_NAME}?start=file_{file_id}", show_alert=True)
        except Exception:
            await safe_answer_callback(query, url=f"https://t.me/{temp.U_NAME}?start=file_{file_id}")

    elif data.startswith("checksub#") or data.startswith("checksubp#"):
        ident, file_id = data.split("#", 1)
        user_id = query.from_user.id

        lock_key = (user_id, file_id, "checksub")
        if not IN_FLIGHT_CALLBACKS.acquire(lock_key):
            await safe_answer_callback(query, "⏳ Checking subscription...", show_alert=False)
            return

        try:
            full_file_arg = f"{'filep' if ident == 'checksubp' else 'file'}_{file_id}" if file_id else None
            reply_markup, unjoined = await build_dynamic_fsub_keyboard(client, user_id, file_id=full_file_arg)

            if unjoined:
                if query.message:
                    await safe_edit_reply_markup(query.message, reply_markup=reply_markup)

                return await safe_answer_callback(
                    query,
                    "🚨 You haven't joined all required channels yet! Joined channel buttons have been hidden. Please join the remaining channel(s) shown above and click Try Again.",
                    show_alert=True
                )

            files = await get_file_details(file_id)
            if not files:
                return await safe_answer_callback(query, '⚠️ File not found or has been removed.', show_alert=True)
            
            await safe_answer_callback(query, "✅ Checking complete. Sending file...", show_alert=False)
            
            try:
                stream_markup = await get_stream_buttons_async(file_id=file_id, file_name=files[0].file_name)
                GLOBAL_METRICS.inc("send_message")
                sent_msg = await client.send_cached_media(
                    chat_id=query.from_user.id,
                    file_id=file_id,
                    caption=get_file_caption(files[0]),
                    protect_content=(ident == "checksubp"),
                    reply_markup=stream_markup,
                    parse_mode=enums.ParseMode.MARKDOWN
                )
                if sent_msg:
                    await add_auto_delete_message(query.from_user.id, sent_msg.id, temp.FILE_DEL_TIME, msg_type="file", file_id=file_id)
                    GLOBAL_METRICS.inc("send_message")
                    del_notice = await client.send_message(
                        chat_id=query.from_user.id,
                        text=DELETE_TXT.format(format_time_str(temp.FILE_DEL_TIME)),
                        parse_mode=enums.ParseMode.HTML
                    )
                    await add_auto_delete_message(query.from_user.id, del_notice.id, temp.FILE_DEL_TIME, msg_type="delete_txt")
                else:
                    await safe_answer_callback(query, "❌ Failed to send file.", show_alert=True)
                
            except FloodWait as e:
                logger.warning(f"FloodWait when sending media: {e.value}s")
                GLOBAL_METRICS.inc("flood_wait_events")
                await safe_answer_callback(query, f"Flood control: Please wait {e.value} seconds.", show_alert=True)
            except Exception as e:
                logger.exception(e)
                await safe_answer_callback(query, "An error occurred while sending the file.", show_alert=True)
        finally:
            IN_FLIGHT_CALLBACKS.release(lock_key)

    elif data.startswith("killfilesdq#"):
        _, keyword = data.split("#")
        msg = await query.message.edit_text(f"🔎 **Step 1/3: Fetching all file IDs for** `{keyword}`**. Please wait...**")
    
        try:
            unique_ids_to_delete = await fetch_mongo_ids_by_keyword(keyword)
            
            if not unique_ids_to_delete:
                return await msg.edit_text(f"✅ No files found matching `{keyword}` across all databases.")
            
            total_found = len(unique_ids_to_delete)
            await msg.edit_text(f"🗑️ **Step 2/3: Deleting `{total_found}` files from MongoDB collections...**")
    
            mongo_deleted_count = 0
            await msg.edit_text(f"🗃️ **Step 3/3: Deleting `{total_found}` files from SQLite database...**")
    
            sql_deleted_count = 0
            for file_id in unique_ids_to_delete:
                result = await Media2.collection.delete_one({'_id': file_id})
                mongo_deleted_count += result.deleted_count
                result2 = await Media3.collection.delete_one({'_id': file_id})
                mongo_deleted_count += result2.deleted_count
                success = await delete_file_sql(file_id)
                if success:
                    sql_deleted_count += 1
                    
            await msg.edit_text(
                f"🎉 **Deletion Complete!**\n\n"
                f"**Keyword:** `{keyword}`\n"
                f"**Total Files Found:** `{total_found}`\n"
                f"**Deleted from MongoDB:** `{mongo_deleted_count}`\n"
                f"**Deleted from SQLite:** `{sql_deleted_count if sql_deleted_count != 0 else 'Error'}`"
            )
    
        except Exception as e:
            logger.error(f"Error during combined deletion: {e}", exc_info=True)
            await msg.edit_text(f'❌ **An unexpected error occurred:** `{e}`')

    elif query.data == "abc":
        await safe_answer_callback(query, "Tʜɪs ғᴇᴀᴛᴜʀᴇ ᴡɪʟʟ ʙᴇ ᴀᴅᴅ sᴏᴏɴ 😉", show_alert=True)
    elif query.data == "efg":
        await safe_answer_callback(query, "Tʜɪs ғᴇᴀᴛᴜʀᴇ ᴡɪʟʟ ʙᴇ ᴀᴅᴅ sᴏᴏɴ 😉", show_alert=True)

    elif data == "start":
        buttons = [[
            InlineKeyboardButton(
                '➜ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ➜',
                url=f'http://t.me/{temp.U_NAME}?startgroup=true',
                style=ButtonStyle.PRIMARY,
                icon_custom_emoji_id=5215354932598350357
            )
        ],[
            InlineKeyboardButton(
                "⭐ Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ Fᴏʀ Cᴏᴍᴘʟᴀɪɴᴛ ⭐",
                url='https://cybertg.vercel.app',
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            )
        ],[
            InlineKeyboardButton(
                '✜ ʜᴇʟᴘ',
                callback_data="help",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            ),
            InlineKeyboardButton(
                '✜ ᴀʙᴏᴜᴛ',
                callback_data="about",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            )
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        user_mention = query.message.from_user.mention if query.message.from_user else "User"
        await safe_edit_message_text(
            query.message,
            text=script.START_TXT.format(user_mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup
        )
        await safe_answer_callback(query)
    elif data == "help":
        buttons = [[
            InlineKeyboardButton(
                '🍷 DᴀᴛᴀBᴀsᴇ Sᴛᴀᴛᴜs 🍷',
                callback_data="stats",
                style=ButtonStyle.PRIMARY,
                icon_custom_emoji_id=5215354932598350357
            )
        ],[
            InlineKeyboardButton(
                '☘ ᴀʙᴏᴜᴛ',
                callback_data="about",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            ),
            InlineKeyboardButton(
                '🏡 ʜᴏᴍᴇ',
                callback_data="start",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            )
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        user_mention = query.message.from_user.mention if query.message.from_user else "User"
        await safe_edit_message_text(
            query.message,
            text=script.HELP_TXT.format(user_mention),
            reply_markup=reply_markup
        )
        await safe_answer_callback(query)
    elif data == "about":
        buttons = [[
            InlineKeyboardButton(
                '🌐 Rᴇᴘᴏ 🌐',
                url="https://github.com/CyberTG",
                style=ButtonStyle.PRIMARY,
                icon_custom_emoji_id=5215354932598350357
            )
        ],[
            InlineKeyboardButton(
                '🕵‍♂ ʜᴇʟᴘ',
                callback_data="help",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            ),
            InlineKeyboardButton(
                '🏡 ʜᴏᴍᴇ',
                callback_data="start",
                style=ButtonStyle.DEFAULT,
                icon_custom_emoji_id=5215354932598350357
            )
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        user_mention = query.message.from_user.mention if query.message.from_user else "User"
        await safe_edit_message_text(
            query.message,
            text=script.ABOUT_TXT.format(user_mention),
            reply_markup=reply_markup
        )
        await safe_answer_callback(query)
    elif data == "stats":
        await safe_edit_message_text(query.message, "⏳Lᴏᴀᴅɪɴɢ sᴛᴀᴛɪsᴛɪᴄs...")
        await safe_answer_callback(query)
        
        tot1 = await Media2.count_documents()
        tot2 = await Media3.count_documents()
        total = tot1 + tot2
        users = await db.total_users_count()
        chats = await db.total_chat_count()

        try:
            stats_db1 = await clientDB.command('dbStats')
            used_dbSize1 = (stats_db1['dataSize'] / (1024 * 1024)) + (stats_db1['indexSize'] / (1024 * 1024))
        except Exception:
            used_dbSize1 = 0.0

        try:
            stats_db2 = await clientDB2.command('dbStats')
            used_dbSize2 = (stats_db2['dataSize'] / (1024 * 1024)) + (stats_db2['indexSize'] / (1024 * 1024))
        except Exception:
            used_dbSize2 = 0.0
        
        try:
            stats_db3 = await clientDB3.command('dbStats')
            used_dbSize3 = (stats_db3['dataSize'] / (1024 * 1024)) + (stats_db3['indexSize'] / (1024 * 1024))
        except Exception:
            used_dbSize3 = 0.0

        await safe_edit_message_text(
            query.message,
            text=script.STATUS_TXT.format(total, users, chats, used_dbSize1, used_dbSize2, used_dbSize3),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    '🏡 ʜᴏᴍᴇ',
                    callback_data='start',
                    style=ButtonStyle.DEFAULT,
                    icon_custom_emoji_id=5215354932598350357
                )
            ]]),
            parse_mode=enums.ParseMode.HTML
        )

async def reply_with_spell_check_suggestions(message, cyber, search):
    """Replies with fast spell check suggestions from SQLite DB when no search results are found."""
    if not message.from_user:
        return
    tracker = PerfTracker(action="spell_check", user_id=message.from_user.id, query=search)
    t0 = time.time()
    suggestions = await get_suggestions_sql(search)
    tracker.db_ms = (time.time() - t0) * 1000

    try:
        if suggestions:
            search_key = f"{message.from_user.id}_{message.id}"
            SEARCH_CACHE.set(f"spell_{search_key}", suggestions)
            
            btn = []
            i = 0
            while i < len(suggestions):
                s1 = suggestions[i]
                if len(s1) > 24 or (i + 1 < len(suggestions) and len(suggestions[i+1]) > 24):
                    btn.append([
                        InlineKeyboardButton(
                            text=f"🎬 {s1}",
                            callback_data=f"sp#{search_key}#{i}",
                            style=ButtonStyle.DEFAULT
                        )
                    ])
                    i += 1
                else:
                    row = [
                        InlineKeyboardButton(
                            text=f"🎬 {s1}",
                            callback_data=f"sp#{search_key}#{i}",
                            style=ButtonStyle.DEFAULT
                        )
                    ]
                    if i + 1 < len(suggestions):
                        s2 = suggestions[i + 1]
                        row.append(
                            InlineKeyboardButton(
                                text=f"🎬 {s2}",
                                callback_data=f"sp#{search_key}#{i+1}",
                                style=ButtonStyle.DEFAULT
                            )
                        )
                        i += 2
                    else:
                        i += 1
                    btn.append(row)
                    
            btn.append([
                InlineKeyboardButton(
                    "❌ Cʟᴏsᴇ",
                    callback_data="close_data",
                    style=ButtonStyle.DEFAULT
                )
            ])
            
            spell_text = script.SPELL_CHECK_TXT.format(cyber=cyber, search=search)
            t1 = time.time()
            GLOBAL_METRICS.inc("send_message")
            reply_msg = await message.reply_text(
                text=spell_text,
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.HTML
            )
            tracker.telegram_ms = (time.time() - t1) * 1000
            tracker.send_count = 1
            tracker.telegram_calls = 1
            await add_auto_delete_message(message.chat.id, reply_msg.id, temp.FILTER_DEL_TIME, msg_type="filter")
        else:
            t1 = time.time()
            GLOBAL_METRICS.inc("send_message")
            reply_msg = await message.reply(
                f"Hᴇʏ {cyber} 💫,\n"
                f"Nᴏ Sᴇᴀʀᴄʜ Rᴇꜱᴜʟᴛ Fᴏᴜɴᴅ Fᴏʀ Yᴏᴜʀ Rᴇᴏ̨ᴜᴇsᴛᴇᴅ Mᴏᴠɪᴇ.\n\n"
                f"➪ Sᴇɴᴅ Mᴇ A Cᴏʀʀᴇᴄᴛ Sᴘᴇʟʟɪɴɢ. Oʀ Pʟᴇᴀꜱᴇ Cʜᴇᴄᴋ Tʜᴀᴛ Mᴏᴠɪᴇ Oᴛᴛ Rᴇʟᴇᴇsᴇᴅ.✨"
            )
            tracker.telegram_ms = (time.time() - t1) * 1000
            tracker.send_count = 1
            tracker.telegram_calls = 1
            await add_auto_delete_message(message.chat.id, reply_msg.id, temp.FILTER_DEL_TIME, msg_type="filter")
    except FloodWait as e:
        logger.warning(f"FloodWait in reply_with_spell_check_suggestions: {e.value}s")
        GLOBAL_METRICS.inc("flood_wait_events")
        if e.value <= 3:
            await asyncio.sleep(e.value + 0.1)
    except Exception as e:
        logger.error(f"Error in reply_with_spell_check_suggestions: {e}")
    finally:
        tracker.log()

async def auto_filter(client, message):
    if not message.from_user:
        return
    cyber = message.from_user.mention
    search = message.text
    logger.debug(f"[auto_filter] user={message.from_user.id} search={search!r}")

    if len(search) < 2 or len(search) > 150:
        return

    tracker = PerfTracker(action="search_group", user_id=message.from_user.id, query=search)
    t0 = time.time()
    files, offset = await get_search_results(search, offset=0)
    tracker.db_ms = (time.time() - t0) * 1000

    if not files:
        tracker.log()
        await reply_with_spell_check_suggestions(message, cyber, search)
        return

    search_key = f"{message.from_user.id}_{message.id}"
    btn = generate_main_buttons(files, offset=0, search_key=search_key, next_offset=offset)
    
    try:
        t1 = time.time()
        GLOBAL_METRICS.inc("send_message")
        reply_msg = await message.reply_text(
            text=script.MAIN_RESULT_TXT.format(cyber=cyber, search=search, page=1),
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.HTML
        )
        tracker.telegram_ms = (time.time() - t1) * 1000
        tracker.send_count = 1
        tracker.telegram_calls = 1
        await add_auto_delete_message(message.chat.id, reply_msg.id, temp.FILTER_DEL_TIME, msg_type="filter")
    except FloodWait as e:
        logger.warning(f"FloodWait in auto_filter: {e.value}s")
        GLOBAL_METRICS.inc("flood_wait_events")
        if e.value <= 3:
            await asyncio.sleep(e.value + 0.1)
            try:
                GLOBAL_METRICS.inc("send_message")
                reply_msg = await message.reply_text(
                    text=script.MAIN_RESULT_TXT.format(cyber=cyber, search=search, page=1),
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML
                )
                await add_auto_delete_message(message.chat.id, reply_msg.id, temp.FILTER_DEL_TIME, msg_type="filter")
            except Exception as ex:
                logger.error(f"Error retrying auto_filter reply: {ex}")
    except Exception as e:
        logger.error(f"Error in auto_filter: {e}")
    finally:
        tracker.log()

    SEARCH_CACHE.set(search_key, search)

async def pm_auto_filter(client, message):
    if not message.from_user:
        return
    cyber = message.from_user.mention
    search = message.text
    logger.debug(f"[pm_auto_filter] user={message.from_user.id} search={search!r}")

    if len(search) < 2 or len(search) > 150:
        return

    tracker = PerfTracker(action="search_pm", user_id=message.from_user.id, query=search)
    t0 = time.time()
    files, offset = await get_search_results(search, offset=0)
    tracker.db_ms = (time.time() - t0) * 1000

    if not files:
        tracker.log()
        await reply_with_spell_check_suggestions(message, cyber, search)
        return

    search_key = f"{message.from_user.id}_{message.id}"
    btn = generate_main_buttons(files, offset=0, search_key=search_key, next_offset=offset)
 
    try:
        t1 = time.time()
        GLOBAL_METRICS.inc("send_message")
        reply_msg = await message.reply_text(
            text=script.MAIN_RESULT_TXT.format(cyber=cyber, search=search, page=1),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(btn),
        )
        tracker.telegram_ms = (time.time() - t1) * 1000
        tracker.send_count = 1
        tracker.telegram_calls = 1
        await add_auto_delete_message(message.chat.id, reply_msg.id, temp.FILTER_DEL_TIME, msg_type="filter")
    except FloodWait as e:
        logger.warning(f"FloodWait in pm_auto_filter: {e.value}s")
        GLOBAL_METRICS.inc("flood_wait_events")
        if e.value <= 3:
            await asyncio.sleep(e.value + 0.1)
            try:
                GLOBAL_METRICS.inc("send_message")
                reply_msg = await message.reply_text(
                    text=script.MAIN_RESULT_TXT.format(cyber=cyber, search=search, page=1),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(btn),
                )
                await add_auto_delete_message(message.chat.id, reply_msg.id, temp.FILTER_DEL_TIME, msg_type="filter")
            except Exception as ex:
                logger.error(f"Error retrying pm_auto_filter reply: {ex}")
    except Exception as e:
        logger.error(f"Error in pm_auto_filter: {e}")
    finally:
        tracker.log()

    SEARCH_CACHE.set(search_key, search)
    
async def global_filters(client, message):
    """Optimized global filter check using a cached regex pattern."""
    pattern = await get_gfilters_cached()
    if not pattern:
        return False
        
    match = pattern.search(message.text)
    if not match:
        return False
        
    keyword = match.group(1)
    reply_text, btn, alert, fileid = await find_gfilter('gfilters', keyword)
    
    if not reply_text and fileid == "None":
        return False

    try:
        markup = None
        if btn and btn != "[]":
            button_data = ast.literal_eval(btn)
            markup = InlineKeyboardMarkup(button_data) if button_data else None

        GLOBAL_METRICS.inc("send_message")
        if fileid == "None":
            sent = await client.send_message(message.chat.id, reply_text, reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=True))
        else:
            sent = await client.send_cached_media(message.chat.id, fileid, caption=reply_text or "", reply_markup=markup)
        if sent:
            await add_auto_delete_message(message.chat.id, sent.id, temp.FILTER_DEL_TIME, msg_type="filter")
        return True
    except Exception as e:
        logger.exception(f"Error processing global filter response: {e}")
        return False
