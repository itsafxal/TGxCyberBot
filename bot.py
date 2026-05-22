import os
import sys
import logging
import logging.config
import asyncio
import psutil
import time
import traceback
import uvloop

from pyrogram import Client, __version__ as pyrogram_version, utils as pyroutils
from pyrogram.raw.all import layer as pyrogram_layer
from database.users_chats_db import db
from info import SESSION, API_ID, API_HASH, BOT_TOKEN, LOG_STR, REQ_CHANNEL1, REQ_CHANNEL2, LOG_CHANNEL, OWNER_ID
from utils import temp, load_datas, delete_messages_loop
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from plugins.index import motor_col_general, index_files_to_db

uvloop.install()

pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -100999999999999

# --- Logging Setup ---
class PremiumLogFormatter(logging.Formatter):
    FORMATS = {
        logging.DEBUG:    "[DEBUG]    %(asctime)s - %(name)s - %(message)s",
        logging.INFO:     "[INFO]     %(asctime)s - %(name)s - %(message)s",
        logging.WARNING:  "[WARNING]  %(asctime)s - %(name)s - %(message)s",
        logging.ERROR:    "[ERROR]    %(asctime)s - %(name)s - %(message)s",
        logging.CRITICAL: "[CRITICAL] %(asctime)s - %(name)s - %(message)s"
    }
    def format(self, record):
        fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        return logging.Formatter(fmt, datefmt='%Y-%m-%d %H:%M:%S').format(record)

# Try loading logging.conf if it exists, otherwise fall back to basicConfig
try:
    logging.config.fileConfig('logging.conf', disable_existing_loggers=False)
except Exception:
    logging.basicConfig(level=logging.DEBUG)

# Root logger: ensure StreamHandler to stdout with our formatter
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

_has_stdout_handler = any(
    isinstance(h, logging.StreamHandler) and getattr(h, 'stream', None) is sys.stdout
    for h in logger.handlers
)
if not _has_stdout_handler:
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setFormatter(PremiumLogFormatter())
    logger.addHandler(_console_handler)
else:
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler):
            h.setFormatter(PremiumLogFormatter())

# Silence noisy third-party loggers
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.getLogger("motor").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)


class Bot(Client):
    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=100,
            plugins={"root": "plugins"},
            sleep_threshold=5,
        )
        self.schedule = AsyncIOScheduler()
        self.username = None

    async def start(self, **kwargs):
        print("\n[INFO] Bot Initializing...\n")
        logger.info("Loaded banned users and chats from database.")

        try:
            banned_users, banned_chats = await db.get_banned()
            temp.BANNED_USERS = banned_users
            temp.BANNED_CHATS = banned_chats
        except Exception as e:
            logger.error(f"Failed to load banned users/chats: {e}", exc_info=True)
            sys.exit(1)

        try:
            await super().start()
            me = await self.get_me()
            await load_datas(me.id)
            self.schedule.start()

            temp.ME = me.id
            temp.U_NAME = me.username
            temp.B_NAME = me.first_name
            self.username = f'@{me.username}'

            logger.info(f"Bot connected successfully: {me.first_name} (@{me.username})")
            logger.info(f"Pyrogram Version: v{pyrogram_version} (Layer {pyrogram_layer})")

            for ch_key, attr in [
                ("REQ_CHANNEL1", "req_link1"), ("REQ_CHANNEL2", "req_link2"), ("REQ_CHANNEL3", "req_link3"),
                ("REQ_CHANNEL1_2", "req_link1_2"), ("REQ_CHANNEL2_2", "req_link2_2"), ("REQ_CHANNEL3_2", "req_link3_2")
            ]:
                ch_id = getattr(temp, ch_key, None)
                if ch_id:
                    try:
                        link = await self.create_chat_invite_link(chat_id=int(ch_id), creates_join_request=True)
                        setattr(self, attr, link.invite_link)
                        logger.info(f"Invite Link {attr[-1]} set: {getattr(self, attr)}")
                    except Exception as e:
                        logger.warning(f"Failed to create invite link for {ch_key} ({ch_id}): {e}")
                else:
                    logger.debug(f"{ch_key} not configured. Skipping invite link creation.")

            asyncio.create_task(self.safe_loop(delete_messages_loop(self)), name="delete_messages_loop_task")
            asyncio.create_task(self.resource_monitor(), name="resource_monitor")

            from sql.db import migrate_to_sql
            await migrate_to_sql()
            logger.info("Database migration check completed.")

            if OWNER_ID:
                try:
                    await self.send_message(chat_id=int(OWNER_ID), text="Bot Restarted Successfully!\n\nAll systems online.")
                except Exception as e:
                    logger.error(f"Could not notify OWNER_ID: {e}")

            status = await motor_col_general.find_one({"_id": "index"})
            if status:
                chat_to_index = status.get("user_id")
                db_type = status.get("db", "N/A")
                last_id = status.get("last_id")
                current = status.get("current")

                if chat_to_index and last_id and current:
                    msg = await self.send_message(
                        chat_id=int(OWNER_ID),
                        text=(
                            "Bot restarted while indexing was running. Resuming...\n"
                            f"Target Chat: `{chat_to_index}`\n"
                            f"DB Type: `{db_type}`\n"
                            f"Last Fetched ID: `{current}`"
                        )
                    )
                    temp.CURRENT = current
                    await index_files_to_db(self, msg, chat_to_index, int(OWNER_ID), db_type, int(last_id))

            logger.info("Bot startup complete.")

        except Exception as e:
            logger.critical(f"Startup failure: {e}", exc_info=True)
            sys.exit(1)

    async def stop(self, *args):
        logger.info("Shutting down bot...")
        try:
            if self.schedule.running:
                self.schedule.shutdown()
        except Exception as e:
            logger.warning(f"Error shutting down scheduler: {e}")
        try:
            await super().stop()
        except Exception as e:
            logger.warning(f"Error disconnecting client: {e}")
        logger.info("Bot stopped cleanly.")

    async def safe_loop(self, coro_func):
        while True:
            try:
                await coro_func
            except Exception as e:
                logger.error(f"Loop error in {coro_func.__name__}: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def resource_monitor(self):
        while True:
            try:
                process = psutil.Process(os.getpid())
                mem = process.memory_info().rss / (1024 ** 2)
                cpu = process.cpu_percent()
                logger.info(f"Memory: {mem:.2f} MB | CPU: {cpu:.2f}%")
                await asyncio.sleep(3600)
            except Exception as e:
                logger.warning(f"Resource monitor error: {e}")
                await asyncio.sleep(60)

def handle_exception(loop, context):
    logger.critical(f"Global error: {context['message']}", exc_info=context.get("exception"))

loop = asyncio.get_event_loop()
loop.set_exception_handler(handle_exception)

app = Bot()
try:
    logger.info("Starting bot...")
    app.run()
except Exception as e:
    logger.critical(f"Bot crashed: {e}", exc_info=True)
