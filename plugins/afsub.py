import subprocess
import json

from pyrogram import Client, filters, enums
import sys, os
from info import ADMINS
from pyrogram.errors import ChatAdminRequired, FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ChatJoinRequest, Message
from pyrogram.types import ChatJoinRequest
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong, PeerIdInvalid
from database.users_chats_db import db
from utils import temp

@Client.on_chat_join_request()
async def join_reqs(bot, join_req: ChatJoinRequest):
    user_id = join_req.from_user.id
    try:
        if join_req.chat.id == temp.REQ_CHANNEL1:
            user = await db.get_req_one(user_id)
            if not user:
                await db.add_req_one(user_id)
            await check_and_switch_channel(bot, 1)
        elif join_req.chat.id == temp.REQ_CHANNEL2:
            user = await db.get_req_two(user_id)
            if not user:
                await db.add_req_two(user_id)
            await check_and_switch_channel(bot, 2)
        elif join_req.chat.id == temp.REQ_CHANNEL3:
            user = await db.get_req_three(user_id)
            if not user:
                await db.add_req_three(user_id)
            await check_and_switch_channel(bot, 3)
    except Exception as e:
        print(f"Error adding join request: {e}")

async def check_and_switch_channel(bot, channel_num):
    try:
        if channel_num == 1:
            count = await db.get_all_one_count()
            threshold = getattr(temp, 'COUNT_THRESHOLD1', None)
            secondary_channel = getattr(temp, 'REQ_CHANNEL1_2', None)

            if threshold and count > threshold and secondary_channel:
                temp.REQ_CHANNEL1 = secondary_channel
                temp.REQ_CHANNEL1_2 = None
                await db.delete_all_one()
                bot.req_link1 = getattr(bot, 'req_link1_2', None)
                bot.req_link1_2 = None
                await db.update_loadout('channel1', secondary_channel, bot.me.id)
                print(f"Switched channel 1 to secondary channel due to threshold ({count} > {threshold})")
                return
            if threshold and count > threshold:
                await db.delete_all_one()
                temp.REQ_CHANNEL1 = None
                bot.req_link1 = None
                await db.update_loadout('channel1', None, bot.me.id)            
                
        elif channel_num == 2:
            count = await db.get_all_two_count()
            threshold = getattr(temp, 'COUNT_THRESHOLD2', None)
            secondary_channel = getattr(temp, 'REQ_CHANNEL2_2', None)
            
            if threshold and count > threshold and secondary_channel:
                temp.REQ_CHANNEL2 = secondary_channel
                bot.req_link2 = getattr(bot, 'req_link2_2', None)
                temp.REQ_CHANNEL2_2 = None
                bot.req_link2_2 = None
                await db.delete_all_two()
                await db.update_loadout('channel2', secondary_channel, bot.me.id)
                print(f"Switched channel 2 to secondary channel due to threshold ({count} > {threshold})")
                return
            if threshold and count > threshold:
                temp.REQ_CHANNEL2 = None
                bot.req_link2 = None
                await db.delete_all_two()
                await db.update_loadout('channel2', None, bot.me.id)
                
        elif channel_num == 3:
            count = await db.get_all_three_count()
            threshold = getattr(temp, 'COUNT_THRESHOLD3', None)
            secondary_channel = getattr(temp, 'REQ_CHANNEL3_2', None)
            
            if threshold and count > threshold and secondary_channel:
                temp.REQ_CHANNEL3 = secondary_channel
                bot.req_link3 = getattr(bot, 'req_link3_2', None)
                temp.REQ_CHANNEL3_2 = None
                bot.req_link3_2 = None
                await db.delete_all_three()
                await db.update_loadout('channel3', secondary_channel, bot.me.id)
                print(f"Switched channel 3 to secondary channel due to threshold ({count} > {threshold})")
                return
            if threshold and count > threshold:
                temp.REQ_CHANNEL3 = None
                bot.req_link3 = None
                await db.delete_all_three()
                await db.update_loadout('channel3', None, bot.me.id)
                
    except Exception as e:
        print(f"Error in check_and_switch_channel: {e}")

@Client.on_message(filters.command("2sub1") & filters.user(ADMINS))
async def set_secondary_chat1(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the Secondary Force Subscribe Channel ID for Channel 1.\n\n"
            "**Usage:** `/setchat1_2 -100123456789`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    
    raw_id = m.text.split(" ", 1)[1]
    await m.reply(f"Setting Channel ID: `{raw_id}`", parse_mode=enums.ParseMode.MARKDOWN)

    try:
        chat = await bot.get_chat(int(raw_id))
    except Exception as e:
        return await m.reply(f"❌ Error getting chat: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    link = "N/A"
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=chat.id, creates_join_request=True)
        link = link_obj.invite_link
    except Exception as e:
        return await m.reply(f"❌ Error creating invite link: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    try:
        my_id = (await bot.get_me()).id
        await db.update_loadout('channel1_2', chat.id, my_id)
        temp.REQ_CHANNEL1_2 = chat.id
        bot.req_link1_2 = link
    except Exception as e:
        return await m.reply(f"❌ Error updating DB or temp: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    return await m.reply(
        f"✅ **Secondary Force Subscribe Channel 1 Set!**\n\n"
        f"🆔 `{chat.id}`\n"
        f"📛 `{chat.title}`\n"
        f"🔗 [Invite Link]({link})",
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.MARKDOWN
    )

@Client.on_message(filters.command("2sub2") & filters.user(ADMINS))
async def set_secondary_chat2(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the Secondary Force Subscribe Channel ID for Channel 2.\n\n"
            "**Usage:** `/setchat2_2 -100123456789`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    
    raw_id = m.text.split(" ", 1)[1]
    await m.reply(f"Setting Channel ID: `{raw_id}`", parse_mode=enums.ParseMode.MARKDOWN)

    try:
        chat = await bot.get_chat(int(raw_id))
    except Exception as e:
        return await m.reply(f"❌ Error getting chat: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    link = "N/A"
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=chat.id, creates_join_request=True)
        link = link_obj.invite_link
    except Exception as e:
        return await m.reply(f"❌ Error creating invite link: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    try:
        my_id = (await bot.get_me()).id
        await db.update_loadout('channel2_2', chat.id, my_id)
        temp.REQ_CHANNEL2_2 = chat.id
        bot.req_link2_2 = link
    except Exception as e:
        return await m.reply(f"❌ Error updating DB or temp: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    return await m.reply(
        f"✅ **Secondary Force Subscribe Channel 2 Set!**\n\n"
        f"🆔 `{chat.id}`\n"
        f"📛 `{chat.title}`\n"
        f"🔗 [Invite Link]({link})",
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.MARKDOWN
    )
    
@Client.on_message(filters.command("2sub3") & filters.user(ADMINS))
async def set_secondary_chat3(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the Secondary Force Subscribe Channel ID for Channel 3.\n\n"
            "**Usage:** `/setchat3_2 -100123456789`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    
    raw_id = m.text.split(" ", 1)[1]
    await m.reply(f"Setting Channel ID: `{raw_id}`", parse_mode=enums.ParseMode.MARKDOWN)

    try:
        chat = await bot.get_chat(int(raw_id))
    except Exception as e:
        return await m.reply(f"❌ Error getting chat: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    link = "N/A"
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=chat.id, creates_join_request=True)
        link = link_obj.invite_link
    except Exception as e:
        return await m.reply(f"❌ Error creating invite link: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    try:
        my_id = (await bot.get_me()).id
        await db.update_loadout('channel3_2', chat.id, my_id)
        temp.REQ_CHANNEL3_2 = chat.id
        bot.req_link3_2 = link
    except Exception as e:
        return await m.reply(f"❌ Error updating DB or temp: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)

    return await m.reply(
        f"✅ **Secondary Force Subscribe Channel 3 Set!**\n\n"
        f"🆔 `{chat.id}`\n"
        f"📛 `{chat.title}`\n"
        f"🔗 [Invite Link]({link})",
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.MARKDOWN
    )


@Client.on_message(filters.command("setcount1") & filters.user(ADMINS))
async def set_count_threshold1(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the join request count threshold for Channel 1.\n\n"
            "**Usage:** `/setcount1 100`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    
    try:
        count = int(m.text.split(" ", 1)[1])
        if count <= 0:
            return await m.reply("❌ **Count must be a positive number!**", parse_mode=enums.ParseMode.MARKDOWN)

        await db.update_cout('channel1', count)
        temp.COUNT_THRESHOLD1 = count
        
        text = (
            f"✅ **Count Threshold for Channel 1 Successfully Set!**\n\n"
            f"**📊 Threshold:** `{count}` join requests\n"
            f"**📝 Note:** When this threshold is exceeded, the system will switch to the secondary channel (if set)."
        )
        return await m.reply(text=text, parse_mode=enums.ParseMode.MARKDOWN)
        
    except ValueError:
        return await m.reply("❌ **Invalid number! Please provide a valid integer.**", parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command("setcount2") & filters.user(ADMINS))
async def set_count_threshold2(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the join request count threshold for Channel 2.\n\n"
            "**Usage:** `/setcount2 100`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    
    try:
        count = int(m.text.split(" ", 1)[1])
        if count <= 0:
            return await m.reply("❌ **Count must be a positive number!**", parse_mode=enums.ParseMode.MARKDOWN)

        await db.update_cout('channel2', count)
        temp.COUNT_THRESHOLD2 = count
        
        text = (
            f"✅ **Count Threshold for Channel 2 Successfully Set!**\n\n"
            f"**📊 Threshold:** `{count}` join requests\n"
            f"**📝 Note:** When this threshold is exceeded, the system will switch to the secondary channel (if set)."
        )
        return await m.reply(text=text, parse_mode=enums.ParseMode.MARKDOWN)
        
    except ValueError:
        return await m.reply("❌ **Invalid number! Please provide a valid integer.**", parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command("setcount3") & filters.user(ADMINS))
async def set_count_threshold3(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the join request count threshold for Channel 3.\n\n"
            "**Usage:** `/setcount3 100`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    
    try:
        count = int(m.text.split(" ", 1)[1])
        if count <= 0:
            return await m.reply("❌ **Count must be a positive number!**", parse_mode=enums.ParseMode.MARKDOWN)

        await db.update_cout('channel3', count)
        temp.COUNT_THRESHOLD3 = count
        
        text = (
            f"✅ **Count Threshold for Channel 3 Successfully Set!**\n\n"
            f"**📊 Threshold:** `{count}` join requests\n"
            f"**📝 Note:** When this threshold is exceeded, the system will switch to the secondary channel (if set)."
        )
        return await m.reply(text=text, parse_mode=enums.ParseMode.MARKDOWN)
        
    except ValueError:
        return await m.reply("❌ **Invalid number! Please provide a valid integer.**", parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command("sub1") & filters.user(ADMINS))
async def add_fsub_chatt1(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the Force Subscribe Channel ID.\n\n"
            "**Usage:** `/set_sub1 -100123456789`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    raw_id = m.text.split(" ", 1)[1]
    
    if temp.REQ_CHANNEL1:
        await db.update_loadout('channel1', None, bot.me.id)
        await db.delete_all_one()
        temp.REQ_CHANNEL1 = None
        bot.req_link1 = None

    try:
        chat = await bot.get_chat(int(raw_id))
    except ChatAdminRequired:
        return await m.reply(
            "❌ **Access Denied!**\n\n"
            "I don't have full admin rights in this channel. "
            "Please ensure I have **all administrative permissions** (including invite link creation) "
            "before setting it as a Force Subscribe channel.",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except PeerIdInvalid:
        return await m.reply(
            "❌ **Invalid Channel ID!**\n\n"
            "The bot is not a member of this channel. "
            "Please add the bot to the channel and grant **full admin permissions**.",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except Exception as e:
        return await m.reply(f'❌ **Error:** `{e}`', parse_mode=enums.ParseMode.MARKDOWN)
    
    link = "N/A (Error generating link)"
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=int(chat.id), creates_join_request=True)
        link = link_obj.invite_link
    except Exception as e:
        print(f"Error creating invite link for {chat.id}: {e}")

    await db.update_loadout('channel1', chat.id, bot.me.id)
    await db.delete_all_one()
    temp.REQ_CHANNEL1 = chat.id
    bot.req_link1 = link

    text = (
        f"✅ **Force Subscribe Channel 1 Successfully Set!**\n\n"
        f"**🆔 Chat ID:** `{chat.id}`\n"
        f"**📝 Chat Name:** `{chat.title}`\n"
        f"**🔗 Invite Link:** [Click Here]({link})"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command("sub2") & filters.user(ADMINS))
async def add_fsub_chatt2(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the Force Subscribe Channel ID.\n\n"
            "**Usage:** `/set_sub2 -100123456789`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    raw_id = m.text.split(" ", 1)[1]

    if temp.REQ_CHANNEL2:
        await db.update_loadout('channel2', None, bot.me.id)
        await db.delete_all_two()
        temp.REQ_CHANNEL2 = None
        bot.req_link2 = None

    try:
        chat = await bot.get_chat(int(raw_id))
    except ChatAdminRequired:
        return await m.reply(
            "❌ **Access Denied!**\n\n"
            "I don't have full admin rights in this channel. "
            "Please ensure I have **all administrative permissions** (including invite link creation) "
            "before setting it as a Force Subscribe channel.",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except PeerIdInvalid:
        return await m.reply(
            "❌ **Invalid Channel ID!**\n\n"
            "The bot is not a member of this channel. "
            "Please add the bot to the channel and grant **full admin permissions**.",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except Exception as e:
        return await m.reply(f'❌ **Error:** `{e}`', parse_mode=enums.ParseMode.MARKDOWN)
    
    link = "N/A (Error generating link)"
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=int(chat.id), creates_join_request=True)
        link = link_obj.invite_link
    except Exception as e:
        print(f"Error creating invite link for {chat.id}: {e}")

    await db.update_loadout('channel2', chat.id, bot.me.id)
    await db.delete_all_two()
    temp.REQ_CHANNEL2 = chat.id
    bot.req_link2 = link

    text = (
        f"✅ **Force Subscribe Channel 2 Successfully Set!**\n\n"
        f"**🆔 Chat ID:** `{chat.id}`\n"
        f"**📝 Chat Name:** `{chat.title}`\n"
        f"**🔗 Invite Link:** [Click Here]({link})"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command("sub3") & filters.user(ADMINS))
async def add_fsub_chatt3(bot, m):
    if len(m.command) == 1:
        return await m.reply(
            "Please provide the Force Subscribe Channel ID.\n\n"
            "**Usage:** `/set_sub3 -100123456789`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    raw_id = m.text.split(" ", 1)[1]

    if temp.REQ_CHANNEL3:
        await db.update_loadout('channel3', None, bot.me.id)
        await db.delete_all_three()
        temp.REQ_CHANNEL3 = None
        bot.req_link3 = None

    try:
        chat = await bot.get_chat(int(raw_id))
    except ChatAdminRequired:
        return await m.reply(
            "❌ **Access Denied!**\n\n"
            "I don't have full admin rights in this channel. "
            "Please ensure I have **all administrative permissions** (including invite link creation) "
            "before setting it as a Force Subscribe channel.",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except PeerIdInvalid:
        return await m.reply(
            "❌ **Invalid Channel ID!**\n\n"
            "The bot is not a member of this channel. "
            "Please add the bot to the channel and grant **full admin permissions**.",
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except Exception as e:
        return await m.reply(f'❌ **Error:** `{e}`', parse_mode=enums.ParseMode.MARKDOWN)

    link = "N/A (Error generating link)"
    try:
        link_obj = await bot.create_chat_invite_link(chat_id=int(chat.id), creates_join_request=True)
        link = link_obj.invite_link
    except Exception as e:
        print(f"Error creating invite link for {chat.id}: {e}")

    await db.update_loadout('channel3', chat.id, bot.me.id)
    await db.delete_all_three()
    temp.REQ_CHANNEL3 = chat.id
    bot.req_link3 = link

    text = (
        f"✅ **Force Subscribe Channel 3 Successfully Set!**\n\n"
        f"**🆔 Chat ID:** `{chat.id}`\n"
        f"**📝 Chat Name:** `{chat.title}`\n"
        f"**🔗 Invite Link:** [Click Here]({link})"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command("view_sub") & filters.user(ADMINS))
async def get_fsub_chats(bot, m):
    try:
        all_channels_text = "📊 **Force Subscribe Channels Status** 📊\n\n"

        if temp.REQ_CHANNEL1:
            try:
                chat1 = await bot.get_chat(int(temp.REQ_CHANNEL1))
                title1 = chat1.title
            except Exception:
                title1 = "_Could not retrieve chat info_"
            link1 = getattr(bot, 'req_link1', "N/A (No invite link available)")
            count1 = await db.get_all_one_count()
            threshold1 = getattr(temp, 'COUNT_THRESHOLD1', 'Not Set')
            secondary1 = getattr(temp, 'REQ_CHANNEL1_2', None)

            all_channels_text += (
                f"**─── Channel 1 ───**\n"
                f"  **🆔 Chat ID:** `{temp.REQ_CHANNEL1}`\n"
                f"  **📝 Chat Name:** `{title1}`\n"
                f"  **🔗 Invite Link:** [Click Here]({link1})\n"
                f"  **👥 Total Requests:** `{count1}`\n"
                f"  **📊 Count Threshold:** `{threshold1}`\n"
                f"  **🔄 Secondary Channel:** `{secondary1 if secondary1 else 'Not Set'}`\n\n"
            )
        else:
            all_channels_text += "**─── Channel 1 ───**\n  __No Force Subscribe channel set for slot 1.__\n\n"

        if temp.REQ_CHANNEL2:
            try:
                chat2 = await bot.get_chat(int(temp.REQ_CHANNEL2))
                title2 = chat2.title
            except Exception:
                title2 = "_Could not retrieve chat info_"
            link2 = getattr(bot, 'req_link2', "N/A (No invite link available)")
            count2 = await db.get_all_two_count()
            threshold2 = getattr(temp, 'COUNT_THRESHOLD2', 'Not Set')
            secondary2 = getattr(temp, 'REQ_CHANNEL2_2', None)

            all_channels_text += (
                f"**─── Channel 2 ───**\n"
                f"  **🆔 Chat ID:** `{temp.REQ_CHANNEL2}`\n"
                f"  **📝 Chat Name:** `{title2}`\n"
                f"  **🔗 Invite Link:** [Click Here]({link2})\n"
                f"  **👥 Total Requests:** `{count2}`\n"
                f"  **📊 Count Threshold:** `{threshold2}`\n"
                f"  **🔄 Secondary Channel:** `{secondary2 if secondary2 else 'Not Set'}`\n\n"
            )
        else:
            all_channels_text += "**─── Channel 2 ───**\n  __No Force Subscribe channel set for slot 2.__\n\n"

        if temp.REQ_CHANNEL3:
            try:
                chat3 = await bot.get_chat(int(temp.REQ_CHANNEL3))
                title3 = chat3.title
            except Exception:
                title3 = "_Could not retrieve chat info_"
            link3 = getattr(bot, 'req_link3', "N/A (No invite link available)")
            count3 = await db.get_all_three_count()
            threshold3 = getattr(temp, 'COUNT_THRESHOLD3', 'Not Set')
            secondary3 = getattr(temp, 'REQ_CHANNEL3_2', None)

            all_channels_text += (
                f"**─── Channel 3 ───**\n"
                f"  **🆔 Chat ID:** `{temp.REQ_CHANNEL3}`\n"
                f"  **📝 Chat Name:** `{title3}`\n"
                f"  **🔗 Invite Link:** [Click Here]({link3})\n"
                f"  **👥 Total Requests:** `{count3}`\n"
                f"  **📊 Count Threshold:** `{threshold3}`\n"
                f"  **🔄 Secondary Channel:** `{secondary3 if secondary3 else 'Not Set'}`"
            )
        else:
            all_channels_text += "**─── Channel 3 ───**\n  __No Force Subscribe channel set for slot 3.__"

        await m.reply_text(all_channels_text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)

    except Exception as e:
        await m.reply_text(f"An error occurred while fetching channels: `{str(e)}`", parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command("delsub1") & filters.user(ADMINS))
async def del_fsub_chats1(bot, m):
    if not temp.REQ_CHANNEL1:
        return await m.reply("⚠️ **No Force Subscribe Channel set for slot 1 to delete.**", parse_mode=enums.ParseMode.MARKDOWN)
    
    old_channel_id = temp.REQ_CHANNEL1
    temp.REQ_CHANNEL1 = None
    bot.req_link1 = None
    await db.update_loadout('channel1', None, bot.me.id)
    await db.delete_all_one()
    
    text = (
        f"🗑️ **Force Subscribe Channel 1 Successfully Removed!**\n\n"
        f"**🆔 Chat ID:** `{old_channel_id}`"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command("delsub2") & filters.user(ADMINS))
async def del_fsub_chats2(bot, m):
    if not temp.REQ_CHANNEL2:
        return await m.reply("⚠️ **No Force Subscribe Channel set for slot 2 to delete.**", parse_mode=enums.ParseMode.MARKDOWN)
    
    old_channel_id = temp.REQ_CHANNEL2
    temp.REQ_CHANNEL2 = None
    bot.req_link2 = None
    await db.update_loadout('channel2', None, bot.me.id)
    await db.delete_all_two()
    
    text = (
        f"🗑️ **Force Subscribe Channel 2 Successfully Removed!**\n\n"
        f"**🆔 Chat ID:** `{old_channel_id}`"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command("delsub3") & filters.user(ADMINS))
async def del_fsub_chats3(bot, m):
    if not temp.REQ_CHANNEL3:
        return await m.reply("⚠️ **No Force Subscribe Channel set for slot 3 to delete.**", parse_mode=enums.ParseMode.MARKDOWN)
    
    old_channel_id = temp.REQ_CHANNEL3
    temp.REQ_CHANNEL3 = None
    bot.req_link3 = None
    await db.update_loadout('channel3', None, bot.me.id)
    await db.delete_all_three()
    
    text = (
        f"🗑️ **Force Subscribe Channel 3 Successfully Removed!**\n\n"
        f"**🆔 Chat ID:** `{old_channel_id}`"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command("2delsub1") & filters.user(ADMINS))
async def del_secondary_chat1(bot, m):
    if not temp.REQ_CHANNEL1_2:
        return await m.reply("⚠️ **No Secondary Force Subscribe Channel set for slot 1 to delete.**", parse_mode=enums.ParseMode.MARKDOWN)
    
    old_channel_id = temp.REQ_CHANNEL1_2
    temp.REQ_CHANNEL1_2 = None
    bot.req_link1_2 = None
    await db.update_loadout('channel1_2', None, bot.me.id)
    
    text = (
        f"🗑️ **Secondary Force Subscribe Channel 1 Successfully Removed!**\n\n"
        f"**🆔 Chat ID:** `{old_channel_id}`"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command("2delsub2") & filters.user(ADMINS))
async def del_secondary_chat2(bot, m):
    if not temp.REQ_CHANNEL2_2:
        return await m.reply("⚠️ **No Secondary Force Subscribe Channel set for slot 2 to delete.**", parse_mode=enums.ParseMode.MARKDOWN)
    
    old_channel_id = temp.REQ_CHANNEL2_2
    temp.REQ_CHANNEL2_2 = None
    bot.req_link2_2 = None
    await db.update_loadout('channel2_2', None, bot.me.id)
    
    text = (
        f"🗑️ **Secondary Force Subscribe Channel 2 Successfully Removed!**\n\n"
        f"**🆔 Chat ID:** `{old_channel_id}`"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command("2delsub3") & filters.user(ADMINS))
async def del_secondary_chat3(bot, m):
    if not temp.REQ_CHANNEL3_2:
        return await m.reply("⚠️ **No Secondary Force Subscribe Channel set for slot 3 to delete.**", parse_mode=enums.ParseMode.MARKDOWN)
    
    old_channel_id = temp.REQ_CHANNEL3_2
    temp.REQ_CHANNEL3_2 = None
    bot.req_link3_2 = None
    await db.update_loadout('channel3_2', None, bot.me.id)
    
    text = (
        f"🗑️ **Secondary Force Subscribe Channel 3 Successfully Removed!**\n\n"
        f"**🆔 Chat ID:** `{old_channel_id}`"
    )
    return await m.reply(text=text, disable_web_page_preview=True, parse_mode=enums.ParseMode.MARKDOWN)
