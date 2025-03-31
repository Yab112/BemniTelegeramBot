import logging
import asyncio
from datetime import datetime, date
import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application, ChatMemberHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from apscheduler.triggers.cron import CronTrigger
import re
from dotenv import load_dotenv
import os


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_URL = os.getenv("DB_URL")
                   
# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# Store deadlines and jobs
deadlines = {}
scheduled_jobs = {}
scheduler = AsyncIOScheduler(timezone="UTC")

app = Application.builder().token(BOT_TOKEN).read_timeout(30).write_timeout(30) .connect_timeout(30) .pool_timeout(30)  .build()

# PostgreSQL connection pool
async def create_db_pool():
    try:
        pool = await asyncpg.create_pool(DB_URL)
        
        # Initialize database schema if it doesn't exist
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deadlines (
                    group_id BIGINT PRIMARY KEY,
                    deadline_date DATE NOT NULL
                )
            """)
            logger.info("✅ Database schema initialized")
            
        return pool
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        raise

db_pool = None

async def get_deadline_from_db(group_id: int):
    """Retrieve the deadline from the database."""
    async with db_pool.acquire() as connection:
        result = await connection.fetchrow("SELECT deadline_date FROM deadlines WHERE group_id=$1", group_id)
        if result:
            return result['deadline_date']
    return None

async def set_deadline_in_db(group_id: int, deadline_date: date):
    """Store the deadline in the database."""
    async with db_pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO deadlines (group_id, deadline_date) VALUES ($1, $2) "
            "ON CONFLICT (group_id) DO UPDATE SET deadline_date=$2",
            group_id, deadline_date
        )

def clean_markdown(text: str) -> str:
    """Properly escapes MarkdownV2 special characters without over-escaping."""
    # List of special characters that need escaping in MarkdownV2
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    
    # Escape only when not already escaped
    def escape_char(match):
        char = match.group(0)
        return f'\\{char}'
    
    # Escape all special chars that aren't already escaped
    pattern = f'(?<!\\\\)([{re.escape(escape_chars)}])'
    return re.sub(pattern, escape_char, text)

def format_message(days: int) -> str:
    """Generates visually engaging countdown messages with proper MarkdownV2 formatting."""
    if days == 0:
        return clean_markdown(
            "🚨🚨🚨 TODAY IS THE DEADLINE! 🚨🚨🚨\n\n"
            "🔥 DROP EVERYTHING AND FINISH! 🔥\n"
            "▪️ No procrastination!\n"
            "▪️ No excuses!\n"
            "▪️ Just GET IT DONE! ✅"
        )
    elif days == 1:
        return clean_markdown(
            "⚠️⚠️ ONE DAY LEFT! ⚠️⚠️\n\n"
            "⏰ FINAL PUSH! ⏰\n"
            "▪️ Review everything!\n"
            "▪️ Fix last-minute issues!\n"
            "▪️ You're almost there! 💪"
        )
    elif days <= 3:
        return clean_markdown(
            f"🔔 {days} DAYS LEFT! 🔔\n\n"
            "❗ Urgent Action Needed! ❗\n"
            "▪️ Prioritize critical tasks!\n"
            "▪️ No distractions!\n"
            "▪️ Stay focused! 🎯"
        )
    elif days <= 7:
        return clean_markdown(
            f"🔥🔥🔥 **{days} DAYS LEFT!** 🔥🔥🔥\n\n"
            "🚨🚨 **TIME IS RUNNING OUT!** 🚨🚨\n"
            "⚠️ **NO ROOM FOR MISTAKES!** ⚠️\n"
            "🛑 **FINAL PUSH!** 🛑\n"
            "🔥 **WORK FAST!** 🔥 **WORK SMART!** 🔥 **NO EXCUSES!** 🚀\n"
            "⏳ **EVERY SECOND COUNTS!** ⏳"
        )
    elif days <= 14:
        return clean_markdown(
            f"⚠️⚠️⚠️ **{days} DAYS REMAINING!** ⚠️⚠️⚠️\n\n"
            "🚨 **DANGER ZONE!** 🚨\n"
            "🔥 **DON'T GET COMPLACENT!** 🔥\n"
            "⏳ **THE CLOCK IS MERCILESS!** ⏳\n"
            "💀 **WASTE A DAY, REGRET IT FOREVER!** 💀\n"
            "🚀 **FULL SPEED AHEAD!** 🚀"
        )
    else:
        return clean_markdown(
            f"🟥🟥🟥 **{days} DAYS LEFT!** 🟥🟥🟥\n\n"
            "🚨 **RED ALERT!** 🚨\n"
            "🔥 **THE DEADLINE IS WATCHING YOU!** 🔥\n"
            "💀 **EVERY HOUR YOU WASTE BRINGS DOOM!** 💀\n"
            "⏳ **NO SECOND CHANCES!** ⏳\n"
            "🛑 **START WORKING NOW OR SUFFER LATER!** 🛑"
        )

async def send_countdown(group_id: int):
    """Sends the formatted countdown message to the group."""
    if group_id not in deadlines:
        return

    message = format_message((deadlines[group_id] - date.today()).days)
    try:
        await app.bot.send_message(
            chat_id=group_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"Failed to send message to group {group_id}: {e}")

async def ask_for_deadline(group_id: int):
    """Sends a properly formatted welcome message."""
    welcome_msg = clean_markdown(
        "🎉 Welcome to Deadline Countdown Bot! 🎉\n\n"
        "📅 To get started, send me your deadline in this format:\n"
        "`YYYY-MM-DD`\n\n"
        "Example: `2025-12-31`\n\n"
        "⏳ I'll send daily reminders to keep everyone on track! 🚀"
    )
    try:
        await app.bot.send_message(
            chat_id=group_id,
            text=welcome_msg,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"Failed to send welcome message to group {group_id}: {e}")

async def handle_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles deadline input with a fun confirmation."""
    group_id = update.message.chat_id
    try:
        # Process the date
        deadline_date = datetime.strptime(update.message.text, "%Y-%m-%d").date()
        days_left = (deadline_date - date.today()).days
        
        if days_left < 0:
            await update.message.reply_text(
                "❌ That date has already passed\\!\n"
                "Set a future date like `2025-12-31`. ",
                parse_mode="MarkdownV2"
            )
            return
        
        deadlines[group_id] = deadline_date
        
        # Store the deadline in the database
        await set_deadline_in_db(group_id, deadline_date)
        
        # Remove old job if exists
        if group_id in scheduled_jobs:
            scheduled_jobs[group_id].remove()
        
        # Schedule new job
        job = scheduler.add_job(
            send_countdown,
            trigger=CronTrigger(hour=7, minute=0, timezone="Africa/Addis_Ababa"),
            args=[group_id],
            id=f"countdown_{group_id}"
        )

        scheduled_jobs[group_id] = job
        
        # Escape the message and send the confirmation
        confirmation_message = f"✅ Deadline Set\\! ✅\n\n" \
                               f"🗓 Date: `{deadline_date}`\n" \
                               f"⏳ Days Left: `{days_left}`\n\n" \
                               "📢 Daily reminders will arrive at 9:00 AM UTC\\! ⏰"
        await update.message.reply_text(
            clean_markdown(confirmation_message),
            parse_mode="MarkdownV2"
        )
        
        # Send first countdown immediately
        await send_countdown(group_id)
        
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid Format\\!\n"
            "Please use `YYYY-MM-DD` (e.g., `2025-12-31`).",
            parse_mode="MarkdownV2"
        )

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers when the bot is added to a group."""
    if update.my_chat_member:
        chat_member = update.my_chat_member
        if (
            chat_member.new_chat_member.status in ["member", "administrator"]
            and chat_member.new_chat_member.user.id == context.bot.id
        ):
            group_id = chat_member.chat.id
            
            # Check for existing deadline in the database
            deadline_date = await get_deadline_from_db(group_id)
            if deadline_date:
                deadlines[group_id] = deadline_date
            
            await ask_for_deadline(group_id)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors."""
    logger.error(f"Update {update} caused error: {context.error}")

def setup_handlers():
    """Set up all handlers."""
    app.add_handler(ChatMemberHandler(new_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, handle_deadline))
    app.add_error_handler(error_handler)

async def main():
    """Main function to start the bot."""
    global db_pool
    logger.info("Starting bot...")
    
    # Start the PostgreSQL connection pool
    db_pool = await create_db_pool()
    
    # Start the scheduler
    scheduler.start()
    
    # Set up handlers
    setup_handlers()
    
    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Run until interrupted
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping bot...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        scheduler.shutdown()
        await db_pool.close()

if __name__ == "__main__":
    asyncio.run(main())
