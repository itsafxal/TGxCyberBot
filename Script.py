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
‣ ᴅᴇᴠᴇʟᴏᴘᴇʀ : <a href='https://t.me/CyberTGz'>ᴄʏʙᴇʀ ᠰ ᴛɢ</a>
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
Group = {}(<code>{}</code>)
Total Members = <code>{}</code>
Added By - {}
"""
    LOG_TEXT_P = """#NewUser
ID - <code>{}</code>
Name - {}
@TheLadyRobot
"""
    CMDS_TXT = """<u>🎀 𝐀𝐝𝐦𝐢𝐧 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬 🎀</u>   
/broadcast <skip_count>	Broadcast a message to all users
/logs	Download latest log file
/delete_duplicate	Delete duplicate files by same size different name or different thumbnail
/deletefiles	Delete files by sertain keyword or filename
<u>𝐅𝐢𝐥𝐭𝐞𝐫𝐬</u>
/gfilter <name>	Add global filter (with reply or text)
/gfilters or /viewgfilters	View all global filters
/delg <name>	Delete a specific global filter
/delallg	Delete all global filters (with confirmation)

<u>⚡ 𝐅𝐬𝐮𝐛 ⚡</u>
/sub1 <chat_id>	Set Force Subscribe Channel 1
/sub2 <chat_id>	Set Force Subscribe Channel 2
/sub3 <chat_id>	Set Force Subscribe Channel 3
/2sub1 <chat_id>	Set Secondary Channel for FS1
/2sub2 <chat_id>	Set Secondary Channel for FS2
/2sub3 <chat_id>	Set Secondary Channel for FS3
/delsub1 <chat_id>	Del Force Subscribe Channel 1
/delsub2 <chat_id>	Del Force Subscribe Channel 2
/delsub3 <chat_id>	Del Force Subscribe Channel 3
/2delsub1 <chat_id>	Del Secondary Channel for FS1
/2delsub2 <chat_id>	Del Secondary Channel for FS2
/2delsub3 <chat_id>	Del Secondary Channel for FS3
/setcount1 <number>	Set threshold for FS1
/setcount2 <number>	Set threshold for FS2
/setcount3 <number>	Set threshold for FS3
/view_sub	View all Force Subscribe settings and counts
<u>🧿 𝐌𝐨𝐝𝐞𝐫𝐚𝐭𝐢𝐨𝐧 🧿</u>
Command	Description
/ban <user_id> [reason]	Ban a user
/unban <user_id>	Unban a user
/disable <chat_id> [reason]	Disable bot in a group
/enable <chat_id>	Enable bot back in a group
/leave <chat_id>	Force bot to leave a group"""
