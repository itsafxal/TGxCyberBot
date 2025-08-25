import logging
import re
import base64
import asyncio
from struct import pack
import datetime
import pytz
from utils import get_size

from typing import Tuple, List, Optional, Any, Dict

from pyrogram.file_id import FileId
from pyrogram import enums
from pymongo.errors import BulkWriteError, DuplicateKeyError
from motor.motor_asyncio import AsyncIOMotorClient
from umongo import Instance, Document, fields
from marshmallow.exceptions import ValidationError

from info import DATABASE_URI2, DATABASE_NAME, DATABASE_URI, DATABASE_URI3, COLLECTION_NAME, USE_CAPTION_FILTER

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_next_db_is_db2 = True

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

client2 = AsyncIOMotorClient(DATABASE_URI2)
db2 = client2[DATABASE_NAME]
instance2 = Instance.from_db(db2)

client3 = AsyncIOMotorClient(DATABASE_URI3)
db3 = client3[DATABASE_NAME]
instance3 = Instance.from_db(db3)

@instance2.register
class Media2(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    size = fields.StrField(allow_none=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True, default=file_name)
    date = fields.DateTimeField(allow_none=True, default=datetime.datetime.now)
    
    class Meta:
        indexes = ({'key': 'file_name', 'text': True}, )
        collection_name = COLLECTION_NAME

@instance3.register
class Media3(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    size = fields.StrField(allow_none=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True, default=file_name)
    date = fields.DateTimeField(allow_none=True, default=datetime.datetime.now)
    
    class Meta: 
        indexes = ({'key': 'file_name', 'text': True}, )
        collection_name = COLLECTION_NAME

async def check_file(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    
    existing_file1 = await Media2.collection.find_one({"_id": file_id})
    existing_file2 = await Media3.collection.find_one({"_id": file_id})
    
    if existing_file1:
        pass
    elif existing_file2:
        pass
    else:
        okda = "okda"
        return okda

async def bulk_check_files(media_list: List[Any]) -> Dict[str, bool]:
    if not media_list:
        LOGGER.debug("bulk_check_files: media_list is empty, returning empty dict.")
        return {}

    file_ids_to_check_set = set()
    for media in media_list:
        try:
            file_id, _ = unpack_new_file_id(media.file_id)
            file_ids_to_check_set.add(file_id)
        except Exception as e:
            logger.exception(f'Error unpacking file_id {getattr(media, "file_id", "N/A")}: {e}')

    file_ids_to_check = list(file_ids_to_check_set)
    if not file_ids_to_check:
        LOGGER.debug("bulk_check_files: No valid file_ids to check after unpacking, returning empty dict.")
        return {}

    logger.debug(f"bulk_check_files: Checking existence for {len(file_ids_to_check)} unique file IDs.")

    async def get_db2_results():
        logger.debug(f"Querying DB2 for {len(file_ids_to_check)} IDs.")
        return await Media2.collection.find({"_id": {"$in": file_ids_to_check}}).to_list(length=None)

    async def get_db3_results():
        logger.debug(f"Querying DB3 for {len(file_ids_to_check)} IDs.")
        return await Media3.collection.find({"_id": {"$in": file_ids_to_check}}).to_list(length=None)

    db2_task = asyncio.create_task(get_db2_results())
    db3_task = asyncio.create_task(get_db3_results())

    db2_results, db3_results = await asyncio.gather(db2_task, db3_task, return_exceptions=True)

    db2_existing_ids = set()
    if isinstance(db2_results, Exception):
        logger.exception(f'Error fetching from DB2: {db2_results}')
    elif db2_results:
        db2_existing_ids = {str(doc['_id']) for doc in db2_results}

    db3_existing_ids = set()
    if isinstance(db3_results, Exception):
        logger.exception(f'Error fetching from DB3: {db3_results}')
    elif db3_results:
        db3_existing_ids = {str(doc['_id']) for doc in db3_results}

    result = {}
    for file_id in file_ids_to_check:
        exists_in_any_db = (str(file_id) in db2_existing_ids) or (str(file_id) in db3_existing_ids)
        result[str(file_id)] = exists_in_any_db
        logger.debug(f"File ID {file_id}: Exists in DB = {exists_in_any_db}")

    logger.debug(f"bulk_check_files: Completed. Result for {len(result)} file IDs.")
    return result

async def save_file2(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    original_file_name = getattr(media, 'caption', media.file_name)

    pattern = re.compile(r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',re.IGNORECASE)
    match = pattern.search(original_file_name)

    if match:
        season = int(match.group(1))
        if match.group(2):
            episode = int(match.group(2))
            prefix = f"[S{season:02d} EP{episode:02d}]"
        else:
            prefix = f"[S{season:02d}]"

        cleaned_name = pattern.sub('', original_file_name).strip()
        cleaned_name = re.sub(r'[\s._-]+', ' ', cleaned_name).strip()
        cleaned_name = re.sub(r'\s{2,}', ' ', cleaned_name)
        processed_name = f"{prefix} {media.file_name}"
    else:
        processed_name = str(media.file_name)
    file_name = re.sub(r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])", " ", processed_name)
    try:
        file = Media2(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            size=get_size(media.file_size),
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption = getattr(media, 'caption', file_name) or file_name,
            date=datetime.datetime.now(pytz.utc)
        )
    except ValidationError:
        logger.exception('Error occurred while saving file in database (save_file2)')
        return False, 2
    else:
        try:
            await file.commit()
        except DuplicateKeyError:      
            logger.debug(f"File {file_id} is a duplicate in DB2 (via save_file2).")
            return False, 0
        except Exception as e:
            logger.exception(f"Error during file.commit() for {file_id} in DB2 (save_file2): {e}")
            return False, 2
        else:
            logger.debug(f"Successfully saved {file_id} to DB2 (via save_file2).")
            return True, 1

async def save_file3(media):
    file_id, file_ref = unpack_new_file_id(media.file_id)
    original_file_name = getattr(media, 'caption', media.file_name)

    pattern = re.compile(r'(?<!\w)(?:s|season)[\s._-]*?(\d{1,2})[\s._-]*?(?:e|ep|episode)[\s._-]*?(\d{1,2})(?!\d)',re.IGNORECASE)
    match = pattern.search(original_file_name)

    if match:
        season = int(match.group(1))
        if match.group(2):
            episode = int(match.group(2))
            prefix = f"[S{season:02d} EP{episode:02d}]"
        else:
            prefix = f"[S{season:02d}]"

        cleaned_name = pattern.sub('', original_file_name).strip()
        cleaned_name = re.sub(r'[\s._-]+', ' ', cleaned_name).strip()
        cleaned_name = re.sub(r'\s{2,}', ' ', cleaned_name)
        processed_name = f"{prefix} {media.file_name}"
    else:
        processed_name = str(media.file_name)
    file_name = re.sub(r"(_|\+\s|\-|\.|\+|\[MM\]\s|\[MM\]_|\@TvSeriesBay|\@Cinema\sCompany|\@Cinema_Company|\@CC_|\@CC|\@MM_New|\@MM_Linkz|\@MOVIEHUNT|\@CL|\@FBM|\@CKMSERIES|www_DVDWap_Com_|MLM|\@WMR|\[CF\]\s|\[CF\]|\@IndianMoviez|\@tamil_mm|\@infotainmentmedia|\@trolldcompany|\@Rarefilms|\@yamandanmovies|\[YM\]|\@Mallu_Movies|\@YTSLT|\@DailyMovieZhunt|\@I_M_D_B|\@CC_All|\@PM_Old|Dvdworld|\[KMH\]|\@FBM_HW|\@Film_Kottaka|\@CC_X265|\@CelluloidCineClub|\@cinemaheist|\@telugu_moviez|\@CR_Rockers|\@CCineClub|KC_|\[KC\]|\[AML\])", " ", processed_name)
    try:
        file = Media3(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            size=get_size(media.file_size),
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption = getattr(media, 'caption', file_name) or file_name,
            date=datetime.datetime.now(pytz.utc)
        )
    except ValidationError:
        logger.exception('Error occurred while saving file in database (save_file3)')
        return False, 2
    else:
        try:
            await file.commit()
        except DuplicateKeyError:      
            logger.debug(f"File {file_id} is a duplicate in DB3 (via save_file3).")
            return False, 0
        except Exception as e:
            logger.exception(f"Error during file.commit() for {file_id} in DB3 (save_file3): {e}")
            return False, 2
        else:
            logger.debug(f"Successfully saved {file_id} to DB3 (via save_file3).")
            return True, 1

async def bulk_save_files_both_db(media_list: List[Any]) -> Dict[str, Tuple[List[str], List[str], List[str]]]:
    global _next_db_is_db2

    if not media_list:
        return {'db2': ([], [], []), 'db3': ([], [], [])}

    db2_results = ([], [], [])
    db3_results = ([], [], [])

    for i, media_item in enumerate(media_list):
        file_id, _ = unpack_new_file_id(media_item.file_id)

        if _next_db_is_db2:
            logger.debug(f"Attempting to save {file_id} to DB2.")
            success, status_code = await save_file2(media_item)
            current_db_name = "DB2"
            current_results = db2_results
        else:
            logger.debug(f"Attempting to save {file_id} to DB3.")
            success, status_code = await save_file3(media_item)
            current_db_name = "DB3"
            current_results = db3_results
        
        if success and status_code == 1:
            current_results[0].append(file_id)
            logger.debug(f"Successfully saved {file_id} to {current_db_name}.")
        elif not success and status_code == 0:
            current_results[1].append(file_id)
            logger.debug(f"File {file_id} is a duplicate in {current_db_name}.")
        elif not success and status_code == 2:
            current_results[2].append(file_id)
            logger.error(f"Failed to save {file_id} to {current_db_name} due to validation/commit error.")
        else:
            current_results[2].append(file_id)
            logger.error(f"Unexpected status code ({status_code}) for file {file_id} when saving to {current_db_name}.")
        
        _next_db_is_db2 = not _next_db_is_db2

    logger.info(f"Alternating bulk save completed. DB2: Success {len(db2_results[0])}, Duplicates {len(db2_results[1])}, Failed {len(db2_results[2])}. DB3: Success {len(db3_results[0])}, Duplicates {len(db3_results[1])}, Failed {len(db3_results[2])}.")
    
    return {'db2': db2_results, 'db3': db3_results}
        
async def bulk_save_files_db2(media_list: List[Any]) -> Tuple[List[str], List[str], List[str]]:
    if not media_list:
        return [], [], []
    
    successful_ids = []
    duplicate_ids = []
    failed_ids = []
    
    for media_item in media_list:
        file_id, _ = unpack_new_file_id(media_item.file_id)
        
        logger.debug(f"Attempting to save {file_id} to DB2 (via individual save_file2).")
        success, status_code = await save_file2(media_item)
        
        if success and status_code == 1:
            successful_ids.append(file_id)
            logger.debug(f"Successfully saved {file_id} to DB2.")
        elif not success and status_code == 0:
            duplicate_ids.append(file_id)
            logger.debug(f"File {file_id} is a duplicate in DB2.")
        elif not success and status_code == 2:
            failed_ids.append(file_id)
            logger.error(f"Failed to save {file_id} to DB2 due to validation/commit error.")
        else:
            failed_ids.append(file_id)
            logger.error(f"Unexpected status code ({status_code}) for file {file_id} when saving to DB2.")
            
    logger.info(f"bulk_save_files_db2 completed. Succeeded: {len(successful_ids)}, Duplicates: {len(duplicate_ids)}, Failed: {len(failed_ids)}.")
    
    return successful_ids, duplicate_ids, failed_ids

async def bulk_save_files_db3(media_list: List[Any]) -> Tuple[List[str], List[str], List[str]]:
    if not media_list:
        return [], [], []
    
    successful_ids = []
    duplicate_ids = []
    failed_ids = []
    
    for media_item in media_list:
        file_id, _ = unpack_new_file_id(media_item.file_id)
        
        logger.debug(f"Attempting to save {file_id} to DB2 (via individual save_file2).")
        success, status_code = await save_file3(media_item)
        
        if success and status_code == 1:
            successful_ids.append(file_id)
            logger.debug(f"Successfully saved {file_id} to DB3.")
        elif not success and status_code == 0:
            duplicate_ids.append(file_id)
            logger.debug(f"File {file_id} is a duplicate in DB3.")
        elif not success and status_code == 2:
            failed_ids.append(file_id)
            logger.error(f"Failed to save {file_id} to DB3 due to validation/commit error.")
        else:
            failed_ids.append(file_id)
            logger.error(f"Unexpected status code ({status_code}) for file {file_id} when saving to DB3.")
            
    logger.info(f"bulk_save_files_db3 completed. Succeeded: {len(successful_ids)}, Duplicates: {len(duplicate_ids)}, Failed: {len(failed_ids)}.")
    
    return successful_ids, duplicate_ids, failed_ids

async def fetch_mongo_ids_by_keyword(keyword: str, file_type: str = None) -> set:
    """
    Fetches all unique file_ids from multiple MongoDB collections matching a keyword
    and an optional file_type. Returns a set of unique IDs.
    """
    unique_ids = set()
    query = keyword.strip()
    if not query:
        return unique_ids

    # --- Logic from get_bad_files ---
    raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])' if ' ' not in query else query.replace(' ', r'.*[\s\.\+\-_]')
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except re.error:
        logger.error(f"Invalid regex pattern for keyword: {keyword}")
        return unique_ids

    search_filter = {'file_name': regex}
    
    # Add the optional file_type to the search filter
    if file_type:
        search_filter['file_type'] = file_type
    
    # --- Efficient fetching logic ---
    collections_to_search = [Media2, Media3]

    for collection in collections_to_search:
        try:
            # Find documents but only retrieve the '_id' field to save memory
            cursor = collection.find(search_filter, {"file_id": 1})
            # Efficiently iterate through results without loading all into memory
            async for doc in cursor:
                unique_ids.add(doc['file_id'])
        except Exception as e:
            print(f"Error fetching IDs from {collection}: {e}")
            
    return unique_ids
    
async def get_file_details(query):
    filter_query = {'_id': query}
    
    filedetails = await Media2.find_one(filter_query)
    if filedetails:
        return [filedetails]
    
    filedetails_media2 = await Media3.find_one(filter_query)
    if filedetails_media2:
        return [filedetails_media2]
    return []

def encode_file_id(raw_file_id: bytes) -> str:
    encoded = b""
    zero_count = 0
    for byte in raw_file_id + b'\x16\x04':
        if byte == 0:
            zero_count += 1
        else:
            if zero_count:
                encoded += b"\x00" + bytes([zero_count])
                zero_count = 0
            encoded += bytes([byte])
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")

def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")

def unpack_new_file_id(new_file_id: str) -> Tuple[str, str]:
    decoded = FileId.decode(new_file_id)
    old_file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash,
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return old_file_id, file_ref

def get_readable_time(seconds: int) -> str:
    periods = [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    result = ''
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f'{int(period_value)}{period_name}'
    return result if result else '0s'
