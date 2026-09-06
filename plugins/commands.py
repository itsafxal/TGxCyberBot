import os
import sys
import logging
import asyncio
import random
import base64
import json
from datetime import datetime, timedelta
from pyrogram import Client, filters, enums
from pyrogram.errors import InputUserDeactivated, FloodWait, UserIsBlocked
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from Script import script
from database.ia_filterdb import Media2, Media3, get_file_details, unpack_new_file_id
from database.users_chats_db import db
from info import ADMINS, LOG_CHANNEL, CUSTOM_FILE_CAPTION, AUTO_DEL, PICS, PROTECT_CONTENT
from utils import get_size, is_requested_one, is_requested_two, is_requested_three, temp, check_loop_sub, check_loop_sub1, check_loop_sub2, check_loop_sub3, get_stream_buttons, get_stream_buttons_async, build_dynamic_fsub_keyboard, check_loop_sub_dynamic, safe_b64decode
from sql.db import delete_all_files_sql, delete_file_sql, get_search_results

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DELETE_TXT = "📁 𝗪𝗮𝗿𝗻𝗶𝗻𝗴 ⚠️\n\n<blockquote>Please note that this movie file will be deleted in 15 minutes to avoid Copyright. To keep it, forward it to a friend or save it to your personal space.</blockquote>"

async def send_log_report(client, user, item, report_type):
    """Sends a formatted report (bug/request) directly to ADMINS in bot DM."""
    header = "#BugReport" if report_type == "bug" else "#Request"
    item_label = "Description" if report_type == "bug" else "Requested Item"

    user_mention = user.mention if user else "Unknown"
    user_id = user.id if user else "Unknown"
    user_info = f"**User:** {user_mention}\n**User ID:** `{user_id}`"
    report_message = f"{header}\n\n**{item_label}:** {item}\n\n{user_info}"

    sent = False
    for admin in ADMINS:
        try:
            await client.send_message(chat_id=admin, text=report_message)
            sent = True
        except Exception as e:
            logger.error(f"Failed to send {report_type} to admin {admin} DM: {e}")

    if not sent and LOG_CHANNEL:
        try:
            await client.send_message(chat_id=LOG_CHANNEL, text=report_message)
            sent = True
        except Exception as e:
            logger.error(f"Failed to send {report_type} to log channel: {e}")
    return sent

async def auto_delete_message(message, delay_seconds):
    """Deletes a message after a specified delay."""
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Failed to auto-delete message {message.id}: {e}")

def schedule_message_deletion(bot, message, delay_seconds=5):
    """
    Schedule deletion of a message after a delay, using bot.loop.
    """
    delete_time = datetime.now() + timedelta(seconds=delay_seconds)

    async def delete_later():
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete message {message.id}: {e}")

    # Use run_coroutine_threadsafe with the bot's event loop
    bot.schedule.add_job(
        lambda: asyncio.run_coroutine_threadsafe(delete_later(), bot.loop),
        trigger='date',
        run_date=delete_time,
        id=f"delete_{message.chat.id}_{message.id}",
        misfire_grace_time=200
    )

def schedule_message_deletion2(bot, message, delay_seconds=5):
    """
    Schedule deletion of a message after a delay, using bot.loop.
    """
    delete_time = datetime.now() + timedelta(seconds=delay_seconds)

    async def delete_later():
        try:
            await message.reply("𝗬𝗼𝘂𝗿 𝗙𝗶𝗹𝗲 𝗛𝗮𝘀 𝗕𝗲𝗲𝗻 𝗗𝗲𝗹𝗲𝘁𝗲𝗱 𝗧𝗼 𝗔𝘃𝗼𝗶𝗱 𝗕𝗢𝗧 𝗕𝗮𝗻.\n\n𝗬𝗼𝘂 𝗖𝗮𝗻 𝗥𝗲𝗾𝘂𝗲𝘀𝘁 𝗔𝗴𝗮𝗶𝗻 𝗜𝗳 𝗬𝗼𝘂 𝗪𝗮𝗻𝘁! 🫵")
            await message.delete()
        except InputUserDeactivated:
            return
        except UserIsBlocked:
            return
        except Exception as e:
            logger.warning(f"Failed to delete message {message.id}: {e}")

    # Use run_coroutine_threadsafe with the bot's event loop
    bot.schedule.add_job(
        lambda: asyncio.run_coroutine_threadsafe(delete_later(), bot.loop),
        trigger='date',
        run_date=delete_time,
        id=f"delete_{message.chat.id}_{message.id}",
        misfire_grace_time=200
    )

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    chat_type = message.chat.type
    user_id = message.from_user.id if message.from_user else None
    chat_id = message.chat.id

    if chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        buttons = [[
            InlineKeyboardButton('➜ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ➜', url=f'http://t.me/{temp.U_NAME}?startgroup=true')
        ],[
            InlineKeyboardButton("⭐ Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ Fᴏʀ Cᴏᴍᴘʟᴀɪɴᴛ ⭐", url='https://cybertg.vercel.app')
        ],[
            InlineKeyboardButton('✜ ʜᴇʟᴘ', callback_data='help'),
            InlineKeyboardButton('✜ ᴀʙᴏᴜᴛ', callback_data='about')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply(script.START_TXT.format(message.from_user.mention if user_id else message.chat.title, temp.B_NAME), reply_markup=reply_markup)
        if not await db.get_chat(chat_id):
            total = await client.get_chat_members_count(chat_id)
            group_log = script.LOG_TEXT_G.format(message.chat.title, chat_id, total, "Unknown")
            for admin in ADMINS:
                try:
                    await client.send_message(admin, group_log)
                except Exception:
                    pass
            await db.add_chat(chat_id, message.chat.title)
        return

    if user_id and not await db.is_user_exist(user_id):
        name = message.from_user.first_name if (message.from_user and message.from_user.first_name) else "User"
        await db.add_user(user_id, name)

    username = message.from_user.username or "No Username" if message.from_user else "No Username"
    if not temp.B_NAME:
        me = await client.get_me()
        temp.B_NAME = me.username
    bot_username = temp.B_NAME

    if len(message.command) != 2:
        buttons = [[
            InlineKeyboardButton('➜ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ➜', url=f'http://t.me/{temp.U_NAME}?startgroup=true')
        ],[
            InlineKeyboardButton("⭐ Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ Fᴏʀ Cᴏᴍᴘʟᴀɪɴᴛ ⭐", url='https://cybertg.vercel.app')
        ],[
            InlineKeyboardButton('✜ ʜᴇʟᴘ', callback_data='help'),
            InlineKeyboardButton('✜ ᴀʙᴏᴜᴛ', callback_data='about')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=script.START_TXT.format(message.from_user.mention if user_id else "User", temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        return

    try:
        file_arg = message.command[1] if len(message.command) > 1 and message.command[1] != "subscribe" else None
        reply_markup, unjoined_channels = await build_dynamic_fsub_keyboard(client, message.from_user.id, file_id=file_arg)

        if unjoined_channels:
            sh = await client.send_message(
                chat_id=message.from_user.id,
                text='**Pʟᴇᴀꜱᴇ Jᴏɪɴ Oᴜʀ Cʜᴀɴɴᴇʟs Tᴏ Gᴇᴛ Yᴏᴜʀ Rᴇǫᴜᴇꜱᴛᴇᴅ Mᴏᴠɪᴇ Fɪʟᴇ 🚀**',
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )

            check = await check_loop_sub_dynamic(client, message, file_id=file_arg, prompt_msg=sh)
            if check:
                try:
                    await sh.delete()
                except Exception:
                    pass
            else:
                return

    except (UserIsBlocked, InputUserDeactivated):
        logger.info(f"User {user_id} blocked the bot during start fsub check.")
        return
    except Exception as e:
        logger.error(f"Error in start command fsub check: {e}")

    if len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
        buttons = [[
            InlineKeyboardButton('➜ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ➜', url=f'http://t.me/{temp.U_NAME}?startgroup=true')
        ],[
            InlineKeyboardButton("⭐ Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ Fᴏʀ Cᴏᴍᴘʟᴀɪɴᴛ ⭐", url='https://t.me/CyberTGx')
        ],[
            InlineKeyboardButton('✜ ʜᴇʟᴘ', callback_data='help'),
            InlineKeyboardButton('✜ ᴀʙᴏᴜᴛ', callback_data='about')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=script.START_TXT.format(message.from_user.mention if user_id else "User", temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        return

    data = message.command[1]
    if data.startswith("getfile-"):
        query_raw = data.replace("getfile-", "").replace("-", " ").strip()
        files, offset = await get_search_results(query_raw, offset=0)
        if not files:
            words = query_raw.split()
            if len(words) > 1:
                files, offset = await get_search_results(words[0], offset=0)
                if files:
                    query_raw = words[0]

        from plugins.pm_filter import SEARCH_CACHE, generate_main_buttons, reply_with_spell_check_suggestions
        if files:
            cyber = message.from_user.mention
            search_key = f"{message.from_user.id}_{message.id}"
            btn = generate_main_buttons(files, offset, search_key)
            SEARCH_CACHE.set(search_key, query_raw)
            return await message.reply_text(
                text=script.MAIN_RESULT_TXT.format(cyber=cyber, search=query_raw, page=1),
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await reply_with_spell_check_suggestions(message, message.from_user.mention if user_id else "User", query_raw)
            return

    try:
        prefix, file_id = data.split('_', 1)
    except ValueError:
        file_id = data
        prefix = ""

    if data.startswith("BATCH-"):
        sts = await message.reply("Please wait")
        file_path = None
        try:
            file_id = data.split("BATCH-", 1)[1]
            file_path = await client.download_media(file_id)
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                file_list = json.load(f)
        except Exception as e:
            logger.error(f"BATCH file load failed: {e}")
            return await sts.edit("❌ Failed to load batch file.")
        finally:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

        for msg in file_list:
            try:
                title = msg.get("title", "File")
                size = get_size(int(msg.get("size", 0)))
                caption = msg.get("caption", "") or title
                if CUSTOM_FILE_CAPTION:
                    try:
                        caption = CUSTOM_FILE_CAPTION.format(
                            file_name=title, file_size=size, file_caption=caption
                        )
                    except Exception as ce:
                        logger.warning(f"Caption formatting error: {ce}")

                stream_markup = await get_stream_buttons_async(file_id=msg.get("file_id"), file_name=title)
                ok = await client.send_cached_media(
                    chat_id=message.chat.id,
                    file_id=msg.get("file_id"),
                    caption=caption,
                    protect_content=msg.get("protect", False),
                    reply_markup=stream_markup
                )
                #schedule_message_deletion(client, ok, delay_seconds=AUTO_DEL)
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Failed to send file: {e}")
                continue

        return await sts.delete()
    if data.startswith("DSTORE-"):
        sts = await message.reply("Please wait")
        try:
            b_string = data.split("DSTORE-", 1)[1]
            decoded = safe_b64decode(b_string)
            if not decoded:
                return await sts.edit("❌ Invalid DSTORE link.")
            try:
                f_msg_id, l_msg_id, f_chat_id, protect = decoded.split("_", 3)
            except ValueError:
                f_msg_id, l_msg_id, f_chat_id = decoded.split("_", 2)
                protect = "/pbatch" if PROTECT_CONTENT else "batch"

            f_msg_id, l_msg_id, f_chat_id = int(f_msg_id), int(l_msg_id), int(f_chat_id)
        except Exception as e:
            logger.warning(f"DSTORE decode error: {e}")
            return await sts.edit("❌ Invalid DSTORE link.")

        for i in range(f_msg_id, l_msg_id + 1, 100):
            ids = list(range(i, min(i + 100, l_msg_id + 1)))
            try:
                msgs = await client.get_messages(f_chat_id, ids)
            except Exception as e:
                logger.warning(f"Failed to fetch messages: {e}")
                continue

            for msg in msgs:
                if not msg or msg.empty or not msg.media:
                    continue
                try:
                    media = getattr(msg, msg.media.value)
                    title = getattr(media, 'file_name', '')
                    size = get_size(getattr(media, 'file_size', 0))
                    caption = getattr(msg, 'caption', title)

                    if CUSTOM_FILE_CAPTION:
                        try:
                            caption = CUSTOM_FILE_CAPTION.format(
                                file_name=title, file_size=size, file_caption=caption
                            )
                        except Exception as ce:
                            logger.warning(f"Caption format fail: {ce}")

                    stream_markup = await get_stream_buttons_async(file_name=title)
                    ok = await msg.copy(
                        chat_id=message.chat.id,
                        caption=caption,
                        protect_content=(protect == "/pbatch"),
                        reply_markup=stream_markup
                    )
                    #schedule_message_deletion(client, ok, delay_seconds=AUTO_DEL)
                    await asyncio.sleep(1)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                except Exception as e:
                    logger.warning(f"Send fail: {e}")
                    continue

        return await sts.delete()

    files_ = await get_file_details(file_id)
    if not files_:
        try:
            decoded = safe_b64decode(data)
            if not decoded:
                return await message.reply("❌ This file may be expired or invalid.")
            if "_" in decoded:
                prefix, file_id = decoded.split("_", 1)
            else:
                prefix, file_id = "", decoded
            try:
                msg = await client.send_cached_media(
                    chat_id=user_id,
                    file_id=file_id,
                    protect_content=(prefix == "filep"),
                    reply_markup=get_stream_buttons(file_id)
                )
                media = getattr(msg, msg.media.value)
                title = getattr(media, "file_name", "Untitled")
                size = get_size(getattr(media, "file_size", 0))
                caption = f"<code>{title}</code>"

                if CUSTOM_FILE_CAPTION:
                    try:
                        caption = CUSTOM_FILE_CAPTION.format(
                            file_name=title,
                            file_size=size,
                            file_caption=""
                        )
                    except Exception as ce:
                        logger.warning(f"Caption formatting failed: {ce}")
 
                stream_markup = await get_stream_buttons_async(file_id=file_id, file_name=title)
                await msg.edit_caption(caption, reply_markup=stream_markup)
                return
            except (UserIsBlocked, InputUserDeactivated):
                logger.info(f"User {user_id} blocked bot or deactivated account.")
                return
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                logger.error(f"Error sending file: {e}")
                return await message.reply("❌ Failed to send the file.")
        except Exception as e:
            logger.warning(f"Error in file/batch handler: {e}")
            return await message.reply("❌ This file may be expired or invalid.")

    files = files_[0]
    title = files.file_name
    size = get_size(files.file_size)
    f_caption=files.caption
    if CUSTOM_FILE_CAPTION:
        try:
            f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='' if f_caption is None else f_caption)
        except Exception as e:
            logger.exception(e)
            f_caption=f_caption
    if f_caption is None:
        f_caption = f"{files.file_name}"

    try:
        stream_markup = await get_stream_buttons_async(file_id=file_id, file_name=title)
        ok = await client.send_cached_media(
            chat_id=user_id,
            file_id=file_id,
            caption=f_caption,
            protect_content=True if prefix == 'filep' else False,
            reply_markup=stream_markup
        )
    except (UserIsBlocked, InputUserDeactivated):
        logger.info(f"User {user_id} blocked bot or deactivated account when sending cached media.")
    except FloodWait as e:
        logger.warning(f"FloodWait when sending media to user {user_id}: {e.value}s")
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"Error sending cached media: {e}")


@Client.on_message(filters.command(["reportbug", "request"]))
async def report_or_request_command(client, message):
    """Handles both /reportbug and /request commands."""
    if len(message.command) < 2:
        return await message.reply_text("Please provide a description after the command.")

    command_type = "bug" if message.command[0] == "reportbug" else "request"
    item_description = " ".join(message.command[1:])

    if await send_log_report(client, message.from_user, item_description, command_type):
        reply_text = "🐛 Your bug report has been sent." if command_type == "bug" else "📝 Your request has been sent."
        await message.reply_text(reply_text + " Thank you!")
    else:
        await message.reply_text("❌ An error occurred while sending your report. Please try again later.")


@Client.on_message(filters.command("delete_duplicate") & filters.user(ADMINS))
async def delete_duplicate_files(client, message):
    try:
        status = await message.reply("🔄 Starting duplicate deletion process...")
        deleted_count = 0
        batch_size = 0
        BATCH_LIMIT = 1000
        collections = [Media2, Media3]
        unique_files = {}
        await status.edit("🔍 Scanning for unique files...")
        async def build_unique_files(collection_model):
            skip = 0
            while True:
                docs = await collection_model.collection.find({}, {"file_id": 1, "file_size": 1}).skip(skip).limit(BATCH_LIMIT).to_list(length=None)
                if not docs:
                    break
                for doc in docs:
                    file_id = doc.get("file_id") or doc.get("_id")
                    file_size = doc.get("file_size")
                    if file_size and file_id and file_size not in unique_files:
                        unique_files[file_size] = file_id
                skip += BATCH_LIMIT
                await asyncio.sleep(0.01)
        for col in collections:
            await build_unique_files(col)
        if not unique_files:
            await status.edit("⚠️ No files found in collections.")
            return
        await status.edit("🗑️ Starting duplicate deletion...")
        async def delete_duplicates(collection_model):
            nonlocal deleted_count, batch_size
            skip = 0
            while True:
                docs = await collection_model.collection.find({}, {"file_id": 1, "file_size": 1}).skip(skip).limit(BATCH_LIMIT).to_list(length=None)
                if not docs:
                    break
                for doc in docs:
                    file_id = doc.get("file_id") or doc.get("_id")
                    file_size = doc.get("file_size")
                    if file_size in unique_files and unique_files[file_size] != file_id:
                        await collection_model.collection.delete_one({"_id": file_id})
                        deleted_count += 1
                        if deleted_count % 100 == 0:
                            batch_size += 1
                            await status.edit(f"🗑️ Deleted {deleted_count} files in {batch_size} batches...")
                            await asyncio.sleep(0.05)
                skip += BATCH_LIMIT
                await asyncio.sleep(0.01)
        for col in collections:
            await delete_duplicates(col)
        if deleted_count == 0:
            await status.edit("✅ No duplicates found. Database is clean.")
        else:
            await status.edit(f"✅ Deleted {deleted_count} duplicates in {batch_size} batches.")
    except Exception as e:
        logger.exception("Error during delete_duplicate_files")
        await message.reply(f"❌ Error occurred:\n<code>{str(e)}</code>")

@Client.on_message(filters.command('update') & filters.user(ADMINS))
async def restart(b, m):
    try:
        if os.path.exists(".git"):
            os.system("git pull")
    except Exception as e:
        await m.reply_text(f"Error during git pull: {e}")

    restart_message = await m.reply_text("Restarting...")
    try:
        os.remove("TelegramBot.txt")
    except FileNotFoundError:
        pass
    except Exception as e:
        await m.reply_text(f"Error removing TelegramBot.txt: {e}")

    os.execl(sys.executable, sys.executable, "bot.py")

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    # Use the walrus operator (:=) to check for and assign variables in one line
    if not (reply := message.reply_to_message) or not (media := reply.document or reply.video or reply.audio):
        return await message.reply('Reply to a file with /delete.')

    msg = await message.reply("Processing...⏳")
    try:
        file_id, _ = unpack_new_file_id(media.file_id)
        deleted_from = []

        # Attempt to delete from each database, adding successes to a list
        try:
            if await delete_file_sql(file_id):
                deleted_from.append("SQL")
        except Exception as e:
            logger.error(f"SQL delete failed: {e}")

        try:
            result = await Media2.collection.delete_one({'_id': file_id})
            if result.deleted_count:
                deleted_from.append("MongoDB")
        except Exception as e:
            logger.error(f"MongoDB delete failed: {e}")

        try:
            result = await Media3.collection.delete_one({'_id': file_id})
            if result.deleted_count:
                deleted_from.append("MongoDB")
        except Exception as e:
            logger.error(f"MongoDB delete failed: {e}")
            
        # Report the final status based on the list contents
        if deleted_from:
            status = f"✅ Successfully deleted from: **{', '.join(deleted_from)}**."
        else:
            status = "⚠️ File not found or failed to delete from any database."
        await msg.edit(status)

    except Exception as e:
        logger.error(f"Delete command error: {e}")
        await msg.edit(f"❌ An unexpected error occurred: `{e}`")

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    try:
        keyword = message.text.split(None, 1)[1]
    except IndexError:
        mention = message.from_user.mention if message.from_user else "Admin"
        return await message.reply_text(f"<b>Hᴇʏ {mention}, Gɪᴠᴇ ᴍᴇ ᴀ ᴋᴇʏᴡᴏʀᴅ ᴀʟᴏɴɢ ᴡɪᴛʜ ᴛʜᴇ ᴄᴏᴍᴍᴀɴᴅ ᴛᴏ ᴅᴇʟᴇᴛᴇ ғɪʟᴇs.</b>")
    btn = [[InlineKeyboardButton("Yᴇs, Cᴏɴᴛɪɴᴜᴇ !", callback_data=f"killfilesdq#{keyword}")],
           [InlineKeyboardButton("Nᴏ, Aʙᴏʀᴛ ᴏᴘᴇʀᴀᴛɪᴏɴ !", callback_data="close_data")]]
    await message.reply_text(
        text="<b>Aʀᴇ ʏᴏᴜ sᴜʀᴇ? Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ?\n\nNᴏᴛᴇ:- Tʜɪs ᴄᴏᴜʟᴅ ʙᴇ ᴀ ᴅᴇsᴛʀᴜᴄᴛɪVE ᴀᴄᴛɪᴏɴ!</b>",
        reply_markup=InlineKeyboardMarkup(btn),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_index(bot, message):
    await message.reply_text(
        'This will delete all indexed files.\nDo you want to continue??',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="YES", callback_data="autofilter_delete")],
                                            [InlineKeyboardButton(text="CANCEL", callback_data="close_data")]]),
        
    )

@Client.on_callback_query(filters.regex(r'^autofilter_delete'))
async def delete_all_index_confirm(bot, message):
    await Media2.collection.drop()
    await Media3.collection.drop()
    await delete_all_files_sql()
    await message.answer('Piracy Is Crime')
    await message.message.edit('Successfully Deleted All The Indexed Files.')

@Client.on_message(filters.command("cmds"))
async def cmds_x(_, message):
    btn = [[
        InlineKeyboardButton('Close', callback_data="close_data")
    ]]
    reply_markup = InlineKeyboardMarkup(btn)
    await message.reply_text(script.CMDS_TXT,
    reply_markup=reply_markup,
    parse_mode=enums.ParseMode.HTML,
    link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    
@Client.on_message(filters.command('autofilter') & filters.user(ADMINS))
async def fil_mod(client, message):
    mode_on = ["yes", "on", "true"]
    mode_of = ["no", "off", "false"]
    try: 
       args = message.text.split(None, 1)[1].lower()
    except: 
       return await message.reply("incomplete command 😅")
    m = await message.reply("loading...😊")
    settings = temp.AUTO_FILTER
    if args in mode_on:
        temp.AUTO_FILTER = True
        await db.update_autofilter(True)
        await m.edit("Aᴜᴛᴏғɪʟᴛᴇʀ ᴍᴏᴅᴇ ᴛᴜʀɴᴇᴅ ᴏɴ ⚡️")
    elif args in mode_of:
        temp.AUTO_FILTER = False
        await db.update_autofilter(False)
        await m.edit("Aᴜᴛᴏғɪʟᴛᴇʀ ᴍᴏᴅᴇ ᴛᴜʀɴᴇᴅ ᴏғғ 🤫")
    else:
        await m.edit("Try - `/autofilter on` or `/autofilter off`")


