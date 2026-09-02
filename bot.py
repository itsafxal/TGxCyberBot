import os
import sys
import logging
import logging.config
import asyncio
import time
import traceback
from pathlib import Path
import importlib
import pkgutil

try:
    import psutil
except ImportError:
    psutil = None

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

from pyrogram import Client, __version__ as pyrogram_version, utils as pyroutils
from pyrogram.handlers.handler import Handler
from pyrogram.raw.all import layer as pyrogram_layer
from database.users_chats_db import db
from info import SESSION, API_ID, API_HASH, BOT_TOKEN, LOG_STR, REQ_CHANNEL1, REQ_CHANNEL2, LOG_CHANNEL, OWNER_ID
from utils import temp, load_datas, delete_messages_loop
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Fix for minimum chat/channel IDs
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

# Configure logging
try:
    logging.config.fileConfig('logging.conf', disable_existing_loggers=False)
except Exception:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure console handler with our formatter
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

# Silence noisy loggers
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)
logging.getLogger("motor").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)

def load_plugins_manually():
    """Manually import all plugin modules and return them"""
    imported_plugins = []
    try:
        # Get the plugins package
        import plugins
        
        # Get all Python files in plugins directory (excluding __init__.py)
        plugins_dir = Path(plugins.__file__).parent
        plugin_files = [f.stem for f in plugins_dir.glob("*.py") if f.stem != "__init__"]
        
        logger.info(f"Found plugin files: {plugin_files}")
        
        for plugin_name in plugin_files:
            try:
                # Import each plugin module
                module = importlib.import_module(f"plugins.{plugin_name}")
                imported_plugins.append(module)
                logger.info(f"✅ Loaded plugin: {plugin_name}")
            except SyntaxError as e:
                logger.error(f"❌ Syntax error in plugin '{plugin_name}': {e}")
            except ImportError as e:
                logger.error(f"❌ Import error in plugin '{plugin_name}': {e}")
            except Exception as e:
                logger.error(f"❌ Failed to load plugin '{plugin_name}': {e}", exc_info=True)
                
        return imported_plugins
        
    except ImportError as e:
        logger.error(f"Could not import plugins package: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error loading plugins: {e}", exc_info=True)
        return []

# Load plugins manually before creating the bot
loaded_plugins = load_plugins_manually()
logger.info(f"Successfully loaded {len(loaded_plugins)} plugins")

class Bot(Client):
    def __init__(self):
        # IMPORTANT: Disable automatic plugin loading to avoid the error
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=100,
            plugins=None,  # Disable automatic plugin loading
            sleep_threshold=5,
        )
        self.schedule = AsyncIOScheduler()
        self.username = None
        self._is_running = False
        
        # Manually register handlers from loaded plugins
        self._register_plugin_handlers()

    def _register_plugin_handlers(self):
        """Manually register handlers from all loaded plugins"""
        total_handlers = 0
        for plugin in loaded_plugins:
            try:
                count = 0
                for obj in getattr(plugin, "__dict__", {}).values():
                    if hasattr(obj, "handlers") and isinstance(obj.handlers, list):
                        for item in obj.handlers:
                            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], Handler):
                                handler, group = item
                                self.add_handler(handler, group)
                                count += 1
                                total_handlers += 1
                if count > 0:
                    logger.info(f"Registered {count} handlers from plugin: {plugin.__name__}")
                else:
                    logger.debug(f"No handlers found in plugin: {plugin.__name__}")
            except Exception as e:
                logger.error(f"Error registering handlers from plugin {plugin.__name__}: {e}")
        logger.info(f"Total handlers registered across all plugins: {total_handlers}")

    async def start(self, **kwargs):
        print("\n[INFO] Bot Initializing...\n")
        self._is_running = True
        
        try:
            # Load banned users and chats
            try:
                banned_users, banned_chats = await db.get_banned()
                temp.BANNED_USERS = banned_users
                temp.BANNED_CHATS = banned_chats
                logger.info(f"Loaded banned users: {len(banned_users)}, banned chats: {len(banned_chats)}")
            except Exception as e:
                logger.error(f"Failed to load banned users/chats: {e}", exc_info=True)
                temp.BANNED_USERS = []
                temp.BANNED_CHATS = []

            # Start the client
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

            # Create invite links for required channels
            for ch_key, attr in [
                ("REQ_CHANNEL1", "req_link1"), 
                ("REQ_CHANNEL2", "req_link2"), 
                ("REQ_CHANNEL3", "req_link3"), 
                ("REQ_CHANNEL1_2", "req_link1_2"), 
                ("REQ_CHANNEL2_2", "req_link2_2"), 
                ("REQ_CHANNEL3_2", "req_link3_2")
            ]:
                ch_id = getattr(temp, ch_key, None)
                if ch_id:
                    try:
                        link = await self.create_chat_invite_link(
                            chat_id=int(ch_id), 
                            creates_join_request=True
                        )
                        setattr(self, attr, link.invite_link)
                        logger.info(f"Invite Link {attr[-1]} set: {getattr(self, attr)}")
                    except Exception as e:
                        logger.warning(f"Failed to create invite link for {ch_key} ({ch_id}): {e}")
                else:
                    logger.debug(f"{ch_key} not configured. Skipping invite link creation.")

            # Start background tasks
            asyncio.create_task(self.safe_loop(delete_messages_loop(self)), name="delete_messages_loop_task")
            asyncio.create_task(self.resource_monitor(), name="resource_monitor")

            # Database initialization and migration check
            try:
                from sql.db import init_aiosqlite_connection, migrate_to_sql, SQLITE_DB
                await init_aiosqlite_connection(SQLITE_DB)
                await migrate_to_sql()
                logger.info("Database initialization and migration completed.")
            except ImportError as ie:
                logger.error(f"SQL database import error: {ie}", exc_info=True)
            except Exception as e:
                logger.error(f"Database initialization error: {e}", exc_info=True)

            # Notify owner
            if OWNER_ID:
                try:
                    await self.send_message(
                        chat_id=int(OWNER_ID), 
                        text="🤖 Bot Restarted Successfully!\n\nAll systems online."
                    )
                except Exception as e:
                    logger.error(f"Could not notify OWNER_ID: {e}")

            # Resume indexing if interrupted
            try:
                from plugins.index import motor_col_general, index_files_to_db
                status = await motor_col_general.find_one({"_id": "index"})
                if status:
                    chat_to_index = status.get("user_id")
                    db_type = status.get("db", "N/A")
                    last_id = status.get("last_id")
                    current = status.get("current")

                    if chat_to_index and last_id and current and OWNER_ID:
                        msg = await self.send_message(
                            chat_id=int(OWNER_ID),
                            text=(
                                "🔄 Bot restarted while indexing was running. Resuming...\n"
                                f"Target Chat: `{chat_to_index}`\n"
                                f"DB Type: `{db_type}`\n"
                                f"Last Fetched ID: `{current}`"
                            )
                        )
                        temp.CURRENT = current
                        await index_files_to_db(
                            self, msg, chat_to_index, int(OWNER_ID), db_type, int(last_id)
                        )
            except ImportError:
                logger.warning("Index module not found, skipping index resume.")
            except Exception as e:
                logger.warning(f"Index resume error: {e}")

            self._is_running = True
            logger.info("✅ Bot startup complete.")
            
        except Exception as e:
            logger.critical(f"Startup failure: {e}", exc_info=True)
            if OWNER_ID:
                try:
                    await self.send_message(
                        chat_id=int(OWNER_ID),
                        text=f"❌ Bot startup failed!\n\nError: `{str(e)}`"
                    )
                except:
                    pass
            sys.exit(1)

    async def stop(self, *args):
        logger.info("Shutting down bot...")
        self._is_running = False
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

    async def safe_loop(self, target):
        """Run a coroutine or callable safely with error handling"""
        while self._is_running:
            try:
                if asyncio.iscoroutine(target):
                    await target
                    break
                elif callable(target):
                    res = target()
                    if asyncio.iscoroutine(res):
                        await res
                else:
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                name = getattr(target, '__name__', getattr(type(target), '__name__', str(target)))
                logger.error(f"Loop error in {name}: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def resource_monitor(self):
        """Monitor system resources"""
        while self._is_running:
            try:
                process = psutil.Process(os.getpid())
                mem = process.memory_info().rss / (1024 ** 2)
                cpu = process.cpu_percent()
                logger.info(f"📊 Memory: {mem:.2f} MB | CPU: {cpu:.2f}%")
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Resource monitor error: {e}")
                await asyncio.sleep(60)

def handle_exception(loop, context):
    """Global exception handler"""
    logger.critical(f"Global error: {context['message']}", exc_info=context.get("exception"))

async def main():
    """Main entry point"""
    try:
        app = Bot()
        logger.info("Starting bot...")
        await app.start()
        
        # Keep the bot running until stopped
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down...")
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    # Set up global exception handler
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(handle_exception)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        loop.close()
