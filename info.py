import re
from os import environ
from Script import script

id_pattern = re.compile(r'^.\d+$')
def is_enabled(value, default):
    if value.lower() in ["true", "yes", "1", "enable", "y"]:
        return True
    elif value.lower() in ["false", "no", "0", "disable", "n"]:
        return False
    else:
        return default

# Bot information
SESSION = environ.get('SESSION', 'Media_searcher')
API_ID = int(environ.get('API_ID', '21352077'))
API_HASH = environ.get('API_HASH', 'e4ba74d3f410dffbe848402989e61a04')
BOT_TOKEN = environ.get('BOT_TOKEN', '8266889397:AAH9B8JnWCkGhZ9wgSN43otYwaxpk4Kxpik')

# Bot settings
AUTO_DEL = int(environ.get('AUTO_DEL', 900))
MAX_FILES = int(environ.get('MAX_FILES', 8))
CACHE_TIME = int(environ.get('CACHE_TIME', 300))
USE_CAPTION_FILTER = True

# Pics
PICS = (environ.get('PICS', '')).split()

# Admins & Users
OWNER_ID = environ.get('OWNER_ID', '5483128891')
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '5483128891').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '').split()]
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '').split()]
AUTH_USERS = (auth_users + ADMINS) if auth_users else []

# MongoDB information
DATABASE_NAME = environ.get('DATABASE_NAME', "CyberTG")
COLLECTION_NAME = environ.get('COLLECTION_NAME', "Telegram-Document")
DATABASE_URI = environ.get('DATABASE_URI', "mongodb+srv://SadieDB1:SadieDB1@sadiedb1.r4iyd6u.mongodb.net/?retryWrites=true&w=majority&appName=SadieDB1")
DATABASE_URI2 = environ.get('DATABASE_URI2', "mongodb+srv://SadieDB2:SadieDB2@cluster0.ajdm5la.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
DATABASE_URI3 = environ.get('DATABASE_URI3', "mongodb+srv://SadieDB3:SadieDB3@sadiedb3.p79deso.mongodb.net/?retryWrites=true&w=majority&appName=SadieDB3")

# FSUB
AUTH_CHANNEL = int(environ.get('AUTH_CHANNEL')) if (auth_channel := environ.get('AUTH_CHANNEL')) and id_pattern.search(auth_channel) else None
REQ_CHANNEL1=environ.get("REQ_CHANNEL1", None)
REQ_CHANNEL1 = (int(REQ_CHANNEL1) if REQ_CHANNEL1 and id_pattern.search(REQ_CHANNEL1) else False) if REQ_CHANNEL1 is not None else None
REQ_CHANNEL2 = environ.get("REQ_CHANNEL2", None)
REQ_CHANNEL2 = (int(REQ_CHANNEL2) if REQ_CHANNEL2 and id_pattern.search(REQ_CHANNEL2) else False) if REQ_CHANNEL2 is not None else None
JOIN_REQS_DB = environ.get("JOIN_REQS_DB", DATABASE_URI)

# Others
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-1003094463113'))
FILE_STORE_CHANNEL = int(environ.get('FILE_STORE_CHANNEL', 0))
PUBLIC_FILE_STORE = int(environ.get('PUBLIC_FILE_STORE', 0))
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'MLZ_BOTZ_SUPPORT') # Please set your support chat link
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", script.CAPTION_TXT)
MAX_LIST_ELM = environ.get("MAX_LIST_ELM", None)

LOG_STR = "Current Cusomized Configurations are:-\n"
LOG_STR += (f"CUSTOM_FILE_CAPTION enabled with value {CUSTOM_FILE_CAPTION}, your files will be send along with this customized caption.\n" if CUSTOM_FILE_CAPTION else "No CUSTOM_FILE_CAPTION Found, Default captions of file will be used.\n")
