"""
Add give money command handler for admin.
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import create_user, get_user, update_user_balance, set_admin_status, is_admin
from config import UserStates, ADMIN_ID

logger = logging.getLogger(__name__)

def check_user_active_tasks(user_id: int) -> bool:
    """Check if user has active tasks (searching or in_progress)"""
    try:
        from database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check for active tasks as customer or executor
        cursor.execute("""
            SELECT COUNT(*) FROM tasks 
            WHERE (customer_id = ? OR executor_id = ?) 
            AND status IN ('searching', 'in_progress')
        """, (user_id, user_id))

        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"Error checking active tasks: {e}")
        return False

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user

    # Create user in database if not exists
    created = create_user(user.id, user.username)

    if created:
        logger.info(f"New user registered: {user.id} (@{user.username})")

    # Check for active tasks to show return to task panel button
    from database import get_user_tasks
    active_statuses = ['searching', 'in_progress']
    customer_tasks = [t for t in get_user_tasks(user.id, as_customer=True) 
                     if t['status'] in active_statuses]
    executor_tasks = [t for t in get_user_tasks(user.id, as_customer=False) 
                     if t['status'] in active_statuses]
    has_active_tasks = bool(customer_tasks or executor_tasks)

    welcome_text = """
🎓 <b>Ласкаво просимо до Rozdum!</b>

Платформа для пошуку виконавців навчальних завдань з автоматичним підбором та безпечними розрахунками.

🔹 <b>Основні переваги:</b>
• Автоматичний підбір виконавців за навичками
• Безпечна система ескроу-платежів  
• Рейтингова система якості
• Анонімне спілкування з виконавцями

🔹 <b>Умови роботи:</b>
• Мінімальна ціна завдання — 25 грн
• VIP-черга: 10 грн (до 100 грн) / 15 грн (понад 100 грн)
• VIP-виконавці мають рейтинг 4.0+
• Комісія — 10% (сплачує виконавець)

💼 <b>Оберіть дію:</b>
    """

    keyboard = [
        [InlineKeyboardButton("📝 Створити Завдання", callback_data="create_task")],
        [InlineKeyboardButton("👤 Мій Профіль", callback_data="my_profile")],
        [InlineKeyboardButton("📋 Мої Завдання", callback_data="my_tasks")],
        [InlineKeyboardButton("ℹ️ Довідка", callback_data="help")]
    ]

    # Add return to task panel button if user has active tasks
    if has_active_tasks:
        keyboard.insert(0, [InlineKeyboardButton("🔄 Повернутися до панелі завдання", callback_data="active_tasks")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # Reset user state for main menu actions
    if data in ['create_task', 'my_profile', 'my_tasks', 'help', 'main_menu']:
        from database import update_user
        update_user(user_id, state=UserStates.NONE, temp_data={})

    if data == "main_menu":
        await start_command(update, context)

    elif data == "help":
        await show_help(update, context)

    elif data == "create_task":
        from handlers.tasks import start_task_creation
        await start_task_creation(update, context)

    elif data == "search_tasks":
        from handlers.tasks import search_available_tasks
        await search_available_tasks(update, context)

    elif data == "my_profile":
        from handlers.profile import show_profile
        await show_profile(update, context)

    elif data == "my_tasks":
        from handlers.tasks import show_my_tasks
        await show_my_tasks(update, context)

    # Handle delete temp file buttons
    elif data.startswith("delete_temp_file_"):
        from handlers.tasks import handle_delete_temp_file
        await handle_delete_temp_file(update, context)

    # Other handlers will be handled by their respective modules through the main.py handler registration
    else:
        await query.answer("❓ Невідома команда")



async def give_money_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Test command to give money to users (available to all)."""
    user_id = update.effective_user.id

    # Parse command arguments
    if not context.args:
        await update.message.reply_text("❌ Використання: /give [сума]")
        return

    try:
        amount = float(context.args[0])
        if amount <= 0:
            await update.message.reply_text("❌ Сума повинна бути більше 0")
            return
    except ValueError:
        await update.message.reply_text("❌ Введіть коректну суму")
        return

    # Get target user (reply to message or current user)
    target_user_id = user_id
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id

    # Give money
    success = update_user_balance(target_user_id, amount)

    if success:
        target_user = get_user(target_user_id)
        text = f"""
✅ <b>Тестове поповнення виконано!</b>

💰 Видано: {amount:.2f} грн
👤 Користувач: {target_user_id}
💳 Новий баланс: {target_user['balance']:.2f} грн
        """
        await update.message.reply_text(text, parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Помилка поповнення балансу")

async def admin_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /code_pas command for admin access."""
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text("❌ Введіть код після команди")
        return

    code = args[0]

    # Check if code is correct
    if code == "09111":
        # Set admin status
        if set_admin_status(user_id, True, 1):
            await update.message.reply_text(
                "✅ <b>Адміністративні права надано!</b>\n\n"
                "Тепер ви маєте доступ до адміністративних функцій у всіх ботах системи Rozdum:\n"
                "• Основний бот (@RozdumBot)\n"
                "• Чат-бот (@Rozdum_ChatBot)\n"
                "• Адмін-бот (@Admin_fartobot)\n\n"
                "Використовуйте адмін-бот для управління системою.",
                parse_mode='HTML'
            )
            logger.info(f"Admin access granted to user {user_id}")
        else:
            await update.message.reply_text("❌ Помилка надання адміністративних прав")
    else:
        await update.message.reply_text("❌ Неправильний код")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help information."""
    help_text = """
<b>📖 Довідка ROZDUM 2.0</b>

<b>🏷️ Категорії завдань:</b>
📊 Презентації - PowerPoint, Keynote, дизайн слайдів
📝 Тексти - копірайтинг, статті, есе, наукові роботи  
🌐 Переклади - англійська, українська, технічні тексти
🎨 Дизайн - логотипи, банери, UI/UX, друк

<b>💰 Фінансова система:</b>
• Комісія платформи: 5%
• Ескроу: кошти заморожуються до завершення
• VIP пропозиції: показ лише топ-виконавцям (4.8+ рейтинг)

<b>⭐ Рейтингова система:</b>
• Початковий рейтинг: 5.0 балів
• Оцінка від 1 до 5 балів
• Впливає на пріоритет отримання завдань

<b>🚖 Система підбору:</b>
• Автоматичний вибір за тегами експертизи
• Враховує рейтинг та завантаженість
• Час на прийняття: 10 хвилин

<b>🔒 Приватність:</b>
• Анонімне спілкування через чат-бот
• Захист персональних даних
• Відсутність публічних каналів

З питань звертайтесь до адміністратора.
    """

    keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    query = update.callback_query
    await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='HTML')