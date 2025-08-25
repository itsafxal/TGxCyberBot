import os
from pyrogram import Client, filters, enums
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant, MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from utils import extract_user, get_file_id, last_online
import time
from datetime import datetime
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

@Client.on_message(filters.command('id'))
async def showid(client, message):
    chat_type = message.chat.type
    if chat_type == enums.ChatType.PRIVATE:
        user_id = message.chat.id
        first = message.from_user.first_name
        last = message.from_user.last_name or ""
        username = message.from_user.username or "N/A"
        dc_id = message.from_user.dc_id or "Not Available" # More user-friendly
        
        await message.reply_text(
            f"👤 <b>Your Personal ID Card</b>\n\n"
            f"────────────────────\n"
            f"📝 <b>First Name:</b> {first}\n"
            f"📝 <b>Last Name:</b> {last}\n"
            f"✨ <b>Username:</b> @{username}\n"
            f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
            f"🌐 <b>Data Centre:</b> <code>{dc_id}</code>\n"
            f"────────────────────",
            quote=True,
            parse_mode=enums.ParseMode.HTML # Ensure HTML is explicitly set
        )

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        _id_text = "📊 <b>IDs Information</b>\n\n"
        _id_text += (
            "💬 <b>Chat ID:</b> "
            f"<code>{message.chat.id}</code>\n"
        )
        if message.reply_to_message:
            _id_text += (
                "👤 <b>Your User ID:</b> "
                f"<code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n"
                "↩️ <b>Replied User ID:</b> "
                f"<code>{message.reply_to_message.from_user.id if message.reply_to_message.from_user else 'Anonymous'}</code>\n"
            )
            file_info = get_file_id(message.reply_to_message)
        else:
            _id_text += (
                "👤 <b>Your User ID:</b> "
                f"<code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n"
            )
            file_info = get_file_id(message)
        
        if file_info:
            _id_text += (
                f"📎 <b>{file_info.message_type.replace('_', ' ').title()} ID:</b> " # Capitalize and clean type name
                f"<code>{file_info.file_id}</code>\n"
            )
        
        _id_text += "────────────────────"
        await message.reply_text(
            _id_text,
            quote=True,
            parse_mode=enums.ParseMode.HTML
        )

@Client.on_message(filters.command(["info"]))
async def who_is(client, message):
    status_message = await message.reply_text(
        "🔍 **Fetching user information...** ⏳",
        parse_mode=enums.ParseMode.MARKDOWN # Using markdown for status messages
    )
    
    from_user = None
    from_user_id, _ = extract_user(message)
    try:
        from_user = await client.get_users(from_user_id)
    except Exception as error:
        await status_message.edit(f"❌ **Error:** Could not retrieve user information. \n\n_Details: {error}_")
        return
    
    if from_user is None:
        return await status_message.edit("⚠️ **No valid user specified.** Please reply to a user's message or provide a valid user ID/username.")
    
    message_out_str = "✨ <b>User Profile Details</b> ✨\n\n"
    message_out_str += f"📝 <b>First Name:</b> {from_user.first_name}\n"
    
    last_name = from_user.last_name or "_Not Set_" # More user-friendly
    message_out_str += f"📝 <b>Last Name:</b> {last_name}\n"
    
    message_out_str += f"🆔 <b>Telegram ID:</b> <code>{from_user.id}</code>\n"
    
    username = from_user.username or "_Not Set_" # More user-friendly
    message_out_str += f"✨ <b>Username:</b> @{username}\n"
    
    dc_id = from_user.dc_id or "_Not Available_" # More user-friendly
    message_out_str += f"🌐 <b>Data Centre:</b> <code>{dc_id}</code>\n"
    
    message_out_str += f"🔗 <b>User Link:</b> <a href='tg://user?id={from_user.id}'>Click Here</a>\n" # No bold on 'Click Here'

    if from_user.status:
        # Using utils.last_online to format status
        online_status = last_online(from_user)
        message_out_str += f"🟢 <b>Status:</b> {online_status}\n"
    else:
        message_out_str += f"🟢 <b>Status:</b> `Offline`\n"


    if message.chat.type in (enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL):
        try:
            chat_member_p = await message.chat.get_member(from_user.id)
            # Formatting joined date for better readability
            joined_date = (
                chat_member_p.joined_date or datetime.now()
            ).strftime("%Y-%m-%d %H:%M:%S")
            message_out_str += (
                "🗓️ **Joined this Chat on:** <code>"
                f"{joined_date}"
                "</code>\n"
            )
        except UserNotParticipant:
            message_out_str += "🗓️ <b>Joined this Chat on:</b> _Not a member of this chat._\n"
        except Exception as e:
            logger.error(f"Error getting chat member info: {e}")
            message_out_str += "🗓️ <b>Joined this Chat on:</b> _Error retrieving info._\n"


    message_out_str += "────────────────────" # Separator

    chat_photo = from_user.photo
    if chat_photo:
        local_user_photo = await client.download_media(
            message=chat_photo.big_file_id
        )
        buttons = [[
            InlineKeyboardButton('🔐 Close', callback_data='close_data')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=local_user_photo,
            quote=True,
            reply_markup=reply_markup,
            caption=message_out_str,
            parse_mode=enums.ParseMode.HTML,
            disable_notification=True
        )
        os.remove(local_user_photo) # Clean up downloaded photo
    else:
        buttons = [[
            InlineKeyboardButton('🔐 Close', callback_data='close_data')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_text(
            text=message_out_str,
            reply_markup=reply_markup,
            quote=True,
            disable_notification=True,
            parse_mode=enums.ParseMode.HTML
        )
    await status_message.delete()
