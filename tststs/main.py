#!/usr/bin/env python3
"""
Rozdum Telegram Bot — Головний бот платформи

- Автоматизований пошук виконавців (Taxi System)
- Ескроу-система платежів
- Управління профілем, завданнями, фінансами
- Інтеграція з анонімним чатом та адмін-ботом

Перед запуском:
- Заповніть .env з усіма токенами та ключами
- Встановіть залежності з requirements.txt

Документація: див. README.md
"""

import logging
import os
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram import Update
import asyncio

# Завантажити змінні середовища з .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# Import removed - ADMIN_ID is read from environment directly
from database import init_database
from handlers.start import start_command, button_handler
import handlers.start as start_command_handlers
from handlers.profile import profile_handlers
from handlers.tasks import task_handlers, task_message_handlers
from handlers.executor import executor_handlers

# Configure logging with better filtering
import os
os.makedirs('logs/main_bot', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/main_bot/main_bot.log'),
        logging.StreamHandler()
    ]
)

# Disable verbose HTTP logging from httpx and telegram
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot."""
    error_msg = str(context.error)
    
    # Handle network errors quietly (they're temporary)
    if any(error_type in error_msg for error_type in ["httpx.ReadError", "NetworkError", "TimeoutError", "ConnectError"]):
        logger.warning(f"Network error (temporary): {error_msg}")
        return
    
    # Handle specific Telegram API errors gracefully
    if "Message is not modified" in error_msg:
        logger.warning("Attempted to edit message with same content - ignoring")
        if update.callback_query:
            await update.callback_query.answer("✅ Оновлено")
        return
    
    # Log other errors
    logger.error(f"Exception while handling an update: {context.error}")

    # For other errors, try to inform the user
    try:
        if update.callback_query:
            await update.callback_query.answer("❌ Виникла помилка. Спробуйте ще раз.")
        elif update.message:
            await update.message.reply_text("❌ Виникла помилка. Спробуйте ще раз.")
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}")

def main():
    """Start the bot."""
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not found in environment variables")

    admin_id_str = os.getenv("ADMIN_ID")
    if admin_id_str:
        try:
            admin_id = int(admin_id_str)
        except ValueError:
            logger.warning("ADMIN_ID is not a valid integer, using default")
            admin_id = 5857065034  # Default to @fezerstop
    else:
        admin_id = 5857065034  # Default to @fezerstop
    # Initialize database
    init_database()

    # Set @fezerstop as highest level admin (Level 5) with both ID and username
    try:
        from database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if fezerstop user exists by ID
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (admin_id,))
        if not cursor.fetchone():
            # Create fezerstop user with Level 5 admin
            cursor.execute("""
                INSERT INTO users (user_id, username, balance, rating, is_executor, is_admin, admin_level, created_at)
                VALUES (?, ?, 0.0, 5.0, 0, 1, 5, datetime('now'))
            """, (admin_id, "fezerstop"))
            logger.info("Created @fezerstop user with Level 5 admin")
        else:
            # Update existing user to ensure proper admin status and username
            cursor.execute("""
                UPDATE users SET username = ?, is_admin = 1, admin_level = 5
                WHERE user_id = ?
            """, ("fezerstop", admin_id))
            logger.info("Updated @fezerstop to Level 5 admin")

        conn.commit()
        conn.close()
        logger.info("@fezerstop (ID: %s, username: fezerstop) set as highest level admin (Level 5)", admin_id)
    except Exception as e:
        logger.error(f"Failed to set @fezerstop as admin: {e}")

    # Create application with better network configuration
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    logger.info("Adding handlers...")

    # Add error handler
    application.add_error_handler(error_handler)

    # Add all handlers from different modules
    from handlers.start import start_command, button_handler
    import handlers.start as start_command_handlers
    from handlers.profile import profile_handlers
    from handlers.tasks import task_handlers, task_message_handlers
    from handlers.executor import executor_handlers
    from handlers.admin import admin_handlers

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("give", start_command_handlers.give_money_command))
    application.add_handler(CommandHandler("code_pas", start_command_handlers.admin_code_command))

    # Add specific handlers first (more specific patterns)
    # Add executor handlers
    for handler in executor_handlers:
        application.add_handler(handler)

    # Add task handlers  
    for handler in task_handlers:
        application.add_handler(handler)

    # Add profile handlers
    for handler in profile_handlers:
        application.add_handler(handler)

    # Add task message handlers
    for handler in task_message_handlers:
        application.add_handler(handler)

    # Add admin handlers
    for handler in admin_handlers:
        application.add_handler(handler)

    # Chat functionality moved to separate bot @Rozdum_ChatBot
    logger.info("Chat functionality handled by separate chat bot")

    # Add general button handler last (catches all remaining callback queries)
    application.add_handler(CallbackQueryHandler(button_handler))


    # Log startup
    logger.info("Rozdum Bot started successfully!")

    # Start task scheduler  
    try:
        from utils.task_scheduler import scheduler
        
        # Schedule the task scheduler to start after bot is running
        async def start_scheduler_callback(context):
            try:
                await scheduler.start(context.bot)
                logger.info("✅ Task scheduler started successfully")
            except Exception as e:
                logger.error(f"Failed to start task scheduler: {e}")
        
        # Check if JobQueue is available
        if application.job_queue:
            application.job_queue.run_once(start_scheduler_callback, when=2)
            logger.info("✅ Task scheduler scheduled to start in 2 seconds")
        else:
            logger.warning("JobQueue not available, starting scheduler directly")
            # Fallback: start scheduler after application starts
            async def delayed_start():
                await asyncio.sleep(3)
                await scheduler.start(application.bot)
            asyncio.create_task(delayed_start())
            
    except Exception as e:
        logger.error(f"Failed to schedule task scheduler: {e}")

    # Run the bot
    application.run_polling(allowed_updates=['message', 'callback_query'])

if __name__ == '__main__':
    main()