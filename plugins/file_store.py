# file_store.py
import re
import os
import json
import base64
import logging
from pyrogram import filters, Client, enums
from pyrogram.errors import ChannelInvalid, UsernameInvalid, UsernameNotModified
from info import ADMINS, LOG_CHANNEL, FILE_STORE_CHANNEL, PUBLIC_FILE_STORE
from database.ia_filterdb import unpack_new_file_id
from utils import temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

if isinstance(FILE_STORE_CHANNEL, int):
    FILE_STORE_CHANNEL = [FILE_STORE_CHANNEL]

async def allowed(_, __, message):
    if PUBLIC_FILE_STORE or (message.from_user and message.from_user.id in ADMINS):
        return True
    return False

@Client.on_message(filters.command(['link', 'plink']) & filters.create(allowed))
async def gen_link_s(bot, message):
    replied = message.reply_to_message
    if not replied:
        return await message.reply('Reply to a media message.')

    media = replied.media
    if media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT]:
        return await message.reply("Unsupported media type.")

    if replied.has_protected_content and message.from_user.id not in ADMINS:
        return await message.reply("Media is protected.")

    file_id_raw = getattr(replied, media.value).file_id
    file_id, ref = unpack_new_file_id(file_id_raw)
    prefix = 'filep_' if message.command[0] == 'plink' else 'file_'
    encoded = base64.urlsafe_b64encode((prefix + file_id).encode()).decode().rstrip("=")

    await message.reply(f"Here is your Link:\nhttps://t.me/{temp.U_NAME}?start={encoded}")

@Client.on_message(filters.command(['batch', 'pbatch']) & filters.create(allowed))
async def gen_link_batch(bot, message):
    try:
        _, first_link, last_link = message.text.split()
    except ValueError:
        return await message.reply("Usage:\n/batch <link1> <link2>")

    regex = re.compile(r"(?:t\.me|telegram\.me)/(?:c/)?([\w\d_-]+)/(\d+)")
    def extract(link):
        match = regex.search(link)
        if not match:
            return None, None
        chat, msg_id = match.groups()
        return int("-100" + chat) if chat.isdigit() else chat, int(msg_id)

    f_chat_id, f_msg_id = extract(first_link)
    l_chat_id, l_msg_id = extract(last_link)

    if not f_chat_id or not l_chat_id:
        return await message.reply("Invalid link(s).")

    if f_chat_id != l_chat_id:
        return await message.reply("Both messages must be from the same chat.")

    f_msg_id, l_msg_id = sorted([f_msg_id, l_msg_id])

    try:
        chat = await bot.get_chat(f_chat_id)
    except (ChannelInvalid, UsernameInvalid, UsernameNotModified) as e:
        return await message.reply("Invalid chat or bot lacks access.")
    except Exception as e:
        logger.exception("Chat fetch error")
        return await message.reply(f"Error: {e}")

    status = await message.reply("Fetching messages...")

    if chat.id in FILE_STORE_CHANNEL:
        raw = f"{f_msg_id}_{l_msg_id}_{chat.id}_{message.command[0]}"
        b64 = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        return await status.edit(f"https://t.me/{temp.U_NAME}?start=DSTORE-{b64}")

    outlist, valid, total = [], 0, l_msg_id - f_msg_id + 1

    for i in range(f_msg_id, l_msg_id + 1, 100):
        batch = list(range(i, min(l_msg_id + 1, i + 100)))
        try:
            msgs = await bot.get_messages(f_chat_id, batch)
        except Exception as e:
            logger.warning(f"Batch error: {e}")
            continue

        for msg in msgs:
            if not msg or msg.empty or msg.service or not msg.media:
                continue
            media_obj = getattr(msg, msg.media.value, None)
            if not media_obj:
                continue
            valid += 1
            outlist.append({
                "file_id": media_obj.file_id,
                "caption": msg.caption or "",
                "title": getattr(media_obj, "file_name", ""),
                "size": media_obj.file_size,
                "protect": message.command[0] == "pbatch"
            })

            if valid % 20 == 0:
                await status.edit(f"Total: {total}\nProcessed: {valid}")

    fname = f"batch_{message.from_user.id}.json"
    with open(fname, "w") as f:
        json.dump(outlist, f, indent=2)

    try:
        up = await bot.send_document(
            LOG_CHANNEL, fname,
            file_name=fname,
            caption=f"🗂️ Batch generated with {valid} files"
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return await status.edit("Failed to send batch file.")

    os.remove(fname)
    file_id, _ = unpack_new_file_id(up.document.file_id)
    await status.edit(f"✅ Link generated for {valid} files:\nhttps://t.me/{temp.U_NAME}?start=BATCH-{file_id}")
