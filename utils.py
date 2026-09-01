import logging
import asyncio
import aiohttp
import re
import os
from urllib.parse import quote
from datetime import datetime, timedelta
from typing import Union, List, Tuple
from pyrogram import Client, enums
from pyrogram.errors import UserNotParticipant
from pyrogram.types import Message, InlineKeyboardButton, MessageEntity
from database.users_chats_db import db
from info import ADMINS, AUTH_CHANNEL, MAX_LIST_ELM
from bs4 import BeautifulSoup  # Although imported, not used in the provided code
import requests  # Although imported, not used in the provided code
from pyrogram.enums import MessageEntityType


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)

SMART_OPEN = '“'
SMART_CLOSE = '”'
START_CHAR = ('\'', '"', SMART_OPEN)

class temp(object):
    AUTO_FILTER = True
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None
    CURRENT=int(os.environ.get("SKIP", 1))
    CANCEL = False
    U_NAME = None
    B_NAME = None
    REQ_CHANNEL1 = None
    REQ_CHANNEL2 = None
    REQ_CHANNEL3 = None
    REQ_CHANNEL1_2 = None
    REQ_CHANNEL2_2 = None
    REQ_CHANNEL3_2 = None
    COUNT_THRESHOLD1 = None
    COUNT_THRESHOLD2 = None
    COUNT_THRESHOLD3 = None

async def load_datas(id: int):
    k = await db.get_loadout(id)
    d = await db.get_autofilter()
    temp.REQ_CHANNEL1 = k.get('channel1')
    temp.REQ_CHANNEL2 = k.get('channel2')
    temp.REQ_CHANNEL3 = k.get('channel3')
    temp.REQ_CHANNEL1_2 = k.get('channel1_2')
    temp.REQ_CHANNEL2_2 = k.get('channel2_2')
    temp.REQ_CHANNEL3_2 = k.get('channel3_2')
    temp.COUNT_THRESHOLD1 = k.get('channel1_threshold')
    temp.COUNT_THRESHOLD2 = k.get('channel2_threshold')
    temp.COUNT_THRESHOLD3 = k.get('channel3_threshold')
    temp.AUTO_FILTER = d.get('autofilter')
    print(f"Loadout for ID {id} has been loaded.")


class AutoDeleteQueue:
    def __init__(self):
        self._queue = {} # Stores {chat_id: {message_id: deletion_time}}

    def add_message(self, chat_id: int, message_id: int, deletion_time: datetime):
        if chat_id not in self._queue:
            self._queue[chat_id] = {}
        self._queue[chat_id][message_id] = deletion_time
        logger.info(f"Added message {message_id} in chat {chat_id} for auto-deletion at {deletion_time}")

    def get_messages_to_process(self):
        """
        Returns a dictionary of {chat_id: {message_id: deletion_time}} for messages due for deletion.
        """
        current_time = datetime.now()
        due_messages = {}
        for chat_id, messages in list(self._queue.items()): # Iterate over a copy
            for message_id, deletion_time in list(messages.items()): # Iterate over a copy
                if current_time >= deletion_time:
                    if chat_id not in due_messages:
                        due_messages[chat_id] = {}
                    due_messages[chat_id][message_id] = deletion_time
        return due_messages

    def remove_message(self, chat_id: int, message_id: int):
        """
        Removes a message from the queue.
        """
        if chat_id in self._queue and message_id in self._queue[chat_id]:
            del self._queue[chat_id][message_id]
            if not self._queue[chat_id]: # If no messages left in the chat, remove the chat entry
                del self._queue[chat_id]
            logger.info(f"Removed message {message_id} from auto-delete queue in chat {chat_id}")

auto_delete_queue = AutoDeleteQueue()

async def check_subscription(client: Client, user_id: int, channel_id: Union[str, int]) -> bool:
    if user_id in ADMINS:
        return True
    try:
        member = await client.get_chat_member(channel_id, user_id)
        return member.status not in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED)
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.exception(f"Error checking subscription for {user_id} in {channel_id}: {e}")
        return False

async def check_loop_sub(client, message):
    count = 0
    while count < 15:
        check = await is_requested_one(client, message)
        check2 = await is_requested_two(client, message)
        count += 1
        if check and check2:
            return True
        await asyncio.sleep(1.5)
    return False

async def check_loop_sub1(client, message):
    count = 0
    while count < 15:
        if await is_requested_one(client, message):
            return True
        count += 1
        await asyncio.sleep(1)
    return False

async def check_loop_sub2(client, message):
    count = 0
    while count < 15:
        if await is_requested_two(client, message):
            return True
        count += 1
        await asyncio.sleep(1)
    return False

async def check_loop_sub3(client, message):
    count = 0
    while count < 15:
        if await is_requested_three(client, message):
            return True
        count += 1
        await asyncio.sleep(1)
    return False


async def is_requested_one(self , message):
    user = await db.get_req_one(int(message.from_user.id))
    if user:
        return True
    if message.from_user.id in ADMINS:
        return True
    try:
        user = await self.get_chat_member(int(temp.REQ_CHANNEL1), message.from_user.id)
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.exception(e)
        pass
    else:
        if not (user.status == enums.ChatMemberStatus.BANNED):
            return True
        else:
            pass
    return False
    
async def is_requested_two(self, message):
    user = await db.get_req_two(int(message.from_user.id))
    if user:
        return True
    if message.from_user.id in ADMINS:
        return True
    try:
        user = await self.get_chat_member(int(temp.REQ_CHANNEL2), message.from_user.id)
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.exception(e)
        pass
    else:
        if not (user.status == enums.ChatMemberStatus.BANNED):
            return True
        else:
            pass
    return False

async def is_requested_three(self, message):
    user = await db.get_req_three(int(message.from_user.id))
    if user:
        return True
    if message.from_user.id in ADMINS:
        return True
    try:
        user = await self.get_chat_member(int(temp.REQ_CHANNEL3), message.from_user.id)
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.exception(e)
        pass
    else:
        if not (user.status == enums.ChatMemberStatus.BANNED):
            return True
        else:
            pass
    return False

async def is_subscribed(bot, query):
    try:
        user = await bot.get_chat_member(AUTH_CHANNEL, query.from_user.id)
    except UserNotParticipant:
        pass
    except Exception as e:
        logger.exception(e)
    else:
        if user.status != 'kicked':
            return True

    return False
    
def get_size(size: int) -> str:
    if not size:
        return ""
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"

def split_list(input_list: List, chunk_size: int) -> List[List]:
    for i in range(0, len(input_list), chunk_size):
        yield input_list[i:i + chunk_size]

def get_file_id(msg: Message):
    if msg.media:
        for media_type in enums.MessageMediaType:
            media = getattr(msg, media_type, None)
            if media:
                setattr(media, "message_type", media_type.value)
                return media
    return None

def extract_user(message: Message) -> Tuple[Union[int, str], str]:
    user_id = None
    first_name = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        first_name = message.reply_to_message.from_user.first_name
    elif message.command and len(message.command) > 1:
        arg = message.command[1]
        entity = message.entities[1] if len(message.entities) > 1 else None
        if entity and entity.type == enums.MessageEntityType.TEXT_MENTION:
            user_id = entity.user.id
            first_name = entity.user.first_name
        else:
            try:
                user_id = int(arg)
                first_name = arg  # Fallback, actual name might be different
            except ValueError:
                user_id = arg
                first_name = arg
    else:
        user_id = message.from_user.id
        first_name = message.from_user.first_name
    return user_id, first_name

def list_to_str(data_list: List) -> str:
    if not data_list:
        return "N/A"
    elif len(data_list) == 1:
        return str(data_list[0])
    elif MAX_LIST_ELM and len(data_list) > MAX_LIST_ELM:
        return ', '.join(map(str, data_list[:MAX_LIST_ELM])) + '...'
    else:
        return ', '.join(map(str, data_list))

def last_online(from_user):
    status = from_user.status
    if from_user.is_bot:
        return "🤖 Bot :("
    elif status == enums.UserStatus.RECENTLY:
        return "Recently"
    elif status == enums.UserStatus.LAST_WEEK:
        return "Within the last week"
    elif status == enums.UserStatus.LAST_MONTH:
        return "Within the last month"
    elif status == enums.UserStatus.LONG_AGO:
        return "A long time ago :("
    elif status == enums.UserStatus.ONLINE:
        return "Currently Online"
    elif status == enums.UserStatus.OFFLINE and from_user.last_online_date:
        return from_user.last_online_date.strftime("%a, %d %b %Y, %H:%M:%S")
    return "N/A"

def split_quotes(text: str) -> List[str]:
    if not any(text.startswith(char) for char in START_CHAR):
        return text.split(None, 1)
    first_char = text[0]
    counter = 1
    while counter < len(text):
        if text[counter] == "\\":
            counter += 1
        elif text[counter] == first_char or (first_char == SMART_OPEN and text[counter] == SMART_CLOSE):
            break
        counter += 1
    else:
        return text.split(None, 1)

    key = remove_escapes(text[1:counter].strip())
    rest = text[counter + 1:].strip()
    return [key, rest]

def gfilterparser(text: str, keyword: str) -> Tuple[str, List[List[InlineKeyboardButton]], Union[List[str], None]]:
    text = text.replace("\n", "\\n").replace("\t", "\\t")
    buttons = []
    note_data = ""
    prev = 0
    alerts = []
    i = 0
    for match in BTN_URL_REGEX.finditer(text):
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check >= 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1

        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            button_type = match.group(3)
            button_label = match.group(2)
            button_data = match.group(4).replace(" ", "")
            same_line = bool(match.group(5))

            button = InlineKeyboardButton(text=button_label, callback_data=f"gfilteralert:{i}:{keyword}") if button_type == "buttonalert" else InlineKeyboardButton(text=button_label, url=button_data)

            if same_line and buttons:
                buttons[-1].append(button)
            else:
                buttons.append([button])

            if button_type == "buttonalert":
                alerts.append(match.group(4))
                i += 1
        else:
            note_data += text[prev:match.start(1) - 1]
            prev = match.start(1)

    note_data += text[prev:]
    return note_data, buttons, alerts if alerts else None

def remove_escapes(text: str) -> str:
    result = ""
    escaped = False
    for char in text:
        if escaped:
            result += char
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result += char
    return result

def humanbytes(size: int) -> str:
    if not size:
        return ""
    power = 1024
    n = 0
    units = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {units.get(n, 'P')}B"

async def add_auto_delete_message(message_id: int, chat_id: int, delay_minutes: int = 5):
    """
    Adds a message to the auto-delete queue.
    :param message_id: The ID of the message to delete.
    :param chat_id: The chat ID where the message was sent.
    :param delay_minutes: The delay in minutes before deletion.
    """
    deletion_time = datetime.now() + timedelta(seconds=delay_minutes)
    auto_delete_queue.add_message(chat_id, message_id, deletion_time)


async def delete_messages_loop(client):
    """
    Continuously checks for messages to delete from the auto-delete queue.
    """
    while True:
        messages_to_delete = auto_delete_queue.get_messages_to_process()
        for chat_id, messages in messages_to_delete.items():
            for message_id, deletion_time in messages.items():
                try:
                    await client.delete_messages(chat_id=chat_id, message_ids=message_id)
                    logger.info(f"Deleted message {message_id} from chat {chat_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete message {message_id} in chat {chat_id}: {e}")
                finally:
                    # Remove the message from the queue regardless of success or failure
                    auto_delete_queue.remove_message(chat_id, message_id)
        await asyncio.sleep(60) # Check every 60 seconds (adjust as needed)

def premium_emoji(text, emoji_map):
    entities = []

    for emoji, emoji_id in emoji_map.items():
        start = text.index(emoji)

        entities.append(
            MessageEntity(
                type=MessageEntityType.CUSTOM_EMOJI,
                offset=start,
                length=len(emoji),
                custom_emoji_id=str(emoji_id)
            )
        )

    return entities

TMDB_CACHE = {}

def clean_file_name_for_search(file_name: str) -> str:
    if not file_name:
        return ""
    raw = str(file_name)
    se_match = re.search(r"(?i)\bS(\d+)\s*E(\d+)\b", raw)
    if not se_match:
        se_match = re.search(r"(?i)\b(\d+)x(\d+)\b", raw)
    
    year_match = re.search(r"\b(19\d\d|20\d\d)\b", raw)
    
    clean = raw
    if se_match:
        clean = clean[:se_match.start()]
    elif year_match:
        clean = clean[:year_match.start()]
    
    clean = re.sub(r"📂 Fɪʟᴇ ɴᴀṁᴇ :", "", clean)
    clean = re.sub(r"[\[\(_\.\-]", " ", clean)
    clean = re.sub(r"\b(720p|1080p|2160p|4k|HDRip|WEBRip|WEB-DL|BluRay|HEVC|x264|x265|AAC|ESub|Hindi|Tamil|Telugu|English|Malayalam)\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


async def resolve_tmdb_stream_url(file_name: str = None, file_id: str = None) -> str:
    from info import STREAM_URL
    clean = clean_file_name_for_search(file_name)
    if not clean:
        return f"{STREAM_URL.rstrip('/')}/search"

    raw = str(file_name)
    se_match = re.search(r"(?i)\bS(\d+)\s*E(\d+)\b", raw)
    if not se_match:
        se_match = re.search(r"(?i)\b(\d+)x(\d+)\b", raw)
    
    season = int(se_match.group(1)) if se_match else 1
    episode = int(se_match.group(2)) if se_match else 1
    is_tv = bool(se_match)

    year_match = re.search(r"\b(19\d\d|20\d\d)\b", raw)
    year = year_match.group(1) if year_match else None

    cache_key = f"{clean.lower()}_{year}_{is_tv}"
    if cache_key in TMDB_CACHE:
        tmdb_id, media_type = TMDB_CACHE[cache_key]
    else:
        tmdb_id, media_type = None, None
        try:
            api_key = "4e44d9029b1270a757cddc766a1bcb63"
            query_url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={clean.replace(' ', '+')}"
            if year:
                query_url += f"&year={year}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(query_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        if results:
                            target = results[0]
                            tmdb_id = target.get("id")
                            media_type = target.get("media_type")
                            TMDB_CACHE[cache_key] = (tmdb_id, media_type)
        except Exception as e:
            logger.debug(f"TMDB search failed for {clean}: {e}")

    base = STREAM_URL.rstrip('/')
    if tmdb_id:
        if is_tv or media_type == "tv":
            return f"{base}/watch/tv/{tmdb_id}?s={season}&e={episode}"
        else:
            return f"{base}/watch/movie/{tmdb_id}"

    return f"{base}/search/{quote(clean)}"


async def get_stream_buttons_async(file_id=None, file_name=None):
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    url = await resolve_tmdb_stream_url(file_name=file_name, file_id=file_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖥️ Watch Online on Website", url=url)
        ]
    ])


def get_stream_buttons(file_id=None, file_name=None, stream_url=None):
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from info import STREAM_URL
    base = STREAM_URL.rstrip('/')
    if stream_url:
        url = stream_url
    elif file_name:
        clean = clean_file_name_for_search(file_name)
        if clean:
            url = f"{base}/search/{quote(clean)}"
        elif file_id and str(file_id).isdigit():
            url = f"{base}/watch/movie/{file_id}"
        else:
            url = f"{base}/search"
    elif file_id and str(file_id).isdigit():
        url = f"{base}/watch/movie/{file_id}"
    else:
        url = f"{base}/search"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖥️ Watch Online on Website", url=url)
        ]
    ])



def get_search_url(query: str) -> str:
    from info import STREAM_URL
    base = STREAM_URL.rstrip('/')
    clean_q = str(query or "").strip()
    return f"{base}/search/{quote(clean_q)}" if clean_q else f"{base}/search"



