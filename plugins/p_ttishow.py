from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong, PeerIdInvalid
from info import ADMINS, LOG_CHANNEL, SUPPORT_CHAT
from database.users_chats_db import db
from database.ia_filterdb import Media3, Media2, db as clientDB, db2 as clientDB2, db3 as clientDB3
from utils import get_size, temp
from Script import script
from pyrogram.errors import ChatAdminRequired

@Client.on_message(filters.new_chat_members & filters.group)
async def save_group(bot, message):
    r_j_check = [u.id for u in message.new_chat_members]

    if temp.ME in r_j_check:

        if not await db.get_chat(message.chat.id):

            total = await bot.get_chat_members_count(message.chat.id)

            group_username = message.chat.username or "Private Group"
            group_type = str(message.chat.type)

            if message.from_user:
                adder_name = message.from_user.first_name
                adder_id = message.from_user.id
                adder_username = message.from_user.username or "No Username"
            else:
                adder_name = "Anonymous"
                adder_id = "Unknown"
                adder_username = "No Username"

            bot_username = (await bot.get_me()).username

            await bot.send_message(
                LOG_CHANNEL,
                script.LOG_TEXT_G.format(
                    message.chat.title,
                    message.chat.id,
                    total,
                    group_username,
                    group_type,
                    adder_name,
                    adder_id,
                    adder_username,
                    bot_username
                )
            )

            await db.add_chat(message.chat.id, message.chat.title)

        if message.chat.id in temp.BANNED_CHATS:
            buttons = [[
                InlineKeyboardButton(
                    '🚨 Support',
                    url=f'https://t.me/{SUPPORT_CHAT}'
                )
            ]]

            reply_markup = InlineKeyboardMarkup(buttons)

            k = await message.reply(
                text='🚫 **CHAT RESTRICTED!** 🚫\n\n'
                     'My administrators have restricted my operations in this group. '
                     'If you believe this is an error or need more information, '
                     'please contact support.',
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.MARKDOWN
            )

            try:
                await k.pin()
            except Exception:
                pass

            await bot.leave_chat(message.chat.id)
            return

        buttons = [[
            InlineKeyboardButton(
                '💡 Help',
                url=f"https://t.me/{temp.U_NAME}?start=help"
            ),
            InlineKeyboardButton(
                '📣 Updates',
                url='https://t.me/AT3xMain'
            )
        ]]

        reply_markup = InlineKeyboardMarkup(buttons)

        await message.reply_text(
            text=f"👋 **Hello! Thank you for adding me to {message.chat.title}!**\n\n"
                 f"I'm here to assist you. If you have any questions or need guidance on "
                 f"how to use my features, feel free to tap the 'Help' button or join our updates channel.",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )

@Client.on_message(filters.command('leave') & filters.user(ADMINS))
async def leave_a_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply('Please specify a chat ID to leave. \n\nUsage: `/leave <chat_id>`', parse_mode=enums.ParseMode.MARKDOWN)
    chat = message.command[1]
    try:
        chat = int(chat)
    except ValueError:
        return await message.reply('Please provide a **valid integer chat ID** to leave.', parse_mode=enums.ParseMode.MARKDOWN)
    try:
        buttons = [[
            InlineKeyboardButton('🚨 Support', url=f'https://t.me/{SUPPORT_CHAT}')
        ]]
        reply_markup=InlineKeyboardMarkup(buttons)
        await bot.send_message(
            chat_id=chat,
            text='👋 **Goodbye!**\n\n'
                 'My administrator has requested me to leave this group. '
                 'Should you wish to add me back in the future, '
                 'please contact our support group.',
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )

        await bot.leave_chat(chat)
        await message.reply(f"✅ Successfully left the chat: `{chat}`", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        await message.reply(f'❌ **Error leaving chat:** `{e}`', parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command('disable') & filters.user(ADMINS))
async def disable_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply('Please provide a chat ID to disable.\n\nUsage: `/disable <chat_id> [reason]`', parse_mode=enums.ParseMode.MARKDOWN)
    r = message.text.split(None)
    if len(r) > 2:
        reason = message.text.split(None, 2)[2]
        chat = message.text.split(None, 2)[1]
    else:
        chat = message.command[1]
        reason = "No reason provided by administrator."
    try:
        chat_ = int(chat)
    except ValueError:
        return await message.reply('Please provide a **valid integer chat ID** to disable.', parse_mode=enums.ParseMode.MARKDOWN)
    cha_t = await db.get_chat(int(chat_))
    if not cha_t:
        return await message.reply("🔍 Chat not found in the database.", parse_mode=enums.ParseMode.MARKDOWN)
    if cha_t.get('is_disabled'):
        return await message.reply(f"⚠️ This chat is already disabled.\n**Reason:** `{cha_t['reason']}`", parse_mode=enums.ParseMode.MARKDOWN)
    await db.disable_chat(int(chat_), reason)
    temp.BANNED_CHATS.append(int(chat_))
    await message.reply('✅ Chat successfully disabled!', parse_mode=enums.ParseMode.MARKDOWN)
    try:
        buttons = [[
            InlineKeyboardButton('🚨 Support', url=f'https://t.me/{SUPPORT_CHAT}')
        ]]
        reply_markup=InlineKeyboardMarkup(buttons)
        await bot.send_message(
            chat_id=chat_,
            text=f'🚫 **Chat Disabled!**\n\n'
                 f'My operations have been disabled in this group by an administrator.\n'
                 f'**Reason:** `{reason}`\n\n'
                 f'If you believe this is an error, please contact support.',
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        await bot.leave_chat(chat_)
    except Exception as e:
        await message.reply(f"❌ **Error notifying chat or leaving:** `{e}`", parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command('enable') & filters.user(ADMINS))
async def re_enable_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply('Please provide a chat ID to enable.\n\nUsage: `/enable <chat_id>`', parse_mode=enums.ParseMode.MARKDOWN)
    chat = message.command[1]
    try:
        chat_ = int(chat)
    except ValueError:
        return await message.reply('Please provide a **valid integer chat ID** to enable.', parse_mode=enums.ParseMode.MARKDOWN)
    sts = await db.get_chat(int(chat))
    if not sts:
        return await message.reply("🔍 Chat not found in the database!", parse_mode=enums.ParseMode.MARKDOWN)
    if not sts.get('is_disabled'):
        return await message.reply('⚠️ This chat is not currently disabled.', parse_mode=enums.ParseMode.MARKDOWN)
    await db.re_enable_chat(int(chat_))
    temp.BANNED_CHATS.remove(int(chat_))
    await message.reply("✅ Chat successfully re-enabled!", parse_mode=enums.ParseMode.MARKDOWN)
    # Optional: Send a message to the re-enabled chat
    try:
        await bot.send_message(
            chat_id=chat_,
            text=f"🎉 **Bot Re-enabled!**\n\n"
                 f"My operations have been re-enabled in this group. "
                 f"I'm back and ready to assist you!",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except Exception as e:
        await message.reply(f"⚠️ Could not send re-enable notification to chat `{chat_}`: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command('stats') & filters.user(ADMINS))
async def stats_command(bot, message):
    mlz = await message.reply("📊 Fetching statistics... Please wait. ⏳", parse_mode=enums.ParseMode.MARKDOWN)
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

    status_text = script.STATUS_TXT
    await mlz.edit_text(
        text=status_text.format(total, users, chats, used_dbSize1, used_dbSize2, used_dbSize3),
        parse_mode=enums.ParseMode.MARKDOWN
    )

@Client.on_message(filters.command('invite') & filters.user(ADMINS))
async def gen_invite(bot, message):
    if len(message.command) == 1:
        return await message.reply('Please provide a chat ID to generate an invite link. \n\nUsage: `/invite <chat_id>`', parse_mode=enums.ParseMode.MARKDOWN)
    chat = message.command[1]
    try:
        chat = int(chat)
    except ValueError:
        return await message.reply('Please provide a **valid integer chat ID**.', parse_mode=enums.ParseMode.MARKDOWN)
    try:
        link = await bot.create_chat_invite_link(chat)
        await message.reply(f'🔗 Here is your invite link: `{link.invite_link}`', parse_mode=enums.ParseMode.MARKDOWN)
    except ChatAdminRequired:
        return await message.reply("🚫 **Invite Link Generation Failed:** I do not have sufficient administrator rights to create invite links in that chat.", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        return await message.reply(f'❌ **Error generating invite link:** `{e}`', parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command('ban') & filters.user(ADMINS))
async def ban_a_user(bot, message):
    if len(message.command) == 1:
        return await message.reply('Please provide a user ID or username to ban.\n\nUsage: `/ban <user_id/username> [reason]`', parse_mode=enums.ParseMode.MARKDOWN)
    r = message.text.split(None)
    if len(r) > 2:
        reason = message.text.split(None, 2)[2]
        user_input = message.text.split(None, 2)[1]
    else:
        user_input = message.command[1]
        reason = "No reason provided by administrator."
    
    try:
        user_id = int(user_input)
    except ValueError:
        user_id = user_input # Assume it's a username

    try:
        k = await bot.get_users(user_id)
    except PeerIdInvalid:
        return await message.reply("❌ **Invalid User ID/Username:** The provided user ID or username is invalid or I have not met this user before.", parse_mode=enums.ParseMode.MARKDOWN)
    except IndexError: # This might occur if user_input is empty after split
        return await message.reply("❌ Please provide a valid user ID or username.", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        return await message.reply(f'❌ **Error getting user info:** `{e}`', parse_mode=enums.ParseMode.MARKDOWN)
    else:
        jar = await db.get_ban_status(k.id)
        if jar['is_banned']:
            return await message.reply(f"⚠️ **{k.mention}** is already banned.\n**Reason:** `{jar['ban_reason']}`", parse_mode=enums.ParseMode.MARKDOWN)
        await db.ban_user(k.id, reason)
        temp.BANNED_USERS.append(k.id)
        await message.reply(f"✅ Successfully banned **{k.mention}**.\n**Reason:** `{reason}`", parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command('unban') & filters.user(ADMINS))
async def unban_a_user(bot, message):
    if len(message.command) == 1:
        return await message.reply('Please provide a user ID or username to unban.\n\nUsage: `/unban <user_id/username>`', parse_mode=enums.ParseMode.MARKDOWN)
    r = message.text.split(None)
    if len(r) > 2:
        user_input = message.text.split(None, 2)[1]
    else:
        user_input = message.command[1]

    try:
        user_id = int(user_input)
    except ValueError:
        user_id = user_input # Assume it's a username

    try:
        k = await bot.get_users(user_id)
    except PeerIdInvalid:
        return await message.reply("❌ **Invalid User ID/Username:** The provided user ID or username is invalid or I have not met this user before.", parse_mode=enums.ParseMode.MARKDOWN)
    except IndexError:
        return await message.reply("❌ Please provide a valid user ID or username.", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        return await message.reply(f'❌ **Error getting user info:** `{e}`', parse_mode=enums.ParseMode.MARKDOWN)
    else:
        jar = await db.get_ban_status(k.id)
        if not jar['is_banned']:
            return await message.reply(f"⚠️ **{k.mention}** is not currently banned.", parse_mode=enums.ParseMode.MARKDOWN)
        await db.remove_ban(k.id)
        temp.BANNED_USERS.remove(k.id)
        await message.reply(f"✅ Successfully unbanned **{k.mention}**.", parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command('users') & filters.user(ADMINS))
async def list_users(bot, message):
    raju = await message.reply('👥 Getting list of all users... ⏳', parse_mode=enums.ParseMode.MARKDOWN)
    users = await db.get_all_users()
    out = "📊 **Registered Users:**\n\n"
    async for user in users:
        user_mention = f"<a href=tg://user?id={user['id']}>{user['name']}</a>"
        status = " (🚫 Banned)" if user['ban_status']['is_banned'] else ""
        out += f"• {user_mention}{status}\n"
    
    try:
        await raju.edit_text(out, parse_mode=enums.ParseMode.HTML)
    except MessageTooLong:
        with open('users.txt', 'w+', encoding='utf-8') as outfile:
            outfile.write(out)
        await message.reply_document('users.txt', caption="📑 **List of Users**", parse_mode=enums.ParseMode.MARKDOWN)
        try:
            os.remove('users.txt')
        except OSError as e:
            print(f"Error removing file: {e}") # Log this, don't return to user

@Client.on_message(filters.command('chats') & filters.user(ADMINS))
async def list_chats(bot, message):
    raju = await message.reply('💬 Getting list of all chats... ⏳', parse_mode=enums.ParseMode.MARKDOWN)
    chats = await db.get_all_chats()
    out = "📊 **Registered Chats:**\n\n"
    async for chat in chats:
        status = " (🚫 Disabled)" if chat['chat_status']['is_disabled'] else ""
        out += f"• **Title:** `{chat['title']}`\n"
        out += f"  **ID:** `{chat['id']}`{status}\n\n" # Added extra newline for better readability between chats
    
    try:
        await raju.edit_text(out, parse_mode=enums.ParseMode.MARKDOWN)
    except MessageTooLong:
        with open('chats.txt', 'w+', encoding='utf-8') as outfile:
            outfile.write(out)
        await message.reply_document('chats.txt', caption="📑 **List of Chats**", parse_mode=enums.ParseMode.MARKDOWN)
        try:
            os.remove('chats.txt')
        except OSError as e:
            print(f"Error removing file: {e}") # Log this, don't return to user
