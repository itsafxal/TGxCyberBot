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
• <code>/ping</code> - Check bot response speed
• <code>/id</code> - Get user or chat Telegram ID
• <code>/info</code> - Get detailed user information
• <code>/latest</code> - View latest movie releases
• <code>/request [movie_name]</code> - Request a movie or series
• <code>/reportbug [desc]</code> - Report a bug to admins

<b>📁 <u>File Sharing & Link Store</u></b>
• <code>/link</code> (reply to media) - Create a public file link
• <code>/plink</code> (reply to media) - Create a protected file link
• <code>/batch [link1] [link2]</code> - Create a batch file link
• <code>/pbatch [link1] [link2]</code> - Create a protected batch link

<b>👑 <u>Admin & Indexing Commands</u></b>
• Forward last msg or post link - Start channel indexing
• <code>/setskip [number]</code> - Set skip offset for indexing
• <code>/stats</code> - Show bot & database statistics
• <code>/users</code> - View total bot users
• <code>/chats</code> - View total connected chats
• <code>/autofilter [on/off]</code> - Enable or disable auto filter
• <code>/delete [file_name]</code> - Delete a specific file from DB
• <code>/deletefiles [keyword]</code> - Delete files matching keyword
• <code>/delete_duplicate</code> - Clean up duplicate media files
• <code>/deleteall</code> - Delete all indexed files from DB
• <code>/broadcast</code> (reply to msg) - Broadcast message to all users
• <code>/update</code> - Restart or update the bot

<b>🔍 <u>Global Filters</u></b>
• <code>/gfilter [name] [reply/text]</code> - Add a global filter
• <code>/gfilters</code> or <code>/viewgfilters</code> - View all active global filters
• <code>/delg [name]</code> - Delete a specific global filter
• <code>/delallg</code> - Clear all global filters

<b>📢 <u>Force Subscribe (FSub) Management</u></b>
• <code>/sub1 [chat_id]</code> - Set Primary FSub Channel 1
• <code>/sub2 [chat_id]</code> - Set Primary FSub Channel 2
• <code>/sub3 [chat_id]</code> - Set Primary FSub Channel 3
• <code>/2sub1 [chat_id]</code> - Set Secondary FSub Channel 1
• <code>/2sub2 [chat_id]</code> - Set Secondary FSub Channel 2
• <code>/2sub3 [chat_id]</code> - Set Secondary FSub Channel 3
• <code>/setcount1 [number]</code> - Set count threshold for FSub 1
• <code>/setcount2 [number]</code> - Set count threshold for FSub 2
• <code>/setcount3 [number]</code> - Set count threshold for FSub 3
• <code>/delsub1</code> / <code>/delsub2</code> / <code>/delsub3</code> - Remove Primary FSub
• <code>/2delsub1</code> / <code>/2delsub2</code> / <code>/2delsub3</code> - Remove Secondary FSub
• <code>/view_sub</code> - View all FSub status & counts

<b>🛡️ <u>Moderation & Admin Tools</u></b>
• <code>/ban [user_id] [reason]</code> - Ban a user from the bot
• <code>/unban [user_id]</code> - Unban a user
• <code>/disable [chat_id] [reason]</code> - Disable bot in a group
• <code>/enable [chat_id]</code> - Re-enable bot in a group
• <code>/leave [chat_id]</code> - Force bot to leave a group
• <code>/invite [chat_id]</code> - Generate invite link for a group"""
    
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



