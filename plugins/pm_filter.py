import asyncio
import re
import ast
import time
import random
from datetime import datetime, timedelta
import logging

from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid, QueryIdInvalid
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto

from datetime import datetime, timedelta

from plugins.commands import schedule_message_deletion
from Script import script
from database.users_chats_db import db
from database.ia_filterdb import get_file_details, Media2, Media3, db as clientDB, db2 as clientDB2, db3 as clientDB3, fetch_mongo_ids_by_keyword
from database.gfilters_mdb import find_gfilter, get_gfilters
from info import ADMINS, CUSTOM_FILE_CAPTION, AUTO_DEL, MAX_FILES
from sql.db import get_search_results, delete_file_sql
from utils import get_size, temp, is_requested_one, is_requested_two, add_auto_delete_message

# --- Configuration ---
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DELETE_TXT = "🗑️ _This message and the file will be deleted in {} seconds._".format(AUTO_DEL)
GLOBAL_FILTER_CACHE = {}
CACHE_TTL = timedelta(minutes=5)

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
    if not temp.AUTO_FILTER: return
    if not await global_filters(client, message):
        await auto_filter(client, message)

@Client.on_message(filters.private & filters.text & filters.incoming & filters.regex(r'^(?!\/).*') & ~filters.forwarded)
async def auto_filter_pm_handler(client, message):
    """Handles non-command messages in private chat."""
    if not temp.AUTO_FILTER: 
        return
    if re.search(r'(?im)(?:https?://|www\.|t\.me/|telegram\.dog/)\S+|@[a-z0-9_]{5,32}\b', message.text):
        await message.delete()
        return
    if not await global_filters(client, message):
        await pm_auto_filter(client, message)
        
@Client.on_message(
    (filters.forwarded | filters.document | filters.photo | filters.video | 
     filters.audio | filters.voice | filters.video_note | 
     filters.sticker | filters.animation) & filters.private
)
async def delete_unwanted_messages(client, message):
    user_id = message.from_user.id
    if user_id in ADMINS: return # ignore admins
    await message.delete()
    
# --- Callback Handlers ---
@Client.on_callback_query(filters.regex(r"^next"))
async def next_page_cb(bot, query):
    _, search_key, offset = query.data.split("|")
    cyber = query.from_user.mention
    req = SEARCH_CACHE.get(search_key)
    if not req:
        await query.answer("🔁 Search expired or not found.", show_alert=True)
        return
    requested_user_id = int(search_key.split("_")[0])
    if query.from_user.id != requested_user_id:
        return await query.answer("✋ This is not for you! Please make your own search.", show_alert=True)
    
    offset = int(offset)
    files, next_offset = await get_search_results(req, offset=offset)
    
    if not files:
        return await query.answer("No more results found.", show_alert=True)
    btn = [
    [
        InlineKeyboardButton(
            text=f"🧸 {file['size']} 🌷 {file['file_name']}",
            callback_data=f"file#{file['file_id']}"
        ),
    ]
    for file in files
    ]
    btn.insert(0, [
        InlineKeyboardButton(text=f"🎬 {req} 🎬", callback_data="qinfo")
    ])
    btn.insert(1, [
        InlineKeyboardButton(text="📮Lᴀɴɢᴜᴀɢᴇs", callback_data="abc"),
        InlineKeyboardButton(text="Qᴜᴀʟɪᴛʏ 🎁", callback_data="efg")
    ])
    nav_buttons = []
    if offset-MAX_FILES >= 0:
        nav_buttons.append(InlineKeyboardButton("⏮ 𝗕𝗮𝗰𝗸", callback_data=f"next|{search_key}|{(offset - MAX_FILES)}"))
    if next_offset > offset + MAX_FILES:
        nav_buttons.append(InlineKeyboardButton("𝗡𝗲𝘅𝘁 ⏭", callback_data=f"next|{search_key}|{next_offset-1}"))
        
    if nav_buttons:
        btn.append(nav_buttons)

    try:
        current_page = (offset // MAX_FILES) + 1
        await query.edit_message_text(
            f"𝗛𝗘𝗬👋 {cyber} 🫶\n\n📁𝙌𝙪𝙚𝙧𝙮 : {req}\n\n🗂️𝑷𝒂𝒈𝒆 𝑵𝒐 › `{current_page}`\n\n✍️ 𝙉𝙊𝙏𝙀 : ⚠️𝙏𝙝𝙞𝙨 𝙈𝙚𝙨𝙨𝙖𝙜𝙚 𝙒𝙞𝙡𝙡 𝘽𝙚 𝘼𝙪𝙩𝙤-𝙙𝙚𝙡𝙚𝙩𝙚𝙙 𝙒𝙞𝙩𝙝𝙞𝙣 15 𝙈𝙞𝙣𝙨..❗️\n ©𝒸ᵧᵦₑᵣₜ𝓰🗡️",
            reply_markup=InlineKeyboardMarkup(btn)
        )
    except MessageNotModified:
        pass
    await query.answer()
    

@Client.on_callback_query()
async def main_cb_handler(client: Client, query: CallbackQuery):
    data = query.data
    
    if data == "close_data":
        await query.message.delete()

    elif data.startswith("file#"):
        _, file_id = data.split("#")
        try:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start=file_{file_id}")
        except (UserIsBlocked, PeerIdInvalid):
            await query.answer("Bot blocked or not started! Please start the bot in private first.", url=f"https://t.me/{temp.U_NAME}?start=file_{file_id}", show_alert=True)
        except QueryIdInvalid:
            await query.answer("This request has expired. Please search again.", show_alert=True)
        except Exception as e:
            logger.error(e)
            await query.answer("An unexpected error occurred.", show_alert=True)

    elif data.startswith("checksub#"):
        ident, file_id = data.split("#")
        
        # Improved force-sub logic
        unjoined_channels = []
        if temp.REQ_CHANNEL1 and not await is_requested_one(client, query):
            unjoined_channels.append("first")
        if temp.REQ_CHANNEL2 and not await is_requested_two(client, query):
            unjoined_channels.append("second")

        if unjoined_channels:
            channel_text = ' and '.join(unjoined_channels)
            return await query.answer(f"🚨 Please join the {channel_text} channel(s) to get this movie, then try again.", show_alert=True)

        files = await get_file_details(file_id)
        if not files:
            return await query.answer('⚠️ File not found or has been removed.', show_alert=True)
        
        await query.answer("✅ Checking complete. Sending file...", show_alert=False)
        
        try:
            sent_msg = await client.send_cached_media(
                chat_id=query.from_user.id,
                file_id=file_id,
                caption=get_file_caption(files[0]),
                protect_content=(ident == "checksubp"),
                parse_mode=enums.ParseMode.MARKDOWN
            )
            delete_reply = await query.message.reply(DELETE_TXT, reply_to_message_id=sent_msg.id, parse_mode=enums.ParseMode.MARKDOWN)
            
            # Efficiently delete all related messages after timeout
            await asyncio.sleep(AUTO_DEL)
            await asyncio.gather(delete_reply.delete(), query.message.delete(), sent_msg.delete(), return_exceptions=True)
            
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await query.answer(f"Flood control: Please wait {e.value} seconds.", show_alert=True)
        except Exception as e:
            logger.error(e)
            await query.answer(f"An error occurred while sending the file.", show_alert=True)

    elif data.startswith("killfilesdq#"):
        _, keyword = data.split("#")
        msg = await query.message.edit_text(f"🔎 **Step 1/3: Fetching all file IDs for** `{keyword}`**. Please wait...**")
    
        try:
            # Step 1: Fetch all unique file IDs from MongoDB
            unique_ids_to_delete = await fetch_mongo_ids_by_keyword(keyword)
            
            if not unique_ids_to_delete:
                return await msg.edit_text(f"✅ No files found matching `{keyword}` across all databases.")
            
            total_found = len(unique_ids_to_delete)
            
            await msg.edit_text(f"🗑️ **Step 2/3: Deleting `{total_found}` files from MongoDB collections...**")
    
            # Step 2: Delete from all MongoDB collections
            mongo_deleted_count = 0
    
            await msg.edit_text(f"🗃️ **Step 3/3: Deleting `{total_found}` files from SQLite database...**")
    
            # Step 3: Delete from SQLite database
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
        await query.answer("Tʜɪs ғᴇᴀᴛᴜʀᴇ ᴡɪʟʟ ʙᴇ ᴀᴅᴅ sᴏᴏɴ 😉", show_alert=True)
    elif query.data == "efg":
        await query.answer("Tʜɪs ғᴇᴀᴛᴜʀᴇ ᴡɪʟʟ ʙᴇ ᴀᴅᴅ sᴏᴏɴ 😉", show_alert=True)

    elif data == "start":
        buttons = [[
            InlineKeyboardButton('➜ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ➜', url=f'http://t.me/{temp.U_NAME}?startgroup=true')
        ],[
            InlineKeyboardButton("⭐ Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ Fᴏʀ Cᴏᴍᴘʟᴀɪɴᴛ ⭐", url=f'https://t.me/AboutCyberTG')
        ],[
            InlineKeyboardButton('✜ ʜᴇʟᴘ', callback_data="help"),
            InlineKeyboardButton('✜ ᴀʙᴏᴜᴛ', callback_data="about")
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.START_TXT.format(query.message.from_user.mention if query.message.from_user else "User"),
            reply_markup=reply_markup
        )
    elif data == "help":
        buttons = [[
            InlineKeyboardButton('🍷 DᴀᴛᴀBᴀsᴇ Sᴛᴀᴛᴜs 🍷', callback_data="stats")
        ],[
            InlineKeyboardButton('☘ ᴀʙᴏᴜᴛ', callback_data="about"),
            InlineKeyboardButton('🏡 ʜᴏᴍᴇ', callback_data="start")
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.HELP_TXT.format(query.message.from_user.mention if query.message.from_user else "User"),
            reply_markup=reply_markup
        )
    elif data == "about":
        print("about")
        buttons = [[
            InlineKeyboardButton('🌐 Rᴇᴘᴏ 🌐', url=f"https://github.com/CyberTG")
        ],[
            InlineKeyboardButton('🕵‍♂ ʜᴇʟᴘ', callback_data="help"),
            InlineKeyboardButton('🏡 ʜᴏᴍᴇ', callback_data="start")
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.ABOUT_TXT.format(query.message.from_user.mention if query.message.from_user else "User"),
            reply_markup=reply_markup
        )
    elif data == "stats":
        await query.message.edit_text("⏳Lᴏᴀᴅɪɴɢ sᴛᴀᴛɪsᴛɪᴄs...")
        
        tot1 = await Media2.count_documents()
        tot2 = await Media3.count_documents()
        total = tot1 + tot2
        users = await db.total_users_count()
        chats = await db.total_chat_count()

    # Calculate DB sizes
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
        await query.message.edit_text(
            text=script.STATUS_TXT.format(total, users, chats, used_dbSize1, used_dbSize2, used_dbSize3),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🏡 ʜᴏᴍᴇ', callback_data='start')]]),
            parse_mode=enums.ParseMode.HTML
        )

async def auto_filter(client, message):
    search = message.text
    cyber = message.from_user.mention
    if len(search) < 2 or len(search) > 150:
        return
    files, offset = await get_search_results(search)
    if not files:
        spellbtn = [[InlineKeyboardButton(f"🔎 ᴄʜᴇᴄᴋ sᴘᴇʟʟɪɴɢ ᴏɴ ɢᴏᴏɢʟᴇ 🔍", url=f"https://google.com/search?q={search}")]] 
        sent_message = await message.reply_text(f"Hᴇʏ {cyber} 💐,\nNᴏ Sᴇᴀʀᴄʜ Rᴇꜱᴜʟᴛ Fᴏᴜɴᴅ Fᴏʀ Yᴏᴜʀ Qᴜᴇʀʏ <u>{search}</u>.\n\n➪ Sᴇɴᴅ Mᴇ A Cᴏʀʀᴇᴄᴛ Sᴘᴇʟʟɪɴɢ. Oʀ Pʟᴇᴀꜱᴇ Cʜᴇᴄᴋ Tʜᴀᴛ Mᴏᴠɪᴇ Oᴛᴛ Rᴇʟᴇᴀꜱᴇᴅ.✨", reply_markup=InlineKeyboardMarkup(spellbtn), quote=True)
        await add_auto_delete_message(sent.id, sent.chat.id, 30)
        return

    user_id = message.from_user.id
    btn = [
    [
        InlineKeyboardButton(
            text=f"🧸 {file['size']} 🌷 {file['file_name']}",
            callback_data=f"file#{file['file_id']}"
        ),
    ]
    for file in files
    ]
    btn.insert(0, [
        InlineKeyboardButton(text=f"🎬 {search} 🎬", callback_data="qinfo")
    ])
    btn.insert(1, [
        InlineKeyboardButton(text="📮Lᴀɴɢᴜᴀɢᴇs", callback_data="abc"),
        InlineKeyboardButton(text="Qᴜᴀʟɪᴛʏ 🎁", callback_data="efg")
    ])
    search_key = f"{message.from_user.id}_{message.id}"
    if offset:
        btn.append([
            InlineKeyboardButton("𝗡𝗲𝘅𝘁 ⏭", callback_data=f"next|{search_key}|{offset}")
        ])
        caption = f" 𝗛𝗘𝗬👋 {cyber} 🫶\n\n📁𝙌𝙪𝙚𝙧𝙮 : {search}\n\n🗂️𝑷𝒂𝒈𝒆 𝑵𝒐 › `1`\n\n✍️ 𝙉𝙊𝙏𝙀 : ⚠️𝙏𝙝𝙞𝙨 𝙈𝙚𝙨𝙨𝙖𝙜𝙚 𝙒𝙞𝙡𝙡 𝘽𝙚 𝘼𝙪𝙩𝙤-𝙙𝙚𝙡𝙚𝙩𝙚𝙙 𝙒𝙞𝙩𝙝𝙞𝙣 15 𝙈𝙞𝙣𝙨..❗️\n ©𝒸ᵧᵦₑᵣₜ𝓰🗡️"
        sent_message = await message.reply_text(
            caption,
            reply_markup=InlineKeyboardMarkup(btn),
            quote=True
        )
        SEARCH_CACHE.set(search_key, search)
        await add_auto_delete_message(sent_message.id, sent_message.chat.id, AUTO_DEL)

async def pm_auto_filter(client, message):
    search = message.text
    cyber = message.from_user.mention
    if len(search) < 2 or len(search) > 150:
        return
    files, offset = await get_search_results(search)
    if not files:
        spellbtn = [[InlineKeyboardButton(f"🔎 ᴄʜᴇᴄᴋ sᴘᴇʟʟɪɴɢ ᴏɴ ɢᴏᴏɢʟᴇ 🔍", url=f"https://google.com/search?q={search}")]] 
        sent_message = await message.reply(f"Hᴇʏ {cyber} 💐,\nNᴏ Sᴇᴀʀᴄʜ Rᴇꜱᴜʟᴛ Fᴏᴜɴᴅ Fᴏʀ Yᴏᴜʀ Qᴜᴇʀʏ <u>{search}</u>.\n\n➪ Sᴇɴᴅ Mᴇ A Cᴏʀʀᴇᴄᴛ Sᴘᴇʟʟɪɴɢ. Oʀ Pʟᴇᴀꜱᴇ Cʜᴇᴄᴋ Tʜᴀᴛ Mᴏᴠɪᴇ Oᴛᴛ Rᴇʟᴇᴀꜱᴇᴅ.✨", reply_markup=InlineKeyboardMarkup(spellbtn), quote=True)
        schedule_message_deletion(client, sent_message, delay_seconds=15)
        return

    user_id = message.from_user.id
    buttons = [[InlineKeyboardButton(f"🧸 {file['size']} 🌷 {file['file_name']}", callback_data=f"file#{file['file_id']}")] for file in files]

    search_key = f"{message.from_user.id}_{message.id}"
    if offset > MAX_FILES:
        buttons.append([InlineKeyboardButton("𝗡𝗲𝘅𝘁 ⏭", callback_data=f"next|{search_key}|{offset-1}")])
    caption = f"𝗛𝗘𝗬👋 {cyber} 🫶\n\n📁𝙌𝙪𝙚𝙧𝙮 : {search}\n\n🗂️𝑷𝒂𝒈𝒆 𝑵𝒐 › `1`\n\n✍️ 𝙉𝙊𝙏𝙀 : ⚠️𝙏𝙝𝙞𝙨 𝙈𝙚𝙨𝙨𝙖𝙜𝙚 𝙒𝙞𝙡𝙡 𝘽𝙚 𝘼𝙪𝙩𝙤-𝙙𝙚𝙡𝙚𝙩𝙚𝙙 𝙒𝙞𝙩𝙝𝙞𝙣 15 𝙈𝙞𝙣𝙨..❗️\n ©𝒸ᵧᵦₑᵣₜ𝓰 🗡️"

    sent_message = await message.reply_text(caption, reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    SEARCH_CACHE.set(search_key, search)
    schedule_message_deletion(client, sent_message, delay_seconds=AUTO_DEL)
    
async def global_filters(client, message):
    """Optimized global filter check using a cached regex pattern."""
    pattern = await get_gfilters_cached()
    if not pattern:
        return False
        
    match = pattern.search(message.text)
    if not match:
        return False
        
    keyword = match.group(1) # The matched keyword
    reply_text, btn, alert, fileid = await find_gfilter('gfilters', keyword)
    
    if not reply_text and fileid == "None":
        return False

    try:
        markup = None
        if btn and btn != "[]":
            button_data = ast.literal_eval(btn)
            markup = InlineKeyboardMarkup(button_data) if button_data else None

        if fileid == "None":
            await client.send_message(message.chat.id, reply_text, reply_markup=markup, disable_web_page_preview=True)
        else:
            await client.send_cached_media(message.chat.id, fileid, caption=reply_text or "", reply_markup=markup)
        return True
    except Exception as e:
        logger.error(f"Error processing global filter response: {e}")
        return False
