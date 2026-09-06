# TGxCyberBot - Advanced Telegram Auto-Filter & Media Searcher Bot

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Pyrogram](https://img.shields.io/badge/library-Pyrogram_v2-orange.svg)](https://docs.pyrogram.org/)
[![MongoDB](https://img.shields.io/badge/database-MongoDB-green.svg)](https://www.mongodb.com/)
[![SQLite](https://img.shields.io/badge/database-SQLite3_Fast-lightblue.svg)](https://www.sqlite.org/)

**TGxCyberBot** is a production-grade, high-performance Telegram Auto-Filter and Media Indexer Bot. Powered by **Pyrogram**, dual-database architecture (**MongoDB + SQLite3 WAL mode**), multi-shard indexing, persistent auto-deletion timers, dynamic force-subscribe, online streaming integration, and automated trash management.

---

## ✨ Features

- 🔍 **High-Speed Hybrid Search**: Dual search engine utilizing SQLite3 WAL indexing and IMDb/OMDb suggestion fallback for 80%+ fuzzy accuracy matching.
- ⏱️ **Auto-Delete Engine**: Configurable auto-delete for search filter responses and delivered files with `DELETE_TXT` warnings.
- 🔄 **Persistent Timers Across Restarts**: Deletion tasks are stored in MongoDB and automatically resumed even after bot restarts.
- 🗑️ **Trash Management & `/deletetrash`**: Track every message sent by the bot and purge all bot messages across groups and DMs with a single command.
- 📅 **Weekly Automated Cleanup**: Automatic background cron job cleans trash once a week and notifies admins.
- 📢 **Dynamic Multi-Channel Force-Subscribe**: Dynamic multi-level FSub keyboard checking channels 1, 2, and 3 in real-time.
- 🎬 **Online Stream Button**: Automatically resolves TMDB movie/TV show stream links for watching files directly on web platforms.
- 📦 **File Store & Batch Links**: Share single files (`/link`, `/plink`) or entire batch ranges (`/batch`, `/pbatch`, `DSTORE`).
- 🌐 **Global Filters**: Add, list, and delete custom group/bot keyword triggers.

---

## 🛠️ Environment Variables Configuration Guide

Configure the following environment variables in `.env`, Heroku Config Vars, or Docker environment settings:

### 🔑 Mandatory Credentials

| Variable | Description | Required | Default |
| :--- | :--- | :---: | :--- |
| `BOT_TOKEN` | Bot API token obtained from [@BotFather](https://t.me/BotFather) | **Yes** | — |
| `API_ID` | Telegram API ID obtained from [my.telegram.org](https://my.telegram.org) | **Yes** | — |
| `API_HASH` | Telegram API Hash obtained from [my.telegram.org](https://my.telegram.org) | **Yes** | — |
| `ADMINS` | Space-separated Telegram User IDs of Bot Administrators (e.g. `12345678 87654321`) | **Yes** | — |
| `DATABASE_URI` | Main MongoDB connection URI (used for users, chats, settings, trash, and queue) | **Yes** | — |

### 🗄️ Multi-Database & Sharding Variables

| Variable | Description | Required | Default |
| :--- | :--- | :---: | :--- |
| `DATABASE_URI2` | Secondary MongoDB URI for multi-shard index storage (Shard 1) | No | `None` |
| `DATABASE_URI3` | Tertiary MongoDB URI for multi-shard index storage (Shard 2) | No | `None` |
| `DATABASE_NAME` | Name of the database in MongoDB | No | `CyberTG` |
| `COLLECTION_NAME` | Name of the media collection in MongoDB | No | `Telegram-Document` |
| `JOIN_REQS_DB` | MongoDB URI for channel join requests | No | Same as `DATABASE_URI` |

### 📢 Force-Subscribe (FSub) Variables

| Variable | Description | Required | Default |
| :--- | :--- | :---: | :--- |
| `AUTH_CHANNEL` | Single primary Channel ID for mandatory subscription check | No | `None` |
| `REQ_CHANNEL1` | Dynamic Force-Subscribe Channel ID 1 | No | `None` |
| `REQ_CHANNEL2` | Dynamic Force-Subscribe Channel ID 2 | No | `None` |
| `REQ_CHANNEL3` | Dynamic Force-Subscribe Channel ID 3 | No | `None` |
| `REQ_CHANNEL1_2` | Secondary Channel ID for FSub 1 thresholding | No | `None` |
| `REQ_CHANNEL2_2` | Secondary Channel ID for FSub 2 thresholding | No | `None` |
| `REQ_CHANNEL3_2` | Secondary Channel ID for FSub 3 thresholding | No | `None` |

### ⚙️ Bot Behavior & Customization Variables

| Variable | Description | Required | Default |
| :--- | :--- | :---: | :--- |
| `OWNER_ID` | Telegram User ID of the Bot Owner (receives startup & weekly cleanup reports) | No | `None` |
| `LOG_CHANNEL` | Channel ID for logging bot activity, bug reports, and indexing logs | No | `None` |
| `FILE_STORE_CHANNEL` | Channel ID for storing uploaded batch/protected store files | No | `0` |
| `PUBLIC_FILE_STORE` | Enable public file store link generation (`True`/`False` or `1`/`0`) | No | `False` |
| `POST_CHANNELS` | Space-separated Target Channel IDs for auto-posting latest releases | No | Empty |
| `CHANNELS` | Space-separated Channel IDs/Usernames for manual indexing | No | Empty |
| `AUTO_DEL` | Default file auto-delete duration in seconds | No | `900` (15m) |
| `MAX_FILES` | Maximum search results returned per result page | No | `8` |
| `CACHE_TIME` | Inline query cache time in seconds | No | `300` |
| `PICS` | Space-separated Telegraph/Imgur image URLs for start menu | No | Empty |
| `CUSTOM_FILE_CAPTION` | Custom file caption template (supports `{file_name}`, `{file_size}`, `{file_caption}`) | No | Default template |
| `STREAM_URL` | Web platform URL for online streaming button | No | `https://fhaaah.vercel.app/` |
| `PROTECT_CONTENT` | Prevent users from saving/forwarding delivered files (`True`/`False`) | No | `False` |
| `SUPPORT_CHAT` | Telegram Support Group username without `@` (e.g. `CyberTGx`) | No | `None` |
| `AUTH_USERS` | Space-separated user IDs authorized to use the bot (empty = public) | No | Empty |
| `SESSION` | Pyrogram session string name | No | `Media_searcher` |

---

## 🤖 Full Command Guide

### ⚡ General Commands
- `/start` – Start the bot or retrieve files via deep link.
- `/cmds` – View full command list and usage guide.
- `/ping` – Check bot response speed and server latency.
- `/id` – Get your Telegram User ID or current chat ID.
- `/info` – Get detailed profile info of a user (by reply or `@username`).
- `/latest` – View latest released movies grouped by language.
- `/request [movie_name]` – Submit a movie/series request to admins.
- `/reportbug [description]` – Report a bug or issue directly to admins.

### ⏱️ Auto-Delete & Trash Management
- `/setfiltertime [seconds/5m/10m]` – Set auto-delete duration for search filter responses. *(Admin Only)*
- `/setfiletime [seconds/15m/1h]` – Set auto-delete duration for sent files & warning notice. *(Admin Only)*
- `/deltimes` – View current filter and file auto-delete timer settings.
- `/deletetrash` – Immediately delete all bot messages across all chats, groups, and DMs. *(Admin Only)*

### 📁 File Sharing & Link Store
- `/link` *(reply to media)* – Generate a public shareable file link.
- `/plink` *(reply to media)* – Generate a protected shareable file link.
- `/batch [link1] [link2]` – Create a shareable batch link for a range of messages.
- `/pbatch [link1] [link2]` – Create a protected shareable batch link.

### 👑 Admin & Indexing Commands
- `/index` – Start indexing files from a channel (reply to channel post or send link/ID).
- `/setskip [number]` – Set skip offset count for indexing.
- `/stats` – View database document counts, user totals, and storage size.
- `/users` – View total registered bot users.
- `/chats` – View total connected Telegram groups.
- `/autofilter [on/off]` – Enable or disable group auto-filter mode.
- `/delete` *(reply to media)* – Delete a specific file document from database.
- `/deletefiles [keyword]` – Mass delete files matching a keyword.
- `/delete_duplicate` – Scan and delete duplicate media entries.
- `/deleteall` – Wipe all indexed media files from databases.
- `/broadcast` *(reply to message)* – Broadcast message to all registered users.
- `/update` – Pull git updates and restart the bot.

### 🔍 Global Filters
- `/gfilter [keyword] [text/reply]` – Add a global trigger filter. *(Admin Only)*
- `/gfilters` or `/viewgfilters` – View all active global filters.
- `/delg [keyword]` – Delete a specific global filter. *(Admin Only)*
- `/delallg` – Clear all global filters. *(Admin Only)*

### 📢 Force Subscribe (FSub) Management
- `/sub1 [chat_id]` / `/sub2` / `/sub3` – Set Primary FSub Channels.
- `/2sub1 [chat_id]` / `/2sub2` / `/2sub3` – Set Secondary FSub Channels.
- `/setcount1 [number]` / `/setcount2` / `/setcount3` – Set user threshold counts for FSub channels.
- `/delsub1` / `/delsub2` / `/delsub3` – Remove Primary FSub channels.
- `/2delsub1` / `/2delsub2` / `/2delsub3` – Remove Secondary FSub channels.
- `/view_sub` – View active FSub channel configuration & member counts.

### 🛡️ Moderation Tools
- `/ban [user_id] [reason]` – Ban a user from using the bot. *(Admin Only)*
- `/unban [user_id]` – Unban a banned user. *(Admin Only)*
- `/banned` – List all banned users and restricted chats. *(Admin Only)*
- `/disable [chat_id] [reason]` – Disable bot operations in a specific group. *(Admin Only)*
- `/enable [chat_id]` – Re-enable bot operations in a disabled group. *(Admin Only)*
- `/leave [chat_id]` – Force bot to leave a specified chat. *(Admin Only)*

---

## 🚀 Deployment Guide

### 1. Local / VPS Deployment

```bash
# Clone the repository
git clone https://github.com/itsafxal/TGxCyberBot.git
cd TGxCyberBot

# Install dependencies
pip install -r requirements.txt

# Create .env file with environment variables
cp .env.example .env

# Run the bot
python bot.py
```

### 2. Docker Deployment

```bash
# Build Docker image
docker build -t tgxcyberbot .

# Run container
docker run -d --name tgxcyberbot --env-file .env tgxcyberbot
```

### 3. Heroku Deployment

Click the button below or deploy via Heroku CLI:

```bash
heroku create tgxcyberbot
heroku config:set BOT_TOKEN="your_token" API_ID="your_api_id" API_HASH="your_api_hash" ADMINS="your_id" DATABASE_URI="your_mongo_uri" LOG_CHANNEL="-100xxxx"
git push heroku main
```

---

## 📜 License & Credits

Distributed under the MIT License. Built with ❤️ by [CyberTG](https://github.com/itsafxal).
