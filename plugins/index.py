import os, pytz, re, datetime, logging, asyncio, math, time
from typing import List, Dict, Any

from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from info import ADMINS, LOG_CHANNEL, DATABASE_URI, DATABASE_NAME
from utils import temp

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
LOGGER = logging.getLogger(__name__)
logging.getLogger("pymongo").setLevel(logging.INFO)

from sql.db import save_files_sql_batch
from database.ia_filterdb import get_readable_time, unpack_new_file_id, bulk_save_files_db2, bulk_save_files_db3, bulk_save_files_both_db, bulk_check_files

lock = asyncio.Lock()

motor_client_general = None
motor_db_general = None
motor_col_general = None

import motor.motor_asyncio
try:
    if DATABASE_URI and DATABASE_NAME:
        motor_client_general = motor.motor_asyncio.AsyncIOMotorClient(DATABASE_URI)
        motor_db_general = motor_client_general[DATABASE_NAME]
        motor_col_general = motor_db_general['index_state']
        LOGGER.info("MongoDB Motor client and collection 'index_state' initialized.")
        # Optional: Ping the database to confirm connection at startup
        async def check_mongo_connection():
            try:
                await motor_db_general.command("ping")
                LOGGER.info("Successfully pinged MongoDB at startup.")
            except Exception as e:
                LOGGER.error(f"Failed to ping MongoDB at startup: {e}", exc_info=True)
        # Run this check in a non-blocking way, e.g., on bot startup
        # (This typically happens in your main bot run function, not directly here)
    else:
        LOGGER.error("DATABASE_URI or DATABASE_NAME is not set. MongoDB indexing will be disabled.")
except Exception as e:
    LOGGER.error(f"Error initializing MongoDB Motor client or database: {e}", exc_info=True)
    motor_client_general = None
    motor_db_general = None
    motor_col_general = None

async def check_file_async_bulk(media_list: List[Any]) -> Dict[str, bool]:
    if not media_list:
        return {}

    db_check_results = await bulk_check_files(media_list)
    final_results = {}
    for media in media_list:
        try:
            file_id, _ = unpack_new_file_id(media.file_id)
            exists_in_any_db = db_check_results.get(file_id, False)
            final_results[file_id] = exists_in_any_db
        except Exception as e:
            LOGGER.error(f"Error processing DB check result for media {getattr(media, 'file_id', 'N/A')}: {e}")
            final_results[getattr(media, 'file_id', 'N/A')] = False

    return final_results

class AutoProcessQueue:
    def __init__(self):
        self._queue = asyncio.Queue()
        LOGGER.info("AutoProcessQueue initialized.")

    async def add_messages(self, messages: List[Message]):
        for message in messages:
            await self._queue.put(message)
        LOGGER.debug(f"Added {len(messages)} messages to the process queue. Current size: {self._queue.qsize()}")

    async def get_messages_to_process(self, batch_size=100) -> List[Message]:
        messages_batch = []
        for _ in range(batch_size):
            try:
                message = self._queue.get_nowait()
                messages_batch.append(message)
            except asyncio.QueueEmpty:
                break
        if messages_batch:
            LOGGER.debug(f"Fetched {len(messages_batch)} messages from queue. Remaining: {self._queue.qsize()}")
        return messages_batch

    async def is_empty(self) -> bool:
        is_q_empty = self._queue.empty()
        LOGGER.debug(f"Queue is_empty check: {is_q_empty}")
        return is_q_empty

    async def task_done(self):
        self._queue.task_done()
        LOGGER.debug("Queue task marked done.")

    async def join(self):
        LOGGER.info("Waiting for processing queue to join (all tasks to be marked done)...")
        await self._queue.join()
        LOGGER.info("Processing queue join completed.")

auto_file_queue = AutoProcessQueue()

global_total_files = 0
global_duplicate = 0
global_no_media = 0
global_errors = 0
global_messages_processed_by_saver = 0

async def process_message_batch(messages_batch: List[Message], index_db_type: str):
    global global_total_files, global_duplicate, global_no_media, global_errors, global_messages_processed_by_saver

    batch_start_time = time.time()
    batch_size = len(messages_batch)
    LOGGER.info(f"Processing batch of {batch_size} messages for type '{index_db_type}'.")

    if not messages_batch:
        LOGGER.debug("process_message_batch received an empty batch.")
        return

    media_to_process = []
    messages_for_task_done_count = 0

    for message in messages_batch:
        LOGGER.debug(f"Processing message ID: {message.id} in batch.")
        messages_for_task_done_count += 1

        try:
            if message.empty:
                global_no_media += 1
                LOGGER.info(f"Msg {message.id}: Empty message. Skipped. (No Media: {global_no_media})")
                continue

            found_suitable_media = False

            for file_type_attribute in ("document", "video", "audio"):
                media = getattr(message, file_type_attribute, None)

                if media:
                    LOGGER.debug(f"Msg {message.id}: Found potential {file_type_attribute}. Checking attributes...")

                    if not hasattr(media, 'file_id') or not hasattr(media, 'file_size'):
                        LOGGER.warning(f"Msg {message.id}: {file_type_attribute} object missing file_id or file_size. Skipping this type for message.")
                        continue

                    current_mime_type = getattr(media, 'mime_type', 'N/A')
                    LOGGER.debug(f"Msg {message.id}: {file_type_attribute} MIME type: {current_mime_type}. Validating MIME...")

                    is_valid_mime = False
                    if file_type_attribute == "video":
                        is_valid_mime = True
                    elif file_type_attribute == "document":
                        is_valid_mime = True


                    if not is_valid_mime:
                        global_no_media += 1
                        LOGGER.info(f"Msg {message.id}: {file_type_attribute} with MIME type '{current_mime_type}' not matching required patterns. Skipped. (No Media: {global_no_media})")
                        continue

                    media.file_type = file_type_attribute.upper()

                    file_name = getattr(media, 'file_name', None)

                    media.caption = message.caption if message.caption else file_name

                    media_to_process.append(media)
                    found_suitable_media = True
                    LOGGER.debug(f"Msg {message.id}: Successfully identified and added {file_type_attribute} to media_to_process.")
                    break

            if not found_suitable_media:
                global_no_media += 1
                LOGGER.debug(f"Msg {message.id}: No suitable media (document, video, or audio matching filters) found in message. Skipped. (No Media: {global_no_media})")

        except Exception as e:
            LOGGER.error(f"Error preparing message {message.id} for processing: {e}", exc_info=True)
            global_errors += 1

    LOGGER.debug(f"Finished initial media identification for batch. Messages to mark done: {messages_for_task_done_count}")
    for _ in range(messages_for_task_done_count):
        await auto_file_queue.task_done()
    global_messages_processed_by_saver += messages_for_task_done_count
    LOGGER.info(f"Marked {messages_for_task_done_count} messages as task_done. Total processed by saver: {global_messages_processed_by_saver}")

    if not media_to_process:
        LOGGER.info(f"No valid media to save for this batch after filtering. ({batch_size} messages originally)")
        return

    LOGGER.info(f"Proceeding to check existence for {len(media_to_process)} media items before saving.")
    file_existence_status = await check_file_async_bulk(media_to_process)
    LOGGER.info(f"Existence check completed for {len(media_to_process)} media items.")

    new_media_list = []
    for media_item in media_to_process:
        try:
            file_id, _ = unpack_new_file_id(media_item.file_id)
            exists = file_existence_status.get(file_id)

            if exists is False:
                new_media_list.append(media_item)
                LOGGER.debug(f"File {file_id} is new, added to new_media_list.")
            elif exists is True:
                global_duplicate += 1
                LOGGER.debug(f"File {file_id} identified as duplicate and skipped saving.")
            else:
                global_errors += 1
                LOGGER.warning(f"File {file_id} had unknown status or error during check: {exists}. Counting as error and skipping save.")

        except Exception as e:
            LOGGER.error(f"Error processing check result for media {getattr(media_item, 'file_id', 'N/A')}: {e}")
            global_errors += 1

    if not new_media_list:
        LOGGER.debug(f"No new media found to save for this batch after duplicate checking. ({len(media_to_process)} originally processed media)")
        return

    LOGGER.debug(f"Attempting to save {len(new_media_list)} new files to DBs (type: {index_db_type}).")
    try:
        successful, duplicates, failed = [], [], []
        if index_db_type == 'accept1':
            successful, duplicates, failed = await bulk_save_files_db2(new_media_list)
            sus, dup, fail = await save_files_sql_batch(new_media_list)
            LOGGER.debug(f"DB2 bulk save results: {len(successful)} saved, {len(duplicates)} duplicates, {len(failed)} failed.")
        elif index_db_type == 'accept2':
            successful, duplicates, failed = await bulk_save_files_db3(new_media_list)
            sus, dup, fail = await save_files_sql_batch(new_media_list)
            LOGGER.debug(f"DB3 bulk save results: {len(successful)} saved, {len(duplicates)} duplicates, {len(failed)} failed.")
        elif index_db_type == 'accept5':
            results_from_alternating_db = await bulk_save_files_both_db(new_media_list)
            sus, dup, fail = await save_files_sql_batch(new_media_list)
            
            successful_db2, duplicates_db2, failed_db2 = results_from_alternating_db.get('db2', ([], [], []))
            successful_db3, duplicates_db3, failed_db3 = results_from_alternating_db.get('db3', ([], [], []))

            successful = successful_db2 + successful_db3
            duplicates = duplicates_db2 + duplicates_db3
            failed = failed_db2 + failed_db3

            if successful or duplicates or failed:
                LOGGER.info(f"Alternating save: Total {len(successful)} saved, {len(duplicates)} duplicates, {len(failed)} failed.")
            else:
                LOGGER.warning(f"Alternating save: No successful operations reported for batch of {len(new_media_list)} files.")
                failed.extend([unpack_new_file_id(media_item.file_id)[0] for media_item in new_media_list])
        else:
            LOGGER.error(f"Unknown index_db_type: {index_db_type}. Skipping save for batch.")
            successful, duplicates, failed = [], [], [unpack_new_file_id(media_item.file_id)[0] for media_item in new_media_list]

        global_total_files += len(successful)
        global_duplicate += len(duplicates)
        global_errors += len(failed)
        LOGGER.info(f"Updated global counters: Saved={global_total_files}, Duplicates={global_duplicate}, Errors={global_errors}")

    except Exception as e:
        LOGGER.exception(f"CRITICAL: Unhandled error during bulk save operation for batch! {e}")
        global_errors += len(new_media_list)

    batch_end_time = time.time()
    LOGGER.info(f"Finished processing batch of {batch_size} messages in {batch_end_time - batch_start_time:.2f} seconds.")

async def save_files_loop(index_db_type: str):
    max_concurrent_batch_processes = 5
    batch_size_from_queue = 100

    current_processing_tasks = []

    LOGGER.info(f"Save files loop started with db_type: {index_db_type}")

    try:
        while True:
            if temp.CANCEL:
                LOGGER.info("Save loop received cancel signal (temp.CANCEL is True). Exiting save_files_loop.")
                break

            current_processing_tasks = [task for task in current_processing_tasks if task is not None and not task.done()]
            LOGGER.debug(f"Active batch processing tasks: {len(current_processing_tasks)}. Queue size: {auto_file_queue._queue.qsize()}")

            if len(current_processing_tasks) >= max_concurrent_batch_processes:
                LOGGER.debug(f"Max concurrent batch processes ({max_concurrent_batch_processes}) reached. Waiting for a batch to complete...")
                done, pending = await asyncio.wait(current_processing_tasks, return_when=asyncio.FIRST_COMPLETED)
                current_processing_tasks = list(pending)
                for d_task in done:
                    try:
                        d_task.result()
                    except asyncio.CancelledError:
                        LOGGER.debug("A batch processing task was cancelled.")
                    except Exception as e:
                        LOGGER.error(f"Error in completed batch processing task: {e}", exc_info=True)
                LOGGER.debug(f"Waited for {len(done)} batch tasks to finish. {len(current_processing_tasks)} still pending.")
                continue

            messages_batch = await auto_file_queue.get_messages_to_process(
                batch_size=batch_size_from_queue
            )

            if messages_batch:
                LOGGER.info(f"Fetched {len(messages_batch)} messages from queue. Starting new processing task.")
                new_task = asyncio.create_task(process_message_batch(messages_batch, index_db_type))
                current_processing_tasks.append(new_task)
                LOGGER.debug(f"New batch processing task started. Total active batch processes: {len(current_processing_tasks)}")
            else:
                if not current_processing_tasks and await auto_file_queue.is_empty():
                    LOGGER.debug("Save queue and all active processing tasks are empty. Sleeping for 5s.")
                    await asyncio.sleep(5)
                else:
                    LOGGER.debug("Save queue empty, but tasks still running or waiting for fetcher. Sleeping briefly (0.1s).")
                    await asyncio.sleep(0.1)

            await asyncio.sleep(0.01)

    except asyncio.CancelledError:
        LOGGER.info("Save files loop was explicitly cancelled.")
    except Exception as e:
        LOGGER.exception(f"An unhandled error occurred in save_files_loop: {e}")
    finally:
        if current_processing_tasks:
            LOGGER.info(f"Save loop exiting. Awaiting {len(current_processing_tasks)} remaining batch tasks to finish.")
            await asyncio.gather(*current_processing_tasks, return_exceptions=True)
            LOGGER.info("All remaining batch tasks completed after save loop exit.")

@Client.on_callback_query(filters.regex(r'^index'))
async def index_files_callback(bot: Client, query: Message):
    if query.data.startswith('index_cancel'):
        LOGGER.info(f"Index cancellation request received from user {query.from_user.id}.")
        temp.CANCEL = True

        if hasattr(bot, "save_loop_task") and not bot.save_loop_task.done():
            LOGGER.info("Attempting to cancel save_loop_task.")
            bot.save_loop_task.cancel()
            try:
                await bot.save_loop_task
            except asyncio.CancelledError:
                LOGGER.info("save_loop_task acknowledged cancellation.")
            except Exception as e:
                LOGGER.error(f"Error while awaiting cancelled save_loop_task: {e}", exc_info=True)
            finally:
                delattr(bot, "save_loop_task")
        else:
            LOGGER.info("Cancel signal received, but save_loop_task not found or already done.")

        # Enhanced cancellation message
        await query.answer("✅ Indexing cancellation initiated. Please wait for current operations to gracefully stop.", show_alert=True)
        return

    _, action, chat, lst_msg_id, from_user = query.data.split("#")

    if action == 'reject':
        await query.message.delete()
        await bot.send_message(int(from_user),
                               f'❌ Your submission for indexing **{chat}** has been **declined** by our moderators.',
                               reply_to_message_id=int(lst_msg_id),
                               parse_mode=enums.ParseMode.MARKDOWN)
        return

    selected_db_type = action

    if action in ['accept1', 'accept2', 'accept5']:
        if lock.locked():
            LOGGER.warning(f"Indexing already in progress. Rejecting new request from {query.from_user.id}.")
            return await query.answer('⚠️ An indexing process is already active. Please wait for it to complete before starting a new one.', show_alert=True)

        msg = query.message
        await query.answer('🚀 Initiating indexing process...', show_alert=True)

        if int(from_user) not in ADMINS:
            await bot.send_message(int(from_user),
                                   f'✅ Your request to index **{chat}** has been **accepted** by our moderators and will commence shortly!',
                                   reply_to_message_id=int(lst_msg_id),
                                   parse_mode=enums.ParseMode.MARKDOWN)

        # Improved initial message for indexing start
        await msg.edit(
            "✨ **Indexing Operation Commencing!** ✨\n\n"
            "Please monitor this message for real-time progress updates.\n\n"
            "To halt the process at any time, simply tap the 'Cancel' button.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('🛑 Cancel Indexing', callback_data='index_cancel')]]
            ),
            parse_mode=enums.ParseMode.MARKDOWN
        )

        try:
            chat_id_to_index = int(chat)
        except ValueError:
            chat_id_to_index = chat
            LOGGER.warning(f"Chat ID '{chat}' is not an integer. Proceeding as username/public link.")

        if not hasattr(bot, "save_loop_task") or bot.save_loop_task.done():
            LOGGER.info("Starting new save_files_loop background task.")
            bot.save_loop_task = asyncio.create_task(save_files_loop(selected_db_type))
            LOGGER.info(f"Save_files_loop background task started: {bot.save_loop_task.get_name()}.")
        else:
            LOGGER.warning("save_files_loop task already running. Not starting a new one. This is expected if an indexing process is already active.")

        await index_files_to_db(bot, msg, chat_id_to_index, int(from_user), selected_db_type, int(lst_msg_id))

    else:
        LOGGER.error(f"Invalid action for index callback: {action}")
        await query.answer("🚫 Unknown action. Please try again or contact support.", show_alert=True)

@Client.on_message(filters.user(ADMINS) & (filters.forwarded | (filters.regex("(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")) & filters.text ) & filters.private & filters.incoming)
async def send_for_index(bot: Client, message: Message):
    chat_id = None
    last_msg_id = None

    if message.text:
        regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(message.text)
        if not match:
            return await message.reply('❌ Invalid link format! Please provide a valid Telegram link, e.g., `https://t.me/channel_username/123` or `https://t.me/c/123456789/123`.', parse_mode=enums.ParseMode.MARKDOWN)

        chat_id_str = match.group(4)
        last_msg_id = int(match.group(5))

        if chat_id_str.isnumeric():
            chat_id = int(f"-100{chat_id_str}")
        else:
            chat_id = chat_id_str
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return await message.reply("💡 To initiate indexing, please forward the **last message** from the desired channel/group, or provide a **valid Telegram message link**.")

    try:
        chat_info = await bot.get_chat(chat_id)
        k = await bot.get_messages(chat_id, last_msg_id)

    except ChannelInvalid:
        return await message.reply('Access Denied 🔒: This appears to be a private channel/group. Please **make me an administrator** in that chat to enable indexing.', parse_mode=enums.ParseMode.MARKDOWN)
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('❌ Invalid Link/Username: The specified channel username or link is incorrect or not found. Double-check and try again.', parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        LOGGER.exception(f"Error checking chat access for {chat_id} or message {last_msg_id}: {e}")
        return await message.reply(f'⚠️ An unexpected error occurred while verifying chat access or message availability: `{e}`', parse_mode=enums.ParseMode.MARKDOWN)

    if k.empty:
        return await message.reply('🔍 Message Not Found: The specified message ID is invalid, or I do not have sufficient permissions (e.g., read messages) in the channel/group.', parse_mode=enums.ParseMode.MARKDOWN)

    if message.from_user.id in ADMINS:
        buttons = [
            [
                InlineKeyboardButton('💾 Index to DB1', callback_data=f'index#accept1#{chat_id}#{last_msg_id}#{message.from_user.id}'),
                InlineKeyboardButton('🗃️ Index to DB2', callback_data=f'index#accept2#{chat_id}#{last_msg_id}#{message.from_user.id}')
            ],
            [InlineKeyboardButton('🔄 Index to Alternating DBs', callback_data=f'index#accept5#{chat_id}#{last_msg_id}#{message.from_user.id}')],
            [InlineKeyboardButton('✖️ Close Options', callback_data='close_data')],
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        return await message.reply(
            f'✨ **Indexing Request Confirmation** ✨\n\n'
            f'You are about to initiate indexing for:\n'
            f'• **Chat ID/Username:** `{chat_id}`\n'
            f'• **Last Message ID:** `{last_msg_id}`\n\n'
            f'Please select your preferred database for indexing:',
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.MARKDOWN
        )
    else:
        invite_link = "Not available (private chat or no admin rights)"
        if isinstance(chat_id, int):
            try:
                invite_link_obj = await bot.create_chat_invite_link(chat_id)
                invite_link = f"🔗 `{invite_link_obj.invite_link}`"
            except ChatAdminRequired:
                invite_link = '⚠️ *Bot is not admin with invite link creation rights.*'
            except Exception as e:
                LOGGER.error(f"Error creating invite link for chat {chat_id}: {e}")
                invite_link = f"⚠️ *Could not generate invite link: {e}*"
        else:
            invite_link = f"🔗 @{chat_id}"

        buttons = [
            [
                InlineKeyboardButton('✅ Accept (DB1)', callback_data=f'index#accept1#{chat_id}#{last_msg_id}#{message.from_user.id}'),
                InlineKeyboardButton('✅ Accept (DB2)', callback_data=f'index#accept2#{chat_id}#{last_msg_id}#{message.from_user.id}')
            ],
            [
                InlineKeyboardButton('🔄 Accept (Alternating DBs)', callback_data=f'index#accept5#{chat_id}#{last_msg_id}#{message.from_user.id}')
            ],
            [InlineKeyboardButton('❌ Decline Request', callback_data=f'index#reject#{chat_id}#{message.id}#{message.from_user.id}')],
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        # Admin notification message
        await bot.send_message(LOG_CHANNEL,
                               f'🚨 **New Indexing Request** 🚨\n\n'
                               f'**Initiated By:** {message.from_user.mention} (ID: `{message.from_user.id}`)\n'
                               f'**Target Chat:** `{chat_id}`\n'
                               f'**Last Message ID:** `{last_msg_id}`\n'
                               f'**Invite Link:** {invite_link}\n\n'
                               f'Please review and decide:',
                               reply_markup=reply_markup,
                               parse_mode=enums.ParseMode.MARKDOWN)
        
        # User confirmation message
        await message.reply('🌟 **Request Submitted!** 🌟\n\n'
                            'Thank you for contributing! Your indexing request has been sent to our moderators for review.\n'
                            'You will receive a notification once your request is **accepted** or **declined**.\n\n'
                            'Appreciate your patience! 🙏', parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_message(filters.command('setskip') & filters.user(ADMINS))
async def set_skip_number(bot: Client, message: Message):
    if ' ' in message.text:
        _, skip_value = message.text.split(" ", 1)
        try:
            skip = int(skip_value)
            if skip < 0:
                raise ValueError("Skip number cannot be negative.")
        except ValueError:
            return await message.reply("❌ Invalid input! The skip number must be a **positive integer**.\n\nUsage: `/setskip <message_id>`", parse_mode=enums.ParseMode.MARKDOWN)

        temp.CURRENT = int(skip)
        await message.reply(f"✅ Success! The **SKIP number** has been set to `{skip}`.\n\n"
                            f"The next indexing operation will commence from this message ID.", parse_mode=enums.ParseMode.MARKDOWN)
    else:
        await message.reply("🤔 Missing argument! Please provide a skip number.\n\nUsage: `/setskip <message_id>`", parse_mode=enums.ParseMode.MARKDOWN)

async def fetch_messages_chunk(client: Client, chat_id: int | str, message_ids_chunk: List[int], semaphore: asyncio.Semaphore) -> List[Message]:
    async with semaphore:
        try:
            LOGGER.debug(f"Fetching chunk: Chat {chat_id}, IDs {message_ids_chunk[0]}-{message_ids_chunk[-1]} ({len(message_ids_chunk)} messages)")
            fetched_messages = await client.get_messages(chat_id, message_ids_chunk)
            valid_messages = [m for m in fetched_messages if m is not None]
            LOGGER.debug(f"Fetched {len(valid_messages)} valid messages for chunk {message_ids_chunk[0]}-{message_ids_chunk[-1]}")
            return valid_messages
        except FloodWait as e:
            LOGGER.warning(f"FloodWait while fetching chunk {message_ids_chunk[0]}-{message_ids_chunk[-1]}: Sleeping for {e.value}s.")
            await asyncio.sleep(e.value + 1)
            try:
                LOGGER.info(f"Retrying fetch for chunk {message_ids_chunk[0]}-{message_ids_chunk[-1]} after FloodWait.")
                fetched_messages = await client.get_messages(chat_id, message_ids_chunk)
                return [m for m in fetched_messages if m is not None]
            except Exception as retry_e:
                LOGGER.error(f"Error on retry fetching chunk {message_ids_chunk[0]}-{message_ids_chunk[-1]}: {retry_e}", exc_info=True)
                return []
        except Exception as e:
            LOGGER.error(f"Error fetching messages for chunk {message_ids_chunk[0]}-{message_ids_chunk[-1]}: {e}", exc_info=True)
            return []

async def index_files_to_db(client: Client, progress_message: Message, chat_id: int | str, from_user_id: int, db_type: str, last_message_id: int):
    global global_total_files, global_duplicate, global_no_media, global_errors, global_messages_processed_by_saver

    if not hasattr(client, "save_loop_task") or client.save_loop_task.done():
        LOGGER.info("Starting new save_files_loop background task.")
        client.save_loop_task = asyncio.create_task(save_files_loop(db_type))
        LOGGER.info(f"Save_files_loop background task started: {client.save_loop_task.get_name()}.")
    else:
        LOGGER.warning("save_files_loop task already running. Not starting a new one. This is expected if an indexing process is already active.")
            
    LOGGER.info(f"Starting index_files_to_db for chat {chat_id} with db_type: {db_type}")

    start_time = time.time()
    temp.CANCEL = False

    global_total_files = 0
    global_duplicate = 0
    global_no_media = 0
    global_errors = 0
    global_messages_processed_by_saver = 0

    try:
        current_start_message_id = temp.CURRENT
        # Ensure we start from at least 1, and don't go below 1 if last_message_id is very small
        start_message_id_for_range = min(last_message_id, current_start_message_id) if current_start_message_id else 1
        
        total_messages_scanned_in_channel = 0
        messages_fetched_this_run = 0

        # Adjust the range to go from last_message_id down to start_message_id_for_range
        # The range function's end parameter is exclusive, so we need -1
        message_ids_to_fetch_range = range(start_message_id_for_range, last_message_id+1)
        total_messages_in_range_count = len(message_ids_to_fetch_range)

        fetching_semaphore = asyncio.Semaphore(10)

        LOGGER.info(f"Iterating messages for {chat_id} from {last_message_id} down to {start_message_id_for_range}. Total approx: {total_messages_in_range_count}")

        # Initial progress message update outside the loop to ensure it appears quickly
        await progress_message.edit(
            f"✨ **Indexing Initialized!** ✨\n\n"
            f"**Channel:** `{chat_id}`\n"
            f"**Messages to Scan:** `{total_messages_in_range_count}` (from ID `{start_message_id_for_range}` to `{last_message_id}`)\n"
            f"**Current Status:** Fetching messages... 📥\n"
            f"**Time Elapsed:** `{get_readable_time(time.time() - start_time)}`\n"
            f"**Progress:** `0%` (0/0)\n"
            f"**Queue:** `Empty`",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('🛑 Cancel Indexing', callback_data='index_cancel')]]
            ),
            parse_mode=enums.ParseMode.MARKDOWN
        )

        for i in range(0, total_messages_in_range_count, 100):
            if temp.CANCEL:
                LOGGER.info(f"Indexing cancelled for {chat_id} by user request during message fetching loop.")
                break

            chunk_of_ids = message_ids_to_fetch_range[i : i + 100]
            if not chunk_of_ids:
                break

            try:
                fetched_messages_in_chunk = await fetch_messages_chunk(client, chat_id, chunk_of_ids, fetching_semaphore)

                if fetched_messages_in_chunk:
                    await auto_file_queue.add_messages(fetched_messages_in_chunk)
                    messages_fetched_this_run += len(fetched_messages_in_chunk)
                    # Update total_messages_scanned_in_channel with the minimum ID processed so far (since we iterate backwards)
                    # This gives a better sense of 'how far back' we've scanned.
                    if fetched_messages_in_chunk:
                        min_id_in_chunk = min(m.id for m in fetched_messages_in_chunk)
                        total_messages_scanned_in_channel = min(total_messages_scanned_in_channel if total_messages_scanned_in_channel > 0 else last_message_id, min_id_in_chunk)
                    
                # Update progress every 500 messages fetched or if it's near the end of the range
                if messages_fetched_this_run % 500 == 0 or (last_message_id - total_messages_scanned_in_channel < 100 and messages_fetched_this_run > 0):
                    total_messages_to_process = last_message_id - start_message_id_for_range + 1
                    # Ensure messages_fetched_this_run doesn't exceed total_messages_to_process for percentage calculation
                    display_progress = min(messages_fetched_this_run, total_messages_to_process)
                    
                    processed_progress_percentage = (display_progress / total_messages_to_process) * 100 if total_messages_to_process > 0 else 0

                    elapsed_time = time.time() - start_time
                    await progress_message.edit(
                        f"📊 **Indexing Progress Update** 📊\n\n"
                        f"**Channel:** `{chat_id}`\n"
                        f"**Target Range:** `{start_message_id_for_range}` to `{last_message_id}`\n\n"
                        f"**Messages Fetched:** `{messages_fetched_this_run}` / `{total_messages_in_range_count}`\n"
                        f"**Processing Queue:** `{auto_file_queue._queue.qsize()}` messages awaiting processing\n\n"
                        f"--- **Current Stats** ---\n"
                        f"**✅ Saved:** `{global_total_files}` files\n"
                        f"**⚠️ Duplicates:** `{global_duplicate}` skipped\n"
                        f"**🚫 No Media:** `{global_no_media}` skipped\n"
                        f"**❌ Errors:** `{global_errors}` encountered\n\n"
                        f"**Time Elapsed:** `{get_readable_time(elapsed_time)}`",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton('🛑 Cancel Indexing', callback_data='index_cancel')]]
                        ),
                        parse_mode=enums.ParseMode.MARKDOWN
                    )
                    if motor_col_general is not None:
                        try:
                            queue = auto_file_queue._queue.qsize()
                            await motor_col_general.update_one(
                                {"_id": "index"},
                                {"$set": {
                                    "status": "running", 
                                    "db": db_type, 
                                    "current": start_message_id_for_range + messages_fetched_this_run - queue + 1, 
                                    "last_id": last_message_id, 
                                    "user_id": chat_id
                                }},
                                upsert=True
                            )
                        except Exception as e:
                            print(f"Error during update index id to db. {e}")
                
            except Exception as e:
                LOGGER.error(f"Error during fetching chunk {chunk_of_ids[0]}-{chunk_of_ids[-1]} from {chat_id}: {e}", exc_info=True)
                global_errors += len(chunk_of_ids)
            
        LOGGER.info(f"Finished fetching all intended messages for {chat_id}. Waiting for remaining queue items to process.")
        
        await progress_message.edit(
            f"📊 **Indexing Phase 1 Complete: Fetching Done!** 📊\n\n"
            f"**Channel:** `{chat_id}`\n"
            f"**Messages Fetched:** `{messages_fetched_this_run}`\n"
            f"**Processing Queue:** `{auto_file_queue._queue.qsize()}` messages remaining to process...\n\n"
            f"--- **Current Stats** ---\n"
            f"**✅ Saved:** `{global_total_files}` files\n"
            f"**⚠️ Duplicates:** `{global_duplicate}` skipped\n"
            f"**🚫 No Media:** `{global_no_media}` skipped\n"
            f"**❌ Errors:** `{global_errors}` encountered\n\n"
            f"**Time Elapsed:** `{get_readable_time(time.time() - start_time)}`\n\n"
            f"Please wait, finalizing database operations... ⏳",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('🛑 Cancel Indexing', callback_data='index_cancel')]]
            ),
            parse_mode=enums.ParseMode.MARKDOWN
        )


        #await auto_file_queue.join() # Wait for all messages in queue to be processed

        end_time = time.time()
        total_time = end_time - start_time

        final_indexed_id_for_db = start_message_id_for_range if messages_fetched_this_run > 0 else last_message_id # If messages were fetched, it means we scanned down to start_message_id_for_range
        
        if temp.CANCEL:
            final_status_message_text = (
                f"🛑 **Indexing Operation Cancelled for** `{chat_id}` 🛑\n\n"
                f"The process was interrupted by user request.\n\n"
                f"**Total Messages Processed:** `{global_messages_processed_by_saver}`\n"
                f"**Successfully Saved Files:** `{global_total_files}`\n"
                f"**Skipped (Duplicates):** `{global_duplicate}`\n"
                f"**Skipped (No Media/Invalid):** `{global_no_media}`\n"
                f"**Errors during processing:** `{global_errors}`\n"
                f"**Elapsed Time:** `{get_readable_time(total_time)}`\n\n"
                f"The indexing can be resumed later from the last indexed point."
            )            
        else:
            final_status_message_text = (
                f"✅ **Indexing Completed Successfully for** `{chat_id}` ✅\n\n"
                f"**Total Messages Processed:** `{global_messages_processed_by_saver}`\n"
                f"**Successfully Saved Files:** `{global_total_files}`\n"
                f"**Skipped (Duplicates):** `{global_duplicate}`\n"
                f"**Skipped (No Media/Invalid):** `{global_no_media}`\n"
                f"**Errors during processing:** `{global_errors}`\n"
                f"**Total Time Taken:** `{get_readable_time(total_time)}`\n\n"
                f"All available content within the specified range has been indexed."
            )

        await progress_message.edit(final_status_message_text, parse_mode=enums.ParseMode.MARKDOWN)
        await motor_col_general.delete_one({"_id": "index"})
        if int(from_user_id) != progress_message.chat.id: # Send completion message to the user who initiated if different from the progress message chat
            await client.send_message(int(from_user_id), final_status_message_text, parse_mode=enums.ParseMode.MARKDOWN)

    except FloodWait as e:
        LOGGER.error(f"Major FloodWait during indexing {chat_id}: {e.value} seconds. This is often unrecoverable in a single run.", exc_info=True)
        await progress_message.edit(f"🚨 **Indexing Halted: FloodWait Detected!** 🚨\n\n"
                                    f"The indexing process has been paused due to a Telegram API flood limit (waiting `{e.value}` seconds).\n"
                                    f"Please try resuming the indexing after some time. This often resolves automatically.", parse_mode=enums.ParseMode.MARKDOWN)
        await asyncio.sleep(e.value + 10) # Wait a bit longer than the FloodWait suggests
    except (ChannelInvalid, UsernameInvalid, UsernameNotModified) as e:
        LOGGER.error(f"Error accessing chat {chat_id}: {e}. Check if bot is admin or channel/username is valid.", exc_info=True)
        await progress_message.edit(f"❌ **Indexing Failed: Chat Access Error** ❌\n\n"
                                    f"Unable to access chat `{chat_id}`. Please ensure:\n"
                                    f"• The bot is an **administrator** in the channel/group.\n"
                                    f"• The provided Chat ID or Username is **correct**.\n"
                                    f"Error Details: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)
    except ChatAdminRequired:
        LOGGER.error(f"Bot is not admin in chat {chat_id}. Cannot index.", exc_info=True)
        await progress_message.edit(f"🔒 **Indexing Failed: Admin Permissions Required** 🔒\n\n"
                                    f"The bot is **not an administrator** in `{chat_id}`.\n"
                                    f"Please grant the necessary admin permissions (at least 'Read Channel History' and 'Post Messages') to proceed with indexing.", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception as e:
        LOGGER.exception(f"An unexpected error occurred during indexing for chat {chat_id}: {e}")
        await progress_message.edit(f"⚠️ **Indexing Encountered an Unexpected Error!** ⚠️\n\n"
                                    f"An unhandled error occurred during the indexing process for `{chat_id}`.\n"
                                    f"Please inform the bot owner with the details below:\n"
                                    f"Error: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)
    finally:
        temp.CANCEL = False
