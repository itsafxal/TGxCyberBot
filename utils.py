import logging
import asyncio
import aiohttp
import re
import os
import base64
import random
from urllib.parse import quote
from datetime import datetime, timedelta
from typing import Union, List, Tuple, Optional, Dict, Any
from pyrogram import Client, enums
from pyrogram.errors import (
    UserNotParticipant, MessageNotModified, FloodWait,
    MessageIdInvalid, QueryIdInvalid, PeerIdInvalid, UserIsBlocked, InputUserDeactivated
)
from pyrogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity, LinkPreviewOptions
from database.users_chats_db import db
from info import ADMINS, AUTH_CHANNEL, MAX_LIST_ELM
from pyrogram.enums import MessageEntityType
import time

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)

SMART_OPEN = '“'
SMART_CLOSE = '”'
START_CHAR = ('\'', '"', SMART_OPEN)

# --- Performance & Telemetry Instrumentation ---
class PerfTracker:
    def __init__(self, action: str, user_id: int = 0, query: str = ""):
        self.action = action
        self.user_id = user_id
        self.query = query
        self.start_t = time.time()
        self.db_ms = 0.0
        self.telegram_ms = 0.0
        self.telegram_calls = 0
        self.send_count = 0
        self.edit_count = 0
        self.delete_count = 0
        self.get_participant_count = 0
        self.retries = 0
        self.flood_wait_seconds = 0
        self.cache_hit = False

    def log(self):
        total_ms = int((time.time() - self.start_t) * 1000)
        logger.info(
            f"[PERF] action={self.action} user_id={self.user_id} query={self.query!r} "
            f"total_ms={total_ms} db_ms={int(self.db_ms)} telegram_ms={int(self.telegram_ms)} "
            f"telegram_calls={self.telegram_calls} send={self.send_count} edit={self.edit_count} "
            f"delete={self.delete_count} get_participant={self.get_participant_count} "
            f"retries={self.retries} flood_wait={self.flood_wait_seconds} cache_hit={self.cache_hit}"
        )

class ApiCallMetrics:
    def __init__(self):
        self.counts = {
            "send_message": 0,
            "edit_message": 0,
            "delete_message": 0,
            "get_participant": 0,
            "answer_callback": 0,
            "flood_wait_events": 0,
            "rpc_errors": 0,
        }

    def inc(self, key: str, val: int = 1):
        if key in self.counts:
            self.counts[key] += val

    def get_stats(self) -> Dict[str, int]:
        return dict(self.counts)

GLOBAL_METRICS = ApiCallMetrics()

# --- Concurrency & In-Flight Tracking ---
class InFlightTracker:
    """Tracks in-flight operations per key (e.g. (user_id, message_id)) to deduplicate concurrent requests."""
    def __init__(self):
        self._active = set()

    def acquire(self, key) -> bool:
        if key in self._active:
            return False
        self._active.add(key)
        return True

    def release(self, key):
        self._active.discard(key)

IN_FLIGHT_CALLBACKS = InFlightTracker()

# --- Short-Lived Membership Cache ---
class MembershipCache:
    """
    Short-lived TTL cache for chat membership status.
    Prevents channels.GetParticipant request storms without permanently caching.
    """
    def __init__(self, positive_ttl: float = 60.0, negative_ttl: float = 8.0):
        self._cache = {}  # (user_id, channel_id) -> (is_member, expire_at)
        self.positive_ttl = positive_ttl
        self.negative_ttl = negative_ttl

    def get(self, user_id: int, channel_id: int) -> Optional[bool]:
        if not user_id or not channel_id:
            return None
        key = (int(user_id), int(channel_id))
        entry = self._cache.get(key)
        if entry is not None:
            is_member, expire_at = entry
            if time.time() < expire_at:
                return is_member
            else:
                self._cache.pop(key, None)
        return None

    def set(self, user_id: int, channel_id: int, is_member: bool):
        if not user_id or not channel_id:
            return
        key = (int(user_id), int(channel_id))
        ttl = self.positive_ttl if is_member else self.negative_ttl
        self._cache[key] = (is_member, time.time() + ttl)

    def invalidate(self, user_id: int, channel_id: Optional[int] = None):
        if channel_id is not None:
            self._cache.pop((int(user_id), int(channel_id)), None)
        else:
            to_del = [k for k in self._cache if k[0] == int(user_id)]
            for k in to_del:
                self._cache.pop(k, None)

MEMBERSHIP_CACHE = MembershipCache(positive_ttl=60.0, negative_ttl=8.0)

# --- Safe Telegram Operations ---

async def safe_delete_message(client_or_message, chat_id: Optional[int] = None, message_id: Optional[int] = None) -> bool:
    """
    Best-effort safe message deletion.
    Handles MessageDeleteForbidden, MessageIdInvalid, PeerIdInvalid, FloodWait gracefully.
    A failed deletion will never crash or break callback flow.
    """
    GLOBAL_METRICS.inc("delete_message")
    try:
        if hasattr(client_or_message, "delete") and callable(client_or_message.delete):
            await client_or_message.delete()
            return True
        elif chat_id and message_id:
            await client_or_message.delete_messages(chat_id=chat_id, message_ids=message_id)
            return True
    except (MessageNotModified, MessageIdInvalid, PeerIdInvalid):
        return False
    except FloodWait as e:
        logger.warning(f"Safe delete FloodWait: {e.value}s")
        GLOBAL_METRICS.inc("flood_wait_events")
        return False
    except Exception as e:
        err_str = str(e)
        if "MESSAGE_DELETE_FORBIDDEN" in err_str or "MessageDeleteForbidden" in type(e).__name__:
            logger.debug(f"Safe delete: delete forbidden in chat {chat_id}: {e}")
        else:
            logger.debug(f"Safe delete error: {e}")
        return False
    return False

async def safe_edit_message_text(
    message_or_query,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode = None,
    link_preview_options: Optional[LinkPreviewOptions] = None
) -> bool:
    """
    Safe message text editing with equality check, bounded FloodWait handling, and transient RPC backoff.
    """
    # Pre-check equality to avoid unnecessary Telegram RPC
    curr_msg = message_or_query.message if isinstance(message_or_query, CallbackQuery) else message_or_query
    if hasattr(curr_msg, "text") and curr_msg.text == text:
        if reply_markup is None or (hasattr(curr_msg, "reply_markup") and curr_msg.reply_markup == reply_markup):
            return True

    GLOBAL_METRICS.inc("edit_message")
    for attempt in range(3):
        try:
            if hasattr(message_or_query, "edit_text"):
                await message_or_query.edit_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    link_preview_options=link_preview_options
                )
            elif hasattr(message_or_query, "edit_message_text"):
                await message_or_query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    link_preview_options=link_preview_options
                )
            return True
        except MessageNotModified:
            return True
        except (MessageIdInvalid, QueryIdInvalid, PeerIdInvalid, UserIsBlocked, InputUserDeactivated):
            return False
        except FloodWait as e:
            GLOBAL_METRICS.inc("flood_wait_events")
            logger.warning(f"FloodWait in safe_edit_message_text: {e.value}s (attempt {attempt+1})")
            if attempt == 0 and e.value <= 3:
                await asyncio.sleep(e.value + 0.1)
            else:
                # Do not retry prematurely if wait > 3s or second attempt
                return False
        except Exception as e:
            err_str = str(e)
            if any(transient in err_str for transient in ["RPC_CALL_FAIL", "INTERDC", "500", "No workers running", "TimeoutError"]):
                GLOBAL_METRICS.inc("rpc_errors")
                logger.warning(f"Transient RPC error in safe_edit_message_text: {e} (attempt {attempt+1})")
                if attempt < 2:
                    await asyncio.sleep(0.3 * (attempt + 1) + random.uniform(0.05, 0.15))
                    continue
            logger.error(f"Error in safe_edit_message_text: {e}")
            return False
    return False

async def safe_edit_reply_markup(
    message_or_query,
    reply_markup: Optional[InlineKeyboardMarkup] = None
) -> bool:
    """
    Safe reply markup editing with equality check and FloodWait / RPC backoff.
    """
    # Pre-check equality to avoid unnecessary Telegram RPC
    curr_msg = message_or_query.message if isinstance(message_or_query, CallbackQuery) else message_or_query
    if hasattr(curr_msg, "reply_markup") and curr_msg.reply_markup == reply_markup:
        return True

    GLOBAL_METRICS.inc("edit_message")
    for attempt in range(3):
        try:
            if hasattr(message_or_query, "edit_reply_markup"):
                await message_or_query.edit_reply_markup(reply_markup=reply_markup)
            elif hasattr(message_or_query, "edit_message_reply_markup"):
                await message_or_query.edit_message_reply_markup(reply_markup=reply_markup)
            return True
        except MessageNotModified:
            return True
        except (MessageIdInvalid, QueryIdInvalid, PeerIdInvalid, UserIsBlocked, InputUserDeactivated):
            return False
        except FloodWait as e:
            GLOBAL_METRICS.inc("flood_wait_events")
            logger.warning(f"FloodWait in safe_edit_reply_markup: {e.value}s (attempt {attempt+1})")
            if attempt == 0 and e.value <= 3:
                await asyncio.sleep(e.value + 0.1)
            else:
                # Do not retry prematurely if wait > 3s or second attempt
                return False
        except Exception as e:
            err_str = str(e)
            if any(transient in err_str for transient in ["RPC_CALL_FAIL", "INTERDC", "500", "No workers running", "TimeoutError"]):
                GLOBAL_METRICS.inc("rpc_errors")
                logger.warning(f"Transient RPC error in safe_edit_reply_markup: {e} (attempt {attempt+1})")
                if attempt < 2:
                    await asyncio.sleep(0.3 * (attempt + 1) + random.uniform(0.05, 0.15))
                    continue
            logger.error(f"Error in safe_edit_reply_markup: {e}")
            return False
    return False

async def safe_answer_callback(query, text: Optional[str] = None, show_alert: bool = False, url: Optional[str] = None) -> bool:
    """Safe answer_callback_query to handle expired queries without breaking flow."""
    GLOBAL_METRICS.inc("answer_callback")
    try:
        await query.answer(text=text, show_alert=show_alert, url=url)
        return True
    except (QueryIdInvalid, MessageIdInvalid, PeerIdInvalid):
        return False
    except FloodWait as e:
        GLOBAL_METRICS.inc("flood_wait_events")
        logger.debug(f"FloodWait in safe_answer_callback: {e.value}s")
        return False
    except Exception as e:
        logger.debug(f"Error in safe_answer_callback: {e}")
        return False


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
    FILTER_DEL_TIME = 300
    FILE_DEL_TIME = 900

async def load_datas(id: int):
    k = await db.get_loadout(id)
    d = await db.get_autofilter()
    del_s = await db.get_del_settings()
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
    temp.FILTER_DEL_TIME = del_s.get('filter_del_time', 300)
    temp.FILE_DEL_TIME = del_s.get('file_del_time', 900)
    print(f"Loadout for ID {id} has been loaded.")

def format_time_str(seconds: int) -> str:
    """Formats seconds into human-readable string (e.g. 15 minutes, 30 seconds)."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = seconds // 60
    rem_sec = seconds % 60
    if minutes < 60:
        res = f"{minutes} minute{'s' if minutes != 1 else ''}"
        if rem_sec:
            res += f" {rem_sec} second{'s' if rem_sec != 1 else ''}"
        return res
    hours = minutes // 60
    rem_min = minutes % 60
    res = f"{hours} hour{'s' if hours != 1 else ''}"
    if rem_min:
        res += f" {rem_min} minute{'s' if rem_min != 1 else ''}"
    return res

def parse_time_to_seconds(time_str: str) -> int:
    """Parses strings like '300', '5m', '15m', '1h', '30s' to integer seconds."""
    time_str = str(time_str).strip().lower()
    if time_str.isdigit():
        return int(time_str)
    
    match = re.match(r"^(\d+)\s*([s|m|h|d])$", time_str)
    if not match:
        raise ValueError(f"Invalid time format: {time_str}")
    val, unit = int(match.group(1)), match.group(2)
    multiplier = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return val * multiplier[unit]

async def add_auto_delete_message(chat_id: int, message_id: int, delay_seconds: int = None, msg_type: str = "general", file_id: str = None):
    if delay_seconds is None:
        delay_seconds = temp.FILTER_DEL_TIME if msg_type == "filter" else temp.FILE_DEL_TIME
    delete_at = time.time() + int(delay_seconds)
    await db.add_to_auto_delete(chat_id, message_id, delete_at, msg_type, file_id=file_id)
    await db.add_trash_message(chat_id, message_id)

async def track_bot_message(chat_id: int, message_id: int):
    await db.add_trash_message(chat_id, message_id)

async def delete_messages_loop(client):
    """
    Background worker that continuously processes past-due auto delete messages stored in DB.
    Persists across bot restarts.
    """
    logger.info("Auto-delete worker loop started.")
    while getattr(client, "_is_running", True):
        try:
            now = time.time()
            due_items = await db.get_due_auto_delete_messages(now)
            if due_items:
                chat_map = {}
                file_notices = [] # Stores (chat_id, file_id) for sending notices

                for item in due_items:
                    cid = item['chat_id']
                    mid = item['message_id']
                    if cid not in chat_map:
                        chat_map[cid] = []
                    chat_map[cid].append(mid)

                    if item.get("msg_type") == "file" and item.get("file_id"):
                        file_notices.append((cid, item.get("file_id")))

                for cid, mids in chat_map.items():
                    for i in range(0, len(mids), 100):
                        chunk = mids[i:i + 100]
                        try:
                            GLOBAL_METRICS.inc("delete_message", len(chunk))
                            await client.delete_messages(chat_id=cid, message_ids=chunk)
                        except Exception as e:
                            logger.debug(f"Error deleting messages in chat {cid}: {e}")
                        
                        for mid in chunk:
                            await db.remove_from_auto_delete(cid, mid)
                        await db.remove_trash_messages(cid, chunk)
                        await asyncio.sleep(0.3)

                # Send post-deletion notices for deleted files
                post_text = (
                    "⚠️ 🗑️ <b>𝙔𝙤𝙪𝙧 𝙧𝙚𝙦𝙪𝙚𝙨𝙩𝙚𝙙 𝙛𝙞𝙡𝙚 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙙𝙚𝙡𝙚𝙩𝙚𝙙!</b>\n\n"
                    "📥 <i>𝘐𝘧 𝘺𝘰𝘶 𝘸𝘢𝘯𝘵 𝘵𝘩𝘦 𝙛𝙞𝙡𝙚, 𝘊𝘭𝘪𝘤𝘬 below button</i>"
                )
                for cid, fid in file_notices:
                    file_id_val = str(fid)
                    if not (file_id_val.startswith("file_") or file_id_val.startswith("filep_") or file_id_val.startswith("getfile-") or file_id_val.startswith("BATCH-") or file_id_val.startswith("DSTORE-")):
                        file_id_val = f"file_{file_id_val}"
                    start_link = f"https://t.me/{temp.U_NAME}?start={file_id_val}"
                    btn = InlineKeyboardMarkup([[
                        InlineKeyboardButton("📥 Get File Again", url=start_link)
                    ]])
                    try:
                        GLOBAL_METRICS.inc("send_message")
                        sent_notice = await client.send_message(
                            chat_id=cid,
                            text=post_text,
                            reply_markup=btn,
                            parse_mode=enums.ParseMode.HTML
                        )
                        await db.add_trash_message(cid, sent_notice.id)
                    except Exception as e:
                        logger.debug(f"Error sending file deletion notice in chat {cid}: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in delete_messages_loop: {e}", exc_info=True)

        await asyncio.sleep(5)

async def clean_all_trash(client):
    """
    Deletes all messages sent by bot across all chats tracked in trash_messages DB.
    Used by /deletetrash command and weekly cleanup job.
    """
    trash_items = await db.get_all_trash_messages()
    if not trash_items:
        return 0, 0

    chat_map = {}
    for item in trash_items:
        cid = item['chat_id']
        mid = item['message_id']
        if cid not in chat_map:
            chat_map[cid] = []
        chat_map[cid].append(mid)

    total_deleted = 0
    total_chats = len(chat_map)

    for cid, mids in chat_map.items():
        for i in range(0, len(mids), 100):
            chunk = mids[i:i + 100]
            try:
                GLOBAL_METRICS.inc("delete_message", len(chunk))
                await client.delete_messages(chat_id=cid, message_ids=chunk)
                total_deleted += len(chunk)
            except Exception as e:
                logger.debug(f"Error deleting trash messages in chat {cid}: {e}")
            await asyncio.sleep(0.3)

    await db.delete_all_trash_from_db()
    return total_deleted, total_chats

class AutoDeleteQueue:
    def __init__(self):
        self._queue = {}

    def add_message(self, chat_id: int, message_id: int, deletion_time: datetime):
        if chat_id not in self._queue:
            self._queue[chat_id] = {}
        self._queue[chat_id][message_id] = deletion_time
        logger.info(f"Added message {message_id} in chat {chat_id} for auto-deletion at {deletion_time}")

    def get_messages_to_process(self):
        current_time = datetime.now()
        due_messages = {}
        for chat_id, messages in list(self._queue.items()):
            for message_id, deletion_time in list(messages.items()):
                if current_time >= deletion_time:
                    if chat_id not in due_messages:
                        due_messages[chat_id] = {}
                    due_messages[chat_id][message_id] = deletion_time
        return due_messages

    def remove_message(self, chat_id: int, message_id: int):
        if chat_id in self._queue and message_id in self._queue[chat_id]:
            del self._queue[chat_id][message_id]
            if not self._queue[chat_id]:
                del self._queue[chat_id]
            logger.info(f"Removed message {message_id} from auto-delete queue in chat {chat_id}")

auto_delete_queue = AutoDeleteQueue()

async def check_subscription(client: Client, user_id: int, channel_id: Union[str, int]) -> bool:
    if user_id in ADMINS:
        return True
    try:
        GLOBAL_METRICS.inc("get_participant")
        member = await client.get_chat_member(channel_id, user_id)
        return member.status not in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED)
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.exception(f"Error checking subscription for {user_id} in {channel_id}: {e}")
        return False

async def check_channel_membership(client, user_id: int, channel_id: int, slot: int) -> bool:
    """Helper to check membership status with cache, DB, and GetParticipant API fallback."""
    if not user_id or not channel_id:
        return True
    if user_id in ADMINS:
        return True

    # 1. Check in-memory TTL cache
    cached = MEMBERSHIP_CACHE.get(user_id, channel_id)
    if cached is not None:
        return cached

    # 2. Check Database join-request tables
    try:
        if slot == 1:
            db_user = await db.get_req_one(user_id)
        elif slot == 2:
            db_user = await db.get_req_two(user_id)
        elif slot == 3:
            db_user = await db.get_req_three(user_id)
        else:
            db_user = None

        if db_user:
            MEMBERSHIP_CACHE.set(user_id, channel_id, True)
            return True
    except Exception as e:
        logger.debug(f"DB check error for slot {slot}: {e}")

    # 3. Call Telegram get_chat_member (GetParticipant)
    GLOBAL_METRICS.inc("get_participant")
    try:
        member = await client.get_chat_member(int(channel_id), user_id)
        is_joined = (member.status not in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED))
        MEMBERSHIP_CACHE.set(user_id, channel_id, is_joined)
        return is_joined
    except UserNotParticipant:
        MEMBERSHIP_CACHE.set(user_id, channel_id, False)
        return False
    except FloodWait as e:
        logger.warning(f"FloodWait in get_chat_member({channel_id}, {user_id}): {e.value}s")
        GLOBAL_METRICS.inc("flood_wait_events")
        MEMBERSHIP_CACHE.set(user_id, channel_id, False)
        return False
    except Exception as e:
        logger.debug(f"Error checking chat member for {user_id} in {channel_id}: {e}")
        MEMBERSHIP_CACHE.set(user_id, channel_id, False)
        return False

async def is_requested_one(self, message_or_user):
    user_id = message_or_user if isinstance(message_or_user, int) else (getattr(message_or_user, "from_user", None) and message_or_user.from_user.id)
    if not user_id:
        return False
    if not temp.REQ_CHANNEL1:
        return True
    return await check_channel_membership(self, user_id, temp.REQ_CHANNEL1, slot=1)

async def is_requested_two(self, message_or_user):
    user_id = message_or_user if isinstance(message_or_user, int) else (getattr(message_or_user, "from_user", None) and message_or_user.from_user.id)
    if not user_id:
        return False
    if not temp.REQ_CHANNEL2:
        return True
    return await check_channel_membership(self, user_id, temp.REQ_CHANNEL2, slot=2)

async def is_requested_three(self, message_or_user):
    user_id = message_or_user if isinstance(message_or_user, int) else (getattr(message_or_user, "from_user", None) and message_or_user.from_user.id)
    if not user_id:
        return False
    if not temp.REQ_CHANNEL3:
        return True
    return await check_channel_membership(self, user_id, temp.REQ_CHANNEL3, slot=3)

async def check_loop_sub(client, message):
    if not message.from_user:
        return False
    user_id = message.from_user.id
    for _ in range(8):
        c1, c2 = await asyncio.gather(
            is_requested_one(client, user_id),
            is_requested_two(client, user_id)
        )
        if c1 and c2:
            return True
        await asyncio.sleep(2.0)
    return False

async def check_loop_sub1(client, message):
    if not message.from_user:
        return False
    user_id = message.from_user.id
    for _ in range(8):
        if await is_requested_one(client, user_id):
            return True
        await asyncio.sleep(2.0)
    return False

async def check_loop_sub2(client, message):
    if not message.from_user:
        return False
    user_id = message.from_user.id
    for _ in range(8):
        if await is_requested_two(client, user_id):
            return True
        await asyncio.sleep(2.0)
    return False

async def check_loop_sub3(client, message):
    if not message.from_user:
        return False
    user_id = message.from_user.id
    for _ in range(8):
        if await is_requested_three(client, user_id):
            return True
        await asyncio.sleep(2.0)
    return False

async def build_dynamic_fsub_keyboard(client, user_id: int, file_id: str = None) -> Tuple[InlineKeyboardMarkup, List[int]]:
    """
    Dynamically constructs Force Subscribe InlineKeyboardMarkup.
    Hides buttons for channels the user has already joined.
    - Concurrently checks Channel 1 and Channel 2.
    - If Channel 1 and Channel 2 are BOTH joined, checks Channel 3.
    Returns (InlineKeyboardMarkup, unjoined_channels_list).
    """
    buttons = []
    unjoined_channels = []

    # Parallelize Channel 1 & Channel 2 checks
    tasks = []
    if temp.REQ_CHANNEL1:
        tasks.append(is_requested_one(client, user_id))
    else:
        tasks.append(asyncio.sleep(0, result=True))

    if temp.REQ_CHANNEL2:
        tasks.append(is_requested_two(client, user_id))
    else:
        tasks.append(asyncio.sleep(0, result=True))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    ch1_joined = results[0] if not isinstance(results[0], Exception) else False
    ch2_joined = results[1] if not isinstance(results[1], Exception) else False

    if temp.REQ_CHANNEL1 and not ch1_joined:
        unjoined_channels.append(temp.REQ_CHANNEL1)
        req_link1 = getattr(client, 'req_link1', None) or getattr(temp, 'req_link1', '')
        buttons.append([
            InlineKeyboardButton("💐 Rᴇǫᴜᴇsᴛ Tᴏ Jᴏɪɴ Cʜᴀɴɴᴇʟ 1 💐", url=req_link1)
        ])

    if temp.REQ_CHANNEL2 and not ch2_joined:
        unjoined_channels.append(temp.REQ_CHANNEL2)
        req_link2 = getattr(client, 'req_link2', None) or getattr(temp, 'req_link2', '')
        buttons.append([
            InlineKeyboardButton("⚡ RᴇǫᴜESᴛ Tᴏ Jᴏɪɴ Cʜᴀɴɴᴇʟ 2 ⚡", url=req_link2)
        ])

    # 3. Check Channel 3 only if Channel 1 and Channel 2 are BOTH joined
    if ch1_joined and ch2_joined and temp.REQ_CHANNEL3:
        ch3_joined = await is_requested_three(client, user_id)
        if not ch3_joined:
            unjoined_channels.append(temp.REQ_CHANNEL3)
            req_link3 = getattr(client, 'req_link3', None) or getattr(temp, 'req_link3', '')
            buttons.append([
                InlineKeyboardButton("♦️ RᴇǫᴜESᴛ Tᴏ Jᴏɪɴ Cʜᴀɴɴᴇʟ 3 ♦️", url=req_link3)
            ])

    return InlineKeyboardMarkup(buttons), unjoined_channels

_ACTIVE_FSUB_TASKS = {}

async def check_loop_sub_dynamic(client, message, file_id: str = None, prompt_msg = None):
    """
    Periodically checks user subscription status in background loop,
    updating prompt_msg reply_markup dynamically only when channel status changes.
    Prevents duplicate loops per user and redundant Telegram edit operations.
    """
    if not message.from_user:
        return False
    user_id = message.from_user.id

    # Deduplicate: If a loop is already running for this user, cancel it
    existing_task = _ACTIVE_FSUB_TASKS.get(user_id)
    if existing_task and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except (asyncio.CancelledError, Exception):
            pass

    current_task = asyncio.current_task()
    _ACTIVE_FSUB_TASKS[user_id] = current_task

    last_unjoined_signature = None
    count = 0
    max_count = 10  # 10 iterations max (20s total)

    try:
        while count < max_count:
            reply_markup, unjoined = await build_dynamic_fsub_keyboard(client, user_id, file_id=file_id)
            if not unjoined:
                return True

            unjoined_signature = tuple(unjoined)
            if prompt_msg and unjoined_signature != last_unjoined_signature:
                last_unjoined_signature = unjoined_signature
                try:
                    GLOBAL_METRICS.inc("edit_message")
                    await prompt_msg.edit_reply_markup(reply_markup=reply_markup)
                except MessageNotModified:
                    pass
                except (MessageIdInvalid, QueryIdInvalid):
                    # Prompt message was deleted or expired
                    return False
                except FloodWait as e:
                    logger.warning(f"FloodWait in check_loop_sub_dynamic edit_reply_markup: {e.value}s")
                    GLOBAL_METRICS.inc("flood_wait_events")
                    if e.value <= 5:
                        await asyncio.sleep(e.value + 0.5)
                    else:
                        return False
                except Exception as e:
                    logger.debug(f"Dynamic loop edit_reply_markup error: {e}")

            count += 1
            await asyncio.sleep(2.0)

        return False
    finally:
        if _ACTIVE_FSUB_TASKS.get(user_id) is current_task:
            _ACTIVE_FSUB_TASKS.pop(user_id, None)

async def is_subscribed(bot, query):
    try:
        GLOBAL_METRICS.inc("get_participant")
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
    if message.reply_to_message and message.reply_to_message.from_user:
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
    elif message.from_user:
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


def safe_b64decode(data: str) -> Union[str, None]:
    """
    Safely decodes a urlsafe base64 string.
    Returns decoded UTF-8 string if successful, or None if input is invalid base64.
    """
    if not data or not isinstance(data, str):
        return None
    data = data.strip()
    if len(data) % 4 == 1:
        return None
    try:
        padded_data = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded_data).decode("utf-8", errors="ignore")
    except Exception:
        return None




