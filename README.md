# 📦 Eva Maria Base Repo

A powerful and scalable Telegram bot for movie and file management, with support for:
- Force Subscription (with threshold and fallback)
- Global filters
- File indexing and retrieval
- User info and moderation tools
- Broadcast system
- Channel file tracking by language

---

## ✨ Features

- 🚀 Speed Index
- 🚄 Speed Broadcast
- 📂 Auto Indexing after restart
- 🔐 Force Subscribe (primary + fallback)
- 🧠 Intelligent Movie Matching (by filename, year, and language)
- 🧰 Global Filters (for buttons and media)
- 📊 Statistics and Database Monitoring
- 📢 Broadcast System
- 🛡️ Admin Moderation (ban/unban/disable chats)
- 🎥 Categorized Latest Movie Listing

---

## 🧾 Bot Commands

### 👥 General Users
| Command | Description |
|--------|-------------|
| `/start` | Start the bot and access commands |
| `/id` | Get your Telegram ID or message/file ID |
| `/info` | Fetch detailed info of a user (reply or @username) |
| `/request <movie name>` | Request a movie from admins |
| `/latest` | Get list of latest movies by language |
| `/stats` | Show bot usage statistics |
| `/ping` | Check Server ping |

---

### 🧑‍💻 Admin-Only Commands

#### 📊 System
| Command | Description |
|--------|-------------|
| `/broadcast <skip_count>` | Broadcast a message to all users |
| `/logs` | Download latest log file |
| `/delete_duplicate` | Delete duplicate files by same size different name or different thumbnail |
| `/deletefiles` | Delete files by sertain keyword or filename |

#### 🧾 Global Filters
| Command | Description |
|--------|-------------|
| `/gfilter <name>` | Add global filter (with reply or text) |
| `/gfilters` or `/viewgfilters` | View all global filters |
| `/delg <name>` | Delete a specific global filter |
| `/delallg` | Delete all global filters (with confirmation) |

#### 🛡️ Force Subscribe Management
| Command | Description |
|--------|-------------|
| `/sub1 <chat_id>` | Set Force Subscribe Channel 1 |
| `/sub2 <chat_id>` | Set Force Subscribe Channel 2 |
| `/sub3 <chat_id>` | Set Force Subscribe Channel 3 |
| `/2sub1 <chat_id>` | Set Secondary Channel for FS1 |
| `/2sub2 <chat_id>` | Set Secondary Channel for FS2 |
| `/2sub3 <chat_id>` | Set Secondary Channel for FS3 |
| `/delsub1 <chat_id>` | Del Force Subscribe Channel 1 |
| `/delsub2 <chat_id>` | Del Force Subscribe Channel 2 |
| `/delsub3 <chat_id>` | Del Force Subscribe Channel 3 |
| `/2delsub1 <chat_id>` | Del Secondary Channel for FS1 |
| `/2delsub2 <chat_id>` | Del Secondary Channel for FS2 |
| `/2delsub3 <chat_id>` | Del Secondary Channel for FS3 |
| `/setcount1 <number>` | Set threshold for FS1 |
| `/setcount2 <number>` | Set threshold for FS2 |
| `/setcount3 <number>` | Set threshold for FS3 |
| `/view_sub` | View all Force Subscribe settings and counts |

#### 🚨 Moderation
| Command | Description |
|--------|-------------|
| `/ban <user_id> [reason]` | Ban a user |
| `/unban <user_id>` | Unban a user |
| `/disable <chat_id> [reason]` | Disable bot in a group |
| `/enable <chat_id>` | Enable bot back in a group |
| `/leave <chat_id>` | Force bot to leave a group |

---
