import re
from os import environ
from dotenv import load_dotenv
from Script import script

load_dotenv()

id_pattern = re.compile(r'^.\d+$')

def is_enabled(value, default):
    if not value:
        return default
    val = str(value).strip().lower()
    if val in ["true", "yes", "1", "enable", "y", "on"]:
        return True
    elif val in ["false", "no", "0", "disable", "n", "off", "none", "null"]:
        return False
    else:
        return default

# Bot information
SESSION = environ.get('SESSION', 'Media_searcher')
API_ID = int(api_id) if (api_id := environ.get('API_ID')) and api_id.isdigit() else 0
API_HASH = environ.get('API_HASH', '')
BOT_TOKEN = environ.get('BOT_TOKEN', '')

# Bot settings
AUTO_DEL = int(environ.get('AUTO_DEL', 900))
MAX_FILES = int(environ.get('MAX_FILES', 8))
CACHE_TIME = int(environ.get('CACHE_TIME', 300))
USE_CAPTION_FILTER = True

# Pics
PICS = environ.get('PICS', '').split()

# Admins & Users
OWNER_ID = environ.get('OWNER_ID')
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '').split()]
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '').split()]
AUTH_USERS = (auth_users + ADMINS) if auth_users else []

# MongoDB information
DATABASE_NAME = environ.get('DATABASE_NAME', "CyberTG")
COLLECTION_NAME = environ.get('COLLECTION_NAME', "Telegram-Document")
DATABASE_URI = environ.get('DATABASE_URI')
DATABASE_URI2 = environ.get('DATABASE_URI2')
DATABASE_URI3 = environ.get('DATABASE_URI3')

# FSUB
AUTH_CHANNEL = int(environ.get('AUTH_CHANNEL')) if (auth_channel := environ.get('AUTH_CHANNEL')) and id_pattern.search(auth_channel) else None
REQ_CHANNEL1 = environ.get("REQ_CHANNEL1", None)
REQ_CHANNEL1 = (int(REQ_CHANNEL1) if REQ_CHANNEL1 and id_pattern.search(REQ_CHANNEL1) else False) if REQ_CHANNEL1 is not None else None
REQ_CHANNEL2 = environ.get("REQ_CHANNEL2", None)
REQ_CHANNEL2 = (int(REQ_CHANNEL2) if REQ_CHANNEL2 and id_pattern.search(REQ_CHANNEL2) else False) if REQ_CHANNEL2 is not None else None
JOIN_REQS_DB = environ.get("JOIN_REQS_DB", DATABASE_URI)

# Others
LOG_CHANNEL = int(log_channel) if (log_channel := environ.get('LOG_CHANNEL')) and id_pattern.search(log_channel) else None
FILE_STORE_CHANNEL = int(file_store) if (file_store := environ.get('FILE_STORE_CHANNEL')) and id_pattern.search(file_store) else 0
PUBLIC_FILE_STORE = int(pub_store) if (pub_store := environ.get('PUBLIC_FILE_STORE')) and id_pattern.search(pub_store) else 0
DISABLE_TOKENS = {'0', 'off', 'disable', 'false', 'none', 'null', 'no', 'n'}
post_channels_raw = environ.get('POST_CHANNELS', '').strip()
POST_CHANNELS = [
    int(ch) if id_pattern.search(ch) else ch
    for ch in post_channels_raw.split()
    if ch.strip().lower() not in DISABLE_TOKENS
]
SUPPORT_CHAT = environ.get('SUPPORT_CHAT')
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", script.CAPTION_TXT)
MAX_LIST_ELM = environ.get("MAX_LIST_ELM", None)
STREAM_URL = environ.get("STREAM_URL", "https://fhaaah.vercel.app/")
PROTECT_CONTENT = is_enabled((environ.get('PROTECT_CONTENT', 'False')), False)

LOG_STR = "Current Customized Configurations are:-\n"
LOG_STR += (f"CUSTOM_FILE_CAPTION enabled with value {CUSTOM_FILE_CAPTION}, your files will be send along with this customized caption.\n" if CUSTOM_FILE_CAPTION else "No CUSTOM_FILE_CAPTION Found, Default captions of file will be used.\n")
LOG_STR += (f"POST_CHANNELS enabled with {len(POST_CHANNELS)} target channel(s).\n" if POST_CHANNELS else "POST_CHANNELS disabled (value 0 or off).\n")

