import time
from pyrogram import Client, filters, enums
import psutil

start_time = time.time()

async def get_bot_uptime():
    uptime_seconds = int(time.time() - start_time)
    uptime_minutes = uptime_seconds // 60
    uptime_hours = uptime_minutes // 60
    uptime_days = uptime_hours // 24
    uptime_weeks = uptime_days // 7

    uptime_parts = []
    if uptime_weeks > 0:
        uptime_parts.append(f"{uptime_weeks}W")
    if uptime_days % 7 > 0 or not uptime_parts: # Add days if there are any, or if weeks isn't present
        uptime_parts.append(f"{uptime_days % 7}D")
    if uptime_hours % 24 > 0 or (not uptime_parts and (uptime_minutes % 60 > 0 or uptime_seconds % 60 > 0)):
        uptime_parts.append(f"{uptime_hours % 24}H")
    if uptime_minutes % 60 > 0 or (not uptime_parts and uptime_seconds % 60 > 0):
        uptime_parts.append(f"{uptime_minutes % 60}M")
    uptime_parts.append(f"{uptime_seconds % 60}S")
    
    return " : ".join(filter(None, uptime_parts))


@Client.on_message(filters.command("ping")) 
async def ping(bot, message):
    start_t = time.time()
    rm = await message.reply_text("⚡️ Pinging...")
    end_t = time.time()
    time_taken_ms = (end_t - start_t) * 1000
    uptime = await get_bot_uptime()
    cpu_usage = psutil.cpu_percent(interval=0.5) # Add interval for more accurate reading
    ram_usage = psutil.virtual_memory().percent    
    
    await rm.edit(
        f"📡 **Ping Status Report** 📊\n\n"
        f"  ➡️ **Latency:** `{time_taken_ms:.3f} ms`\n"
        f"  ⏱️ **Uptime:** `{uptime}`\n"
        f"  🤖 **CPU Usage:** `{cpu_usage:.2f} %`\n"
        f"  🧠 **RAM Usage:** `{ram_usage:.2f} %`\n\n",
        parse_mode=enums.ParseMode.MARKDOWN
    )
