import io
from pyrogram import filters, Client, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.gfilters_mdb import add_gfilter, get_gfilters, delete_gfilter, count_gfilters, del_allg
from utils import get_file_id, gfilterparser, split_quotes
from info import ADMINS


@Client.on_message(filters.command(['gfilter', 'addg']) & filters.incoming & filters.user(ADMINS))
async def addgfilter(client, message):
    args = message.text.html.split(None, 1)
    if len(args) < 2:
        await message.reply_text("Command Incomplete :(", quote=True)
        return

    extracted = split_quotes(args[1])
    text = extracted[0].lower()

    if not message.reply_to_message and len(extracted) < 2:
        await message.reply_text("Add some content to save your filter!", quote=True)
        return

    reply_text, btn, alert, fileid = None, None, None, None

    if len(extracted) >= 2 and not message.reply_to_message:
        reply_text, btn, alert = gfilterparser(extracted[1], text)
        if not reply_text:
            await message.reply_text("You cannot have buttons alone, give some text to go with it!", quote=True)
            return
    elif message.reply_to_message:
        rm = message.reply_to_message.reply_markup
        msg = get_file_id(message.reply_to_message)
        if rm:
            try:
                btn = rm.inline_keyboard
            except:
                btn = []
        if msg:
            fileid = msg.file_id
            reply_text = message.reply_to_message.caption.html if message.reply_to_message.caption else ""
        else:
            reply_text = message.reply_to_message.text.html if message.reply_to_message.text else ""
        if message.reply_to_message.media and not message.reply_to_message.sticker:
            reply_text, btn, alert = gfilterparser(extracted[1], text) if len(extracted) >= 2 else (message.reply_to_message.caption.html if message.reply_to_message.caption else "", [], None)
        elif message.reply_to_message.text and len(extracted) >= 2:
            reply_text, btn, alert = gfilterparser(extracted[1], text)

    if reply_text is not None:
        await add_gfilter('gfilters', text, reply_text, btn, fileid, alert)
        await message.reply_text(
            f"GFilter for  `{text}`  added",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN
        )


@Client.on_message(filters.command(['viewgfilters', 'gfilters']) & filters.incoming & filters.user(ADMINS))
async def get_all_gfilters(client, message):
    texts = await get_gfilters('gfilters')
    count = await count_gfilters('gfilters')
    if not count:
        await message.reply_text("There are no active gfilters.", quote=True)
        return

    gfilterlist = f"Total number of gfilters : {count}\n\n"
    for text in texts:
        gfilterlist += f" ×  `{text}`\n"

    if len(gfilterlist) > 4096:
        with io.BytesIO(gfilterlist.replace("`", "").encode()) as keyword_file:
            keyword_file.name = "keywords.txt"
            await message.reply_document(document=keyword_file, quote=True)
    else:
        await message.reply_text(text=gfilterlist, quote=True, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command('delg') & filters.incoming & filters.user(ADMINS))
async def deletegfilter(client, message):
    try:
        _, text = message.text.split(" ", 1)
        query = text.lower()
        await delete_gfilter(message, query, 'gfilters')
    except ValueError:
        await message.reply_text(
            "<i>Mention the gfiltername which you wanna delete!</i>\n\n"
            "<code>/delg gfiltername</code>\n\n"
            "Use /viewgfilters to view all available gfilters",
            quote=True
        )


@Client.on_message(filters.command('delallg') & filters.user(ADMINS))
async def delallgfilters(client, message):
    await message.reply_text(
        "Do you want to continue??",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="YES", callback_data="gfiltersdeleteallconfirm")],
             [InlineKeyboardButton(text="CANCEL", callback_data="gfiltersdeleteallcancel")]]
        ),
        quote=True
    )

@Client.on_callback_query(filters.regex('^gfiltersdeleteall'))
async def delete_all_gfilters_callback(client, callback_query):
    """Handle callbacks for global filter deletion confirmation"""
    if callback_query.data == "gfiltersdeleteallconfirm":
        await del_allg(callback_query.message, 'gfilters')
    else:
        await callback_query.message.edit_text("Deletion cancelled")


