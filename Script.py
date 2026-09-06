class script(object):
    START_TXT = """👋 𝙃𝙚𝙮 𝙩𝙝𝙚𝙧𝙚, {}!

𝙄'𝙢 𝙮𝙤𝙪𝙧 𝙖𝙪𝙩𝙤-𝙛𝙞𝙡𝙩𝙚𝙧 𝙗𝙤𝙩 – 𝙖𝙙𝙫𝙖𝙣𝙘𝙚𝙙, 𝙥𝙤𝙬𝙚𝙧𝙛𝙪𝙡, 𝙖𝙣𝙙 𝙙𝙚𝙨𝙞𝙜𝙣𝙚𝙙 𝙩𝙤 𝙢𝙖𝙠𝙚 𝙮𝙤𝙪𝙧 𝙜𝙧𝙤𝙪𝙥𝙨 𝙩𝙤 𝙢𝙤𝙫𝙞𝙚 𝙧𝙚𝙦𝙪𝙚𝙨𝙩 𝙜𝙧𝙤𝙪𝙥!  

𝙇𝙚𝙩'𝙨 𝙜𝙚𝙩 𝙨𝙩𝙖𝙧𝙩𝙚𝙙! 🚀"""
    
    HELP_TXT = """**Iᴛ ɪs ᴇᴀsʏ ᴛᴏ ᴜsᴇ ᴍᴇ Jᴜsᴛ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴏʀ Sᴇᴀʀᴄʜ ʏᴏᴜʀ ᴍᴏᴠɪᴇs ᴏɴ ʙᴏᴛ ᴘᴍ (Hᴇʀᴇ) 😉

<blockquote><u>Sᴏᴍᴇ Oғ Mʏ  Cᴏᴍᴍᴀɴᴅs</u>
‣/latest - Gᴇᴛ ʟɪsᴛ ᴏғ ʟᴀᴛᴇsᴛ ᴍᴏᴠɪᴇs ʙʏ ʟᴀɴɢᴜᴀɢᴇ
‣/request <movie name> - Rᴇᴏ̨ᴜᴇsᴛ ᴀ ᴍᴏᴠɪᴇ ғʀᴏᴍ ᴀᴅᴍɪɴs
‣/id - Gᴇᴛ ʏᴏᴜʀ Tᴇʟᴇɢʀᴀᴍ ID ᴏʀ ᴍᴇssᴀɢᴇ/ғɪʟᴇ ID
‣/info - Fᴇᴛᴄʜ ᴅᴇᴛᴀɪʟᴇᴅ ɪɴғᴏ ᴏғ ᴀ ᴜsᴇʀ (ʀᴇᴘʟʏ ᴏʀ @ᴜsᴇʀɴᴀᴍᴇ)
‣/ping - Cʜᴇᴄᴋ Sᴇʀᴠᴇʀ ᴘɪɴɢ
‣/broadcast - Rᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇssᴀɢᴇ ᴛᴏ sᴇɴᴅ ᴛʜᴀᴛ ᴛᴏ ᴀʟʟ ʙᴏᴛ ᴜsᴇʀs (ᴀᴅᴍɪɴ ᴏɴʟʏ)</blockquote>**"""
    
    ABOUT_TXT = """<blockquote><b>
‣ ᴍʏ ɴᴀᴍᴇ : <a href='https://t.me/FilmSercher'>Fɪʟᴍ Bᴏᴛ</a>
‣ ᴄʀᴇᴀᴛᴏʀ : <a href='tg://settings'>ᴛʜɪs ᴘᴇʀsᴏɴ</a>
‣ ᴅᴇᴠᴇʟᴏᴘᴇʀ : <a href='https://cybertg.vercel.app'>ᴄʏʙᴇʀ ᠰ ᴛɢ</a>
‣ ʟɪʙʀᴀʀʏ : <a href='https://docs.pyrogram.org/'>ᴘʏʀᴏɢʀᴀᴍ</a>
‣ ʟᴀɴɢᴜᴀɢᴇ : <a href='https://www.python.org/download/releases/3.0/'>ᴘʏᴛʜᴏɴ 3</a>
‣ ᴅᴀᴛᴀ ʙᴀsᴇ : <a href='https://www.mongodb.com/'>ᴍᴏɴɢᴏ ᴅʙ</a>
‣ ʙᴏᴛ sᴇʀᴠᴇʀ : <a href='https://t.me/quickfastt'>ǫᴜɪᴄᴋ ꜰᴀsᴛ</a></b></blockquote>"""

    CAPTION_TXT = """
<code>{file_name}</code>

<b>╔════ ᴊᴏɪɴ ᴡɪᴛʜ ᴜs ═════╗
◻️ 𝙅𝙊𝙄𝙉 :- @wwwCinemaCourt
◻️ 𝙅𝙊𝙄𝙉 :- @CKFamilyTG
╚════ ᴊᴏɪɴ ᴡɪᴛʜ ᴜs ═════╝</b>
"""

    STATUS_TXT = """📈 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬 𝐎𝐯𝐞𝐫𝐯𝐢𝐞𝐰 📊
    
📚 𝐓𝐨𝐭𝐚𝐥 𝐅𝐢𝐥𝐞𝐬: {}
👥 𝐓𝐨𝐭𝐚𝐥 𝐔𝐬𝐞𝐫𝐬: {}
💬 𝐓𝐨𝐭𝐚𝐥 𝐂𝐡𝐚𝐭𝐬: {}

💾 𝐃𝐚𝐭𝐚𝐛𝐚𝐬𝐞 𝐒𝐢𝐳𝐞𝐬:
• 𝐃𝐁𝟏: {:.2f} 𝐌𝐁
• 𝐃𝐁𝟐: {:.2f} 𝐌𝐁
• 𝐃𝐁𝟑: {:.2f} 𝐌𝐁"""
        
    LOG_TEXT_G = """#NewGroup

🏷 Group : {}
🆔 Group ID : <code>{}</code>
👥 Members : {}

➕ Added By : {}
🆔 Adder ID : <code>{}</code>
📛 Username : @{}

🤖 Bot : @{}
"""
    LOG_TEXT_P = """#NewUser

👤 Name : {}
👥 Full Name : {} {}
🆔 ID : <code>{}</code>
📛 Username : @{}
🤖 Bot : @{}
"""
    CMDS_TXT = """<b><u>🤖 BOT COMMANDS & USAGE GUIDE 🤖</u></b>

<b>⚡ <u>General Commands</u></b>
• <code>/start</code> - Start the bot or open file link
• <code>/cmds</code> - View command list & usage
• <code>/ping</code> - Check bot response speed & server latency
• <code>/id</code> - Get your Telegram ID or chat ID
• <code>/info</code> - Get detailed user info (reply or @username)
• <code>/latest</code> - View latest movie releases by language
• <code>/request [movie]</code> - Send a movie/series request to admins
• <code>/reportbug [desc]</code> - Report a bug/issue to admins

<b>📁 <u>File Sharing & Link Store</u></b>
• <code>/link</code> (reply to media) - Generate a public file link
• <code>/plink</code> (reply to media) - Generate a protected file link
• <code>/batch [link1] [link2]</code> - Generate a batch file link
• <code>/pbatch [link1] [link2]</code> - Generate a protected batch link

<b>⏱️ <u>Auto-Delete & Trash Management</u></b>
• <code>/setfiltertime [time]</code> - Set auto-delete time for filter responses (e.g. <code>300</code>, <code>5m</code>)
• <code>/setfiletime [time]</code> - Set auto-delete time for sent files & warning (e.g. <code>900</code>, <code>15m</code>)
• <code>/deltimes</code> - View current filter & file auto-delete timer settings
• <code>/deletetrash</code> - Immediately delete all bot messages across all chats, groups & DMs

<b>👑 <u>Admin & Indexing Commands</u></b>
• <code>/index</code> - Start indexing a channel by replying or sending channel ID/link
• <code>/setskip [number]</code> - Set skip offset count for indexing
• <code>/stats</code> - View bot & database usage statistics
• <code>/users</code> - View total registered bot users
• <code>/chats</code> - View total connected groups/chats
• <code>/autofilter [on/off]</code> - Enable or disable auto-filter mode
• <code>/delete</code> (reply to file) - Delete specific file from databases
• <code>/deletefiles [keyword]</code> - Delete files matching keyword
• <code>/delete_duplicate</code> - Scan and remove duplicate media files
• <code>/deleteall</code> - Delete all indexed files from databases
• <code>/broadcast</code> (reply to msg) - Broadcast message to all bot users
• <code>/update</code> - Git pull updates & restart bot

<b>🔍 <u>Global Filters</u></b>
• <code>/gfilter [name] [text/reply]</code> - Add a global filter keyword
• <code>/gfilters</code> or <code>/viewgfilters</code> - View all active global filters
• <code>/delg [name]</code> - Delete a specific global filter
• <code>/delallg</code> - Clear all global filters

<b>📢 <u>Force Subscribe (FSub) Management</u></b>
• <code>/sub1 [chat_id]</code> / <code>/sub2</code> / <code>/sub3</code> - Set Primary FSub Channels
• <code>/2sub1 [chat_id]</code> / <code>/2sub2</code> / <code>/2sub3</code> - Set Secondary FSub Channels
• <code>/setcount1 [num]</code> / <code>/setcount2</code> / <code>/setcount3</code> - Set FSub user count thresholds
• <code>/delsub1</code> / <code>/delsub2</code> / <code>/delsub3</code> - Remove Primary FSub channels
• <code>/2delsub1</code> / <code>/2delsub2</code> / <code>/2delsub3</code> - Remove Secondary FSub channels
• <code>/view_sub</code> - View active FSub channels and threshold status

<b>🛡️ <u>Moderation & Admin Tools</u></b>
• <code>/ban [user_id] [reason]</code> - Ban a user from using the bot
• <code>/unban [user_id]</code> - Unban a user
• <code>/banned</code> - View list of banned users & chats
• <code>/disable [chat_id] [reason]</code> - Disable bot in a specific group
• <code>/enable [chat_id]</code> - Re-enable bot in a group
• <code>/leave [chat_id]</code> - Force bot to leave a group"""
    
    MAIN_RESULT_TXT = """𝗛𝗘𝗬 <emoji id='5413694143601842851'>👋</emoji> {cyber} <emoji id='5397890811436213746'>🫶</emoji>
    
<emoji id='5800835941543186089'>📁</emoji> <b>Query :</b> {search}

<emoji id='5413879192267805083'>🗓️</emoji> <b><i>Page No ›</i></b> `{page}`

<emoji id='5458382591121964689'>✍️</emoji> NOTE : <emoji id='5188463524568926712'>⚠️</emoji> This Message Will Be Auto Deleted Within 15 Mins <emoji id='6312353154788758411'>❗️</emoji>
©ᶜʸᵇᵉʳᵗᵍ <emoji id='5456140674028019486'>🗡️</emoji>"""

    SPELL_CHECK_TXT = """Hᴇʏ {cyber} 💫,
🔎 <b>Nᴏ ᴇxᴀᴄᴛ ʀᴇsᴜʟᴛ ғᴏᴜɴᴅ ғᴏʀ:</b>
<code>{search}</code>

✨ <b>Cʟᴏsᴇsᴛ ᴍᴀᴛᴄʜᴇs:</b>"""

    AUTO_ANNOUNCEMENT_TXT = """🎬 <b>{file_name}</b>"""



