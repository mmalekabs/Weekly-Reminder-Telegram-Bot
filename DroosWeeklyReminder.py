import logging
import json
import asyncio
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

from telegram.request import HTTPXRequest

# --- CONFIGURATION ---
BOT_TOKEN = "8496542750:AAERB_yV3t_LJw8FUUTcyUCtespOqlHKEy4"
SETTINGS_FILE = "group_settings.json"

# --- SCHEDULER WITH RIYADH TIMEZONE ---
# Riyadh is UTC+3
riyadh_tz = timezone(timedelta(hours=3))
scheduler = BackgroundScheduler(timezone=riyadh_tz)
scheduler.start()

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- STATE CONSTANTS ---
(
    CHOOSING_REPEAT, CHOOSING_DAY, SETTING_MESSAGE, CHOOSING_TIME
) = range(4)

# --- WEEKDAY MAPPING ---
WEEKDAY_MAP = {
    "monday": "mon",
    "tuesday": "tue", 
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun"
}

# --- STORAGE ---
def load_settings():
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

group_settings = load_settings()

# --- SCHEDULING ---
def schedule_message(context, chat_id, settings, loop):  
    job_id = f"{chat_id}_msg"  
    for job in scheduler.get_jobs():  
        if job.id.startswith(job_id):  
            scheduler.remove_job(job.id)  
    repeat = settings["repeat"]  
    message = settings["message"]  
    hour, minute = map(int, settings["time"].split(":"))  
    bot = context.bot  
  
    def send_msg():  
        async def send_message():  
            try:  
                await bot.send_message(chat_id=chat_id, text=message)  
                logger.info(f"Message sent successfully to {chat_id}")  
            except Exception as e:  
                logger.error(f"Failed to send message: {e}")  
  
        # Use the main event loop passed from main thread  
        asyncio.run_coroutine_threadsafe(send_message(), loop)  
  
    if repeat == "daily":  
        scheduler.add_job(send_msg, "cron", hour=hour, minute=minute, id=job_id)  
    elif repeat == "weekly":  
        scheduler.add_job(send_msg, "cron", day_of_week=settings["day"], hour=hour, minute=minute, id=job_id)  
    elif repeat == "monthly":  
        scheduler.add_job(send_msg, "cron", day=settings["day"], hour=hour, minute=minute, id=job_id)  
    elif repeat == "custom":  
        for d in settings["days"]:  
            scheduler.add_job(send_msg, "cron", day_of_week=d, hour=hour, minute=minute, id=f"{job_id}_{d}")

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! Use /setday to schedule your message."
    )

async def setday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "How often do you want to send the message? (daily/weekly/custom/monthly)"
    )
    return CHOOSING_REPEAT

async def choose_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repeat = update.message.text.lower()
    context.user_data["repeat"] = repeat
    if repeat == "daily":
        await update.message.reply_text("What message should I send?")
        return SETTING_MESSAGE
    elif repeat == "weekly":
        await update.message.reply_text("Which day? (e.g., Monday)")
        return CHOOSING_DAY
    elif repeat == "monthly":
        await update.message.reply_text("Which day of the month? (1-31)")
        return CHOOSING_DAY
    elif repeat == "custom":
        await update.message.reply_text("Which days? (comma-separated, e.g., Monday,Thursday)")
        return CHOOSING_DAY
    else:
        await update.message.reply_text("Invalid option. Please type daily, weekly, custom, or monthly.")
        return CHOOSING_REPEAT

async def choose_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repeat = context.user_data["repeat"]
    day = update.message.text.lower()
    if repeat == "weekly":
        # Convert to short form
        day_short = WEEKDAY_MAP.get(day)
        if not day_short:
            await update.message.reply_text("Please enter a valid weekday (e.g., Monday).")
            return CHOOSING_DAY
        context.user_data["day"] = day_short
    elif repeat == "monthly":
        try:
            context.user_data["day"] = int(day)
        except ValueError:
            await update.message.reply_text("Please enter a valid day of the month (1-31).")
            return CHOOSING_DAY
    elif repeat == "custom":
        days = [d.strip().lower() for d in day.split(",")]
        days_short = []
        for d in days:
            short = WEEKDAY_MAP.get(d)
            if not short:
                await update.message.reply_text(f"Invalid weekday: {d}. Please use names like Monday, Thursday, etc.")
                return CHOOSING_DAY
            days_short.append(short)
        context.user_data["days"] = days_short
    await update.message.reply_text("What message should I send?")
    return SETTING_MESSAGE

async def set_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["message"] = update.message.text
    await update.message.reply_text("At what time? (HH:MM, 24h format - Riyadh time)")
    return CHOOSING_TIME

async def choose_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    # Validate time format
    try:
        datetime.strptime(t, "%H:%M")
    except ValueError:
        await update.message.reply_text("Please enter time in HH:MM (24h) format.")
        return CHOOSING_TIME

    context.user_data["time"] = t
    chat_id = update.effective_chat.id
    repeat = context.user_data["repeat"]
    settings = {
        "repeat": repeat,
        "time": context.user_data["time"],
        "message": context.user_data["message"]
    }
    if repeat == "weekly":
        settings["day"] = context.user_data["day"]
    elif repeat == "monthly":
        settings["day"] = context.user_data["day"]
    elif repeat == "custom":
        settings["days"] = context.user_data["days"]

    group_settings[str(chat_id)] = settings
    save_settings(group_settings)
    schedule_message(context, chat_id, settings)
    await update.message.reply_text(f"Schedule set! I'll send your message at {t} Riyadh time as requested.")
    return ConversationHandler.END

async def modify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /setday to modify the schedule or message.")

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    settings = group_settings.get(chat_id)
    if not settings:
        await update.message.reply_text("No schedule set. Use /setday to create one.")
    else:
        pretty = json.dumps(settings, indent=2, ensure_ascii=False)
        await update.message.reply_text(f"Current settings (Riyadh time):\n{pretty}")

async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text(
                "Hi! I'm here to help schedule messages. Use /setday to get started."
            )

# --- MAIN ---
def main():
    # Configure request with longer timeout and larger connection pool
    request = HTTPXRequest(
        connection_pool_size=50,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30
    )

    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    # Add handlers BEFORE starting polling
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("setday", setday)],
        states={
            CHOOSING_REPEAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_repeat)],
            CHOOSING_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_day)],
            SETTING_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_message)],
            CHOOSING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_time)],
        },
        fallbacks=[CommandHandler("setday", setday)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("modify", modify))
    app.add_handler(CommandHandler("settings", show_settings))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))

    # Get the running event loop from the main thread
    loop = asyncio.get_event_loop()

    # Reschedule jobs on restart, passing the loop
    for chat_id, settings in group_settings.items():
        schedule_message(app, int(chat_id), settings, loop)

    # Start polling (this blocks)
    app.run_polling()

if __name__ == "__main__":
    main()