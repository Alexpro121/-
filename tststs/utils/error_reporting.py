"""
Error reporting system for Rozdum Bot
Sends error notifications to admin bot
"""

import logging
import asyncio
import traceback
from typing import Optional
from datetime import datetime
import os
import httpx

logger = logging.getLogger(__name__)

async def report_error_to_admin(error: Exception, context: str = None, user_id: int = None, 
                               task_id: int = None, additional_info: dict = None):
    """Report error to admin bot"""
    try:
        admin_bot_token = os.getenv("ADMIN_BOT_TOKEN")
        admin_user_id = os.getenv("ADMIN_ID")

        if not admin_bot_token or not admin_user_id:
            logger.warning("Admin bot credentials not configured for error reporting")
            return

        # Format error message
        error_message = f"""
🚨 <b>СИСТЕМНА ПОМИЛКА</b>

⏰ <b>Час:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 <b>Контекст:</b> {context or 'Невідомий'}
🆔 <b>Користувач:</b> {user_id or 'Системна помилка'}
📋 <b>Завдання:</b> {task_id or 'Не застосовно'}

❌ <b>Помилка:</b> {type(error).__name__}
💬 <b>Повідомлення:</b> {str(error)}

📄 <b>Трейс:</b>
<pre>{traceback.format_exc()[:1000]}</pre>
        """

        if additional_info:
            error_message += f"\n📊 <b>Додаткова інформація:</b>\n"
            for key, value in additional_info.items():
                error_message += f"• {key}: {value}\n"

        # Send to admin bot
        url = f"https://api.telegram.org/bot{admin_bot_token}/sendMessage"

        data = {
            "chat_id": admin_user_id,
            "text": error_message,
            "parse_mode": "HTML"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=10)

        if response.status_code == 200:
            logger.info("Error reported to admin successfully")
        else:
            logger.warning(f"Failed to report error to admin: {response.status_code}")

    except Exception as report_error:
        logger.error(f"Failed to report error to admin: {report_error}")

async def report_system_stats_to_admin():
    """Send daily system statistics to admin"""
    try:
        admin_bot_token = os.getenv("ADMIN_BOT_TOKEN")
        admin_user_id = os.getenv("ADMIN_ID")

        if not admin_bot_token or not admin_user_id:
            return

        # Import here to avoid circular imports
        from database import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get daily stats
        today = datetime.now().strftime('%Y-%m-%d')

        # New users today
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE DATE(created_at) = ?
        """, (today,))
        new_users = cursor.fetchone()[0]

        # New tasks today
        cursor.execute("""
            SELECT COUNT(*) FROM tasks 
            WHERE DATE(created_at) = ?
        """, (today,))
        new_tasks = cursor.fetchone()[0]

        # Completed tasks today
        cursor.execute("""
            SELECT COUNT(*) FROM tasks 
            WHERE status = 'completed' AND DATE(updated_at) = ?
        """, (today,))
        completed_tasks = cursor.fetchone()[0]

        # Active disputes
        cursor.execute("""
            SELECT COUNT(*) FROM disputes 
            WHERE status = 'open'
        """)
        active_disputes = cursor.fetchone()[0]

        # Total system balance
        cursor.execute("SELECT SUM(balance) FROM users")
        total_balance = cursor.fetchone()[0] or 0

        conn.close()

        # Get active timers count
        from utils.task_timer import get_active_timers_count
        active_timers = get_active_timers_count()

        stats_message = f"""
📊 <b>ЩОДЕННА СТАТИСТИКА СИСТЕМИ</b>

📅 <b>Дата:</b> {today}

👥 <b>Користувачі:</b>
• Нові сьогодні: {new_users}

📋 <b>Завдання:</b>
• Створено сьогодні: {new_tasks}
• Завершено сьогодні: {completed_tasks}
• Активні таймери: {active_timers}

⚠️ <b>Спори:</b>
• Активні: {active_disputes}

💰 <b>Фінанси:</b>
• Загальний баланс системи: {total_balance:.2f} грн

🤖 <b>Боти:</b>
• Основний бот: Працює
• Чат-бот: Працює
• Адмін-бот: Працює
        """

        url = f"https://api.telegram.org/bot{admin_bot_token}/sendMessage"

        data = {
            "chat_id": admin_user_id,
            "text": stats_message,
            "parse_mode": "HTML"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=10)

        if response.status_code == 200:
            logger.info("Daily stats sent to admin successfully")

    except Exception as e:
        logger.error(f"Failed to send daily stats: {e}")

async def report_dispute_to_admin(task_id: int, customer_id: int, executor_id: int, reason: str):
    """Report new dispute to admin bot"""
    try:
        admin_bot_token = os.getenv("ADMIN_BOT_TOKEN")
        admin_user_id = os.getenv("ADMIN_ID")

        if not admin_bot_token or not admin_user_id:
            return

        # Get task details
        from database import get_task, get_user

        task = get_task(task_id)
        customer = get_user(customer_id)
        executor = get_user(executor_id)

        if not task:
            return

        dispute_message = f"""
⚠️ <b>НОВИЙ СПІР ВІДКРИТО!</b>

📋 <b>Завдання:</b> #{task_id}
💰 <b>Ціна:</b> {task['price']} грн
📅 <b>Створено:</b> {task['created_at']}

👥 <b>Учасники спору:</b>
🛒 <b>Замовник:</b> {f"@{customer.get('username')}" if customer and customer.get('username') else f"ID: {customer_id}"}
⚡ <b>Виконавець:</b> {f"@{executor.get('username')}" if executor and executor.get('username') else f"ID: {executor_id}"}

💬 <b>Причина спору:</b>
{reason}

📝 <b>Опис завдання:</b>
{task['description'][:300]}{'...' if len(task['description']) > 300 else ''}

🔧 <b>Необхідні дії:</b>
• Перейдіть до адмін-бота (@Admin_fartobot)
• Перевірте деталі спору
• Перегляньте історію чату
• Прийміть рішення на користь однієї зі сторінристь однієї зі сторін
        """

        url = f"https://api.telegram.org/bot{admin_bot_token}/sendMessage"

        data = {
            "chat_id": admin_user_id,
            "text": dispute_message,
            "parse_mode": "HTML"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=10)

        if response.status_code == 200:
            logger.info(f"Dispute {task_id} reported to admin successfully")

    except Exception as e:
        logger.error(f"Failed to report dispute to admin: {e}")

class ErrorReporter:
    """Decorator class for automatic error reporting"""

    @staticmethod
    def report_on_error(context: str = None):
        """Decorator to automatically report errors"""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Extract user_id from update if available
                    user_id = None
                    if args and hasattr(args[0], 'effective_user'):
                        user_id = args[0].effective_user.id

                    await report_error_to_admin(
                        error=e,
                        context=context or func.__name__,
                        user_id=user_id,
                        additional_info={
                            'function': func.__name__,
                            'args_count': len(args),
                            'kwargs_keys': list(kwargs.keys())
                        }
                    )

                    # Re-raise the error
                    raise e
            return wrapper
        return decorator

def setup_error_reporting():
    """Setup error reporting system"""
    # Schedule daily stats reporting
    import asyncio

    async def daily_stats_scheduler():
        while True:
            # Wait until next day at 9:00 AM
            now = datetime.now()
            next_report = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if next_report <= now:
                next_report = next_report.replace(day=next_report.day + 1)

            sleep_time = (next_report - now).total_seconds()
            await asyncio.sleep(sleep_time)

            await report_system_stats_to_admin()

    # Start scheduler
    asyncio.create_task(daily_stats_scheduler())