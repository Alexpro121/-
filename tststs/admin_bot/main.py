"""
Rozdum Admin Bot - @Admin_fartobot
Handles disputes, arbitration, and administrative functions
"""

import os
import sys
import logging
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import json

# Add parent directory to path for database access
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
from io import BytesIO
import httpx

# Kyiv timezone
KYIV_TZ = timezone(timedelta(hours=2))

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration - use only environment variables
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
if not ADMIN_BOT_TOKEN:
    raise ValueError("ADMIN_BOT_TOKEN not found in environment variables")

admin_id_str = os.getenv("ADMIN_ID")
if admin_id_str:
    try:
        ADMIN_USER_ID = int(admin_id_str)
    except ValueError:
        ADMIN_USER_ID = 5857065034  # Default to @fezerstop
else:
    ADMIN_USER_ID = 5857065034  # Default to @fezerstop

# Context storage for multi-step operations
user_contexts = {}


def get_db_connection():
    """Get database connection with row factory."""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'rozdum.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    # @fezerstop is the highest level admin (Level 5) - both ID and username recognition
    if user_id == 5857065034:  # @fezerstop ID
        return True

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check by user_id
        cursor.execute("SELECT is_admin FROM users WHERE user_id = ?",
                       (user_id, ))
        result = cursor.fetchone()
        if result and result['is_admin'] == 1:
            conn.close()
            return True

        # Check by username for @fezerstop
        cursor.execute(
            "SELECT is_admin FROM users WHERE username = ? AND is_admin = 1",
            ("fezerstop", ))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return user_id == 5857065034


def set_admin_status(user_id: int,
                     is_admin_status: bool = True,
                     admin_level: int = 1) -> bool:
    """Set admin status for user."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?",
                       (user_id, ))
        if not cursor.fetchone():
            # Create user if doesn't exist
            cursor.execute(
                """
                INSERT INTO users (user_id, username, balance, rating, is_executor, is_admin, admin_level)
                VALUES (?, ?, 0.0, 5.0, 0, ?, ?)
            """, (user_id, None, 1 if is_admin_status else 0, admin_level))
        else:
            # Update existing user
            cursor.execute(
                """
                UPDATE users SET is_admin = ?, admin_level = ?
                WHERE user_id = ?
            """, (1 if is_admin_status else 0, admin_level, user_id))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error setting admin status: {e}")
        return False


def get_user_info(user_id: int) -> Optional[Dict]:
    """Get detailed user information."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_id, username, balance, rating, is_executor, is_admin, 
                   created_at, completed_tasks, frozen_balance, admin_level
            FROM users WHERE user_id = ?
        """, (user_id, ))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        return None


def search_users(query: str) -> List[Dict]:
    """Search users by username or ID."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if query.isdigit():
            cursor.execute(
                """
                SELECT user_id, username, balance, rating, is_executor, is_admin
                FROM users WHERE user_id = ?
            """, (int(query), ))
        else:
            cursor.execute(
                """
                SELECT user_id, username, balance, rating, is_executor, is_admin
                FROM users WHERE username LIKE ?
            """, (f"%{query}%", ))

        results = cursor.fetchall()
        conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return []


def get_dispute_details(task_id: int) -> Optional[Dict]:
    """Get dispute details for a task"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT d.*, t.customer_id, t.executor_id, t.description, t.price
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            WHERE d.task_id = ?
        """, (task_id, ))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        logger.error(f"Error getting dispute details: {e}")
        return None


def get_kyiv_time() -> str:
    """Get current time in Kyiv timezone."""
    return datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")


async def safe_edit_message(query,
                            text: str,
                            reply_markup=None,
                            parse_mode='HTML'):
    """Safely edit message with proper error handling for refresh buttons."""
    try:
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode=parse_mode)
    except Exception as edit_error:
        if "Message is not modified" in str(
                edit_error) or "exactly the same" in str(edit_error):
            await query.answer("🔄 Дані актуальні")
        elif "Bad Request" in str(edit_error):
            await query.answer("❌ Помилка оновлення")
        else:
            logger.error(f"Error editing message: {edit_error}")
            await query.answer("❌ Технічна помилка")


def get_admin_level(user_id: int) -> int:
    """Get admin level for user."""
    # @fezerstop is the highest level admin (Level 5)
    if user_id == 5857065034:  # @fezerstop
        return 5

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT admin_level FROM users WHERE user_id = ?",
                       (user_id, ))
        result = cursor.fetchone()
        conn.close()

        return result['admin_level'] if result and result['admin_level'] else 0

    except Exception as e:
        logger.error(f"Error getting admin level: {e}")
        return 0


def can_manage_user(admin_id: int, target_id: int) -> bool:
    """Check if admin can manage target user."""
    if admin_id == target_id:
        return False  # Can't manage yourself

    admin_level = get_admin_level(admin_id)
    target_level = get_admin_level(target_id)

    return admin_level > target_level


def update_user_balance(user_id: int,
                        amount: float,
                        operation: str = "add") -> bool:
    """Update user balance (add or subtract)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if operation == "add":
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id))
        elif operation == "subtract":
            cursor.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (amount, user_id))
        elif operation == "set":
            cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?",
                           (amount, user_id))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error updating balance: {e}")
        return False


def unfreeze_user_balance(user_id: int) -> bool:
    """Unfreeze user's frozen balance."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE users 
            SET balance = balance + frozen_balance, frozen_balance = 0 
            WHERE user_id = ?
        """, (user_id, ))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error unfreezing balance: {e}")
        return False


def get_user_complete_history(user_id: int) -> Dict:
    """Get complete user history including all activities."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        history = {
            'tasks_as_customer': [],
            'tasks_as_executor': [],
            'reviews_given': [],
            'reviews_received': [],
            'chat_messages': [],
            'disputes': []
        }

        # Tasks as customer
        cursor.execute(
            """
            SELECT task_id, description, price, status, created_at, executor_id
            FROM tasks WHERE customer_id = ?
            ORDER BY created_at DESC
        """, (user_id, ))
        history['tasks_as_customer'] = cursor.fetchall()

        # Tasks as executor
        cursor.execute(
            """
            SELECT task_id, description, price, status, created_at, customer_id
            FROM tasks WHERE executor_id = ?
            ORDER BY created_at DESC
        """, (user_id, ))
        history['tasks_as_executor'] = cursor.fetchall()

        # Reviews given
        cursor.execute(
            """
            SELECT r.*, t.description as task_description
            FROM reviews r
            JOIN tasks t ON r.task_id = t.task_id
            WHERE r.reviewer_id = ?
            ORDER BY r.created_at DESC
        """, (user_id, ))
        history['reviews_given'] = cursor.fetchall()

        # Reviews received
        cursor.execute(
            """
            SELECT r.*, t.description as task_description
            FROM reviews r
            JOIN tasks t ON r.task_id = t.task_id
            WHERE r.reviewed_id = ?
            ORDER BY r.created_at DESC
        """, (user_id, ))
        history['reviews_received'] = cursor.fetchall()

        # Chat messages
        cursor.execute(
            """
            SELECT chat_code, message_text, message_type, created_at, sender_role
            FROM chat_messages 
            WHERE sender_id = ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (user_id, ))
        history['chat_messages'] = cursor.fetchall()

        # Disputes
        cursor.execute(
            """
            SELECT d.*, t.description as task_description
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            WHERE d.customer_id = ? OR d.executor_id = ?
            ORDER BY d.created_at DESC
        """, (user_id, user_id))
        history['disputes'] = cursor.fetchall()

        conn.close()
        return history

    except Exception as e:
        logger.error(f"Error getting user history: {e}")
        return {}


async def start_command(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ Доступ заборонено. Цей бот тільки для адміністратора.")
        return

    welcome_text = f"""
🛡 <b>ROZDUM ADMIN PANEL</b>
🕐 {get_kyiv_time()}

Повна адміністративна панель керування системою

<b>Основні функції:</b>
• Управління користувачами та адміністраторами
• Вирішення спорів та конфліктів  
• Моніторинг системи та статистика
• Фінансові операції та баланси
• Управління завданнями та чатами
• Системні налаштування та alerts

💼 Централізоване управління всією платформою Rozdum
    """

    keyboard = [[
        InlineKeyboardButton("⚠️ Спори", callback_data="active_disputes"),
        InlineKeyboardButton("👥 Користувачі", callback_data="user_management")
    ],
                [
                    InlineKeyboardButton("📊 Статистика",
                                         callback_data="system_stats"),
                    InlineKeyboardButton("💰 Фінанси",
                                         callback_data="financial_operations")
                ],
                [
                    InlineKeyboardButton("📋 Завдання",
                                         callback_data="task_management"),
                    InlineKeyboardButton("⚙️ Налаштування",
                                         callback_data="admin_settings")
                ],
                [
                    InlineKeyboardButton("🔔 Сповіщення",
                                         callback_data="system_alerts"),
                    InlineKeyboardButton("📊 Детальна статистика",
                                         callback_data="detailed_stats")
                ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text,
                                    reply_markup=reply_markup,
                                    parse_mode='HTML')


async def code_pas_command(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /code_pas command for admin access."""
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text("❌ Введіть код після команди")
        return

    if args[0] == "09111":
        success = set_admin_status(user_id, True, 1)
        if success:
            await update.message.reply_text("✅ Адміністративні права надано!")
            # Start admin interface
            await start_command(update, context)
        else:
            await update.message.reply_text("❌ Помилка надання прав")
    else:
        await update.message.reply_text("❌ Неправильний код")


async def adminssss_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /adminssss command - redirect to main admin panel."""
    await start_command(update, context)


async def disputes_command(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show active disputes"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Доступ заборонено")
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.dispute_id, d.task_id, d.reason, d.created_at, t.price
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            WHERE d.status = 'open'
            ORDER BY d.created_at DESC
        """)
        disputes = cursor.fetchall()
        conn.close()

        if not disputes:
            await update.message.reply_text("✅ Активних спорів немає")
            return

        text = f"⚠️ <b>АКТИВНІ СПОРИ</b>\n🕐 {get_kyiv_time()}\n\n"
        keyboard = []

        for dispute in disputes:
            text += f"🆔 Спір #{dispute['dispute_id']}\n"
            text += f"📋 Завдання: {dispute['task_id']}\n"
            text += f"💰 Сума: {dispute['price']:.2f} грн\n"
            text += f"📝 Причина: {dispute['reason'][:50]}...\n"
            text += f"📅 {dispute['created_at'][:10]}\n\n"

            keyboard.append([
                InlineKeyboardButton(
                    f"📋 Спір #{dispute['dispute_id']}",
                    callback_data=f"dispute_details_{dispute['dispute_id']}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text,
                                        reply_markup=reply_markup,
                                        parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing disputes: {e}")
        await update.message.reply_text("❌ Помилка завантаження спорів")


async def handle_callback(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries"""
    if not update.callback_query or not update.callback_query.from_user:
        return

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if not data:
        await query.edit_message_text("❌ Невірні дані")
        return

    if not is_admin(user_id):
        await query.edit_message_text("❌ Доступ заборонено")
        return

    try:
        if data == "active_disputes":
            try:
                from admin_bot.dispute_handlers import show_active_disputes_list
                await show_active_disputes_list(query, context)
            except ImportError:
                # Fallback to built-in dispute handler
                await show_active_disputes(query, context)
        elif data == "user_management":
            await show_user_management(query, context)
        elif data == "system_stats":
            await show_system_stats(query, context)
        elif data == "detailed_stats":
            await show_detailed_stats(query, context)
        elif data == "financial_operations":
            await show_financial_operations(query, context)
        elif data.startswith("dispute_details_") or data.startswith("view_dispute_"):
            dispute_id = int(data.split("_")[2])
            try:
                from admin_bot.dispute_handlers import show_dispute_details
                await show_dispute_details(query, dispute_id, context)
            except ImportError:
                # Fallback to error message
                await query.edit_message_text("❌ Помилка завантаження деталей спору")
        elif data.startswith("resolve_dispute_"):
            parts = data.split("_")
            dispute_id = int(parts[2])
            resolution = parts[3]
            try:
                from admin_bot.dispute_handlers import resolve_dispute_handler
                await resolve_dispute_handler(query, dispute_id, resolution, context)
            except ImportError:
                # Use the built-in resolve_dispute function
                await resolve_dispute(query, dispute_id, resolution, context)
        elif data.startswith("user_info_"):
            user_id_target = int(data.split("_")[2])
            await show_detailed_user_info(query, user_id_target, context)
        elif data == "user_search":
            await show_user_search(query, context)
        elif data == "top_users":
            await show_top_users(query, context)
        elif data == "recent_users":
            await show_recent_users(query, context)
        elif data == "back_to_main":
            await start_command_callback(query, context)
        elif data == "financial_stats":
            await show_financial_stats(query, context)
        elif data == "transactions":
            await show_transactions(query, context)
        elif data.startswith("chat_history_"):
            task_id = int(data.split("_")[2])
            await send_chat_history(query, task_id, context)
        elif data == "task_management":
            await show_task_management(query, context)
        elif data == "system_alerts":
            await show_system_alerts(query, context)
        elif data == "admin_settings":
            await show_admin_settings(query, context)
        elif data.startswith("user_action_"):
            parts = data.split("_")
            action = parts[2]
            user_id_target = int(parts[3])
            await handle_user_action(query, action, user_id_target, context)
        elif data == "list_admins":
            await show_list_admins(query, context)
        elif data == "active_tasks":
            await show_active_tasks(query, context)
        elif data == "problem_tasks":
            await show_problem_tasks(query, context)
        elif data.startswith("user_history_"):
            user_id_target = int(data.split("_")[2])
            await show_user_complete_history(query, user_id_target, context)
        elif data.startswith("user_actions_"):
            user_id_target = int(data.split("_")[2])
            await show_user_action_menu(query, user_id_target, context)
        elif data.startswith("balance_ops_"):
            user_id_target = int(data.split("_")[2])
            await show_balance_operations(query, user_id_target, context)
        elif data.startswith("admin_level_"):
            parts = data.split("_")
            user_id_target = int(parts[2])
            level = int(parts[3])
            await handle_admin_level_change(query, user_id_target, level,
                                            context)
        elif data.startswith("remove_admin_"):
            user_id_target = int(data.split("_")[2])
            await handle_remove_admin(query, user_id_target, context)
        elif data.startswith("add_balance_"):
            user_id_target = int(data.split("_")[2])
            await initiate_balance_operation(query, user_id_target, "add",
                                             context)
        elif data.startswith("remove_balance_"):
            user_id_target = int(data.split("_")[2])
            await initiate_balance_operation(query, user_id_target, "subtract",
                                             context)
        elif data.startswith("unfreeze_balance_"):
            user_id_target = int(data.split("_")[2])
            await handle_unfreeze_balance(query, user_id_target, context)
        elif data.startswith("block_user_"):
            user_id_target = int(data.split("_")[2])
            await handle_block_user(query, user_id_target, context)
        elif data.startswith("task_details_"):
            task_id = int(data.split("_")[2])
            await show_task_details(query, task_id, context)
        elif data.startswith("user_tasks_"):
            user_id_target = int(data.split("_")[2])
            await show_user_tasks(query, user_id_target, context)
        elif data.startswith("user_reviews_"):
            user_id_target = int(data.split("_")[2])
            await show_user_reviews(query, user_id_target, context)
        elif data == "system_maintenance":
            await show_system_maintenance(query, context)
        elif data == "broadcast_message":
            await initiate_broadcast(query, context)
        elif data == "link_management":
            await show_link_management(query, context)
        elif data.startswith("link_"):
            await handle_link_callback(query, data, context)
        elif data == "flvs_management":
            await show_flvs_management(query, context)
        elif data.startswith("flvs_"):
            await handle_flvs_callback(query, data, context)
        elif data == "security_management":
            await show_security_management(query, context)
        elif data.startswith("chat_files_"):
            parts = data.split("_")
            task_id = int(parts[2])
            page = int(parts[3])
            await show_chat_files(query, task_id, page, context)
        elif data == "cleanup_old_data":
            await handle_cleanup_old_data(query, context)
        elif data == "check_database":
            await handle_check_database(query, context)
        elif data == "database_stats":
            await handle_database_stats(query, context)
        else:
            await query.edit_message_text("❌ Невідома команда")

    except Exception as e:
        logger.error(f"Error handling callback {data}: {e}")
        await query.edit_message_text(f"❌ Помилка обробки команди: {str(e)}")


async def show_active_disputes(query, context) -> None:
    """Show active disputes in callback"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.dispute_id, d.task_id, d.reason, d.created_at, t.price, t.description
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            WHERE d.status = 'open'
            ORDER BY d.created_at DESC
        """)
        disputes = cursor.fetchall()
        conn.close()

        if not disputes:
            text = f"✅ <b>АКТИВНИХ СПОРІВ НЕМАЄ</b>\n🕐 {get_kyiv_time()}"
            keyboard = [[
                InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text,
                                          reply_markup=reply_markup,
                                          parse_mode='HTML')
            return

        text = f"⚠️ <b>АКТИВНІ СПОРИ ({len(disputes)})</b>\n🕐 {get_kyiv_time()}\n\n"
        keyboard = []

        for dispute in disputes:
            text += f"🆔 Спір #{dispute['dispute_id']}\n"
            text += f"📋 Завдання: {dispute['task_id']}\n"
            text += f"💰 Сума: {dispute['price']:.2f} грн\n"
            text += f"📝 Причина: {dispute['reason'][:30]}...\n\n"

            keyboard.append([
                InlineKeyboardButton(
                    f"📋 Деталі спору #{dispute['dispute_id']}",
                    callback_data=f"dispute_details_{dispute['dispute_id']}")
            ])

        keyboard.append([
            InlineKeyboardButton("🔄 Оновити", callback_data="active_disputes")
        ])
        keyboard.append(
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing active disputes: {e}")
        await query.edit_message_text("❌ Помилка завантаження спорів")


async def show_dispute_details(query, dispute_id: int, context) -> None:
    """Show detailed dispute information"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT d.*, t.customer_id, t.executor_id, t.description, t.price,
                   c.username as customer_name, e.username as executor_name
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            LEFT JOIN users c ON t.customer_id = c.user_id
            LEFT JOIN users e ON t.executor_id = e.user_id
            WHERE d.dispute_id = ?
        """, (dispute_id, ))
        dispute = cursor.fetchone()
        conn.close()

        if not dispute:
            await query.edit_message_text("❌ Спір не знайдено")
            return

        customer_name = dispute[
            'customer_name'] or f"ID:{dispute['customer_id']}"
        executor_name = dispute[
            'executor_name'] or f"ID:{dispute['executor_id']}"

        text = f"""
⚠️ <b>ДЕТАЛІ СПОРУ #{dispute_id}</b>
🕐 {get_kyiv_time()}

📋 <b>Завдання:</b> {dispute['task_id']}
💰 <b>Сума:</b> {dispute['price']:.2f} грн
📅 <b>Дата:</b> {dispute['created_at'][:10]}

👤 <b>Замовник:</b> {customer_name}
🔧 <b>Виконавець:</b> {executor_name}

📝 <b>Опис завдання:</b>
{dispute['description'][:200]}...

⚠️ <b>Причина спору:</b>
{dispute['reason']}

<b>Рішення:</b>
        """

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ На користь замовника",
                    callback_data=f"resolve_dispute_{dispute_id}_customer")
            ],
            [
                InlineKeyboardButton(
                    "🔧 На користь виконавця",
                    callback_data=f"resolve_dispute_{dispute_id}_executor")
            ],
            [
                InlineKeyboardButton(
                    "📄 Історія чату",
                    callback_data=f"chat_history_{dispute['task_id']}")
            ],
            [
                InlineKeyboardButton(
                    "👤 Інфо замовника",
                    callback_data=f"user_info_{dispute['customer_id']}")
            ],
            [
                InlineKeyboardButton(
                    "🔧 Інфо виконавця",
                    callback_data=f"user_info_{dispute['executor_id']}")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="active_disputes")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing dispute details: {e}")
        await query.edit_message_text("❌ Помилка завантаження деталей спору")


async def resolve_dispute(query, dispute_id: int, resolution: str,
                          context) -> None:
    """Resolve dispute in favor of customer or executor"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get dispute details
        cursor.execute(
            """
            SELECT d.*, t.customer_id, t.executor_id, t.price
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            WHERE d.dispute_id = ?
        """, (dispute_id, ))
        dispute = cursor.fetchone()

        if not dispute:
            await query.edit_message_text("❌ Спір не знайдено")
            return

        # Update dispute status
        cursor.execute(
            """
            UPDATE disputes SET status = 'resolved', admin_decision = ?, resolved_at = datetime('now')
            WHERE dispute_id = ?
        """, (resolution, dispute_id))

        # Handle money transfer
        if resolution == "customer":
            # Return money to customer
            cursor.execute(
                """
                UPDATE users SET frozen_balance = frozen_balance - ?, balance = balance + ?
                WHERE user_id = ?
            """, (dispute['price'], dispute['price'], dispute['customer_id']))

            cursor.execute(
                """
                UPDATE tasks SET status = 'cancelled'
                WHERE task_id = ?
            """, (dispute['task_id'], ))

        elif resolution == "executor":
            # Pay executor
            cursor.execute(
                """
                UPDATE users SET frozen_balance = frozen_balance - ?
                WHERE user_id = ?
            """, (dispute['price'], dispute['customer_id']))

            cursor.execute("""
                UPDATE users SET balance = balance + ?
                WHERE user_id = ?
            """, (dispute['price'] * 0.9,
                  dispute['executor_id']))  # 10% commission

            cursor.execute(
                """
                UPDATE tasks SET status = 'completed'
                WHERE task_id = ?
            """, (dispute['task_id'], ))

        conn.commit()
        conn.close()

        text = f"""
✅ <b>СПІР ВИРІШЕНО</b>
🕐 {get_kyiv_time()}

🆔 Спір #{dispute_id}
📋 Завдання: {dispute['task_id']}
💰 Сума: {dispute['price']:.2f} грн
🏆 Рішення на користь: {'замовника' if resolution == 'customer' else 'виконавця'}
        """

        keyboard = [[
            InlineKeyboardButton("⚠️ Переглянути інші спори",
                                 callback_data="active_disputes")
        ],
                    [
                        InlineKeyboardButton("🔙 Головне меню",
                                             callback_data="back_to_main")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error resolving dispute: {e}")
        await query.edit_message_text("❌ Помилка вирішення спору")


async def show_user_management(query, context) -> None:
    """Show user management interface"""
    text = f"""
👥 <b>УПРАВЛІННЯ КОРИСТУВАЧАМИ</b>
🕐 {get_kyiv_time()}

Виберіть дію:
    """

    keyboard = [[
        InlineKeyboardButton("🔍 Пошук користувача",
                             callback_data="user_search")
    ], [InlineKeyboardButton("📊 Топ користувачі", callback_data="top_users")],
                [
                    InlineKeyboardButton("🆕 Нові користувачі",
                                         callback_data="recent_users")
                ],
                [
                    InlineKeyboardButton("👑 Список адмінів",
                                         callback_data="list_admins")
                ],
                [
                    InlineKeyboardButton("🔙 Назад",
                                         callback_data="back_to_main")
                ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def show_system_stats(query, context) -> None:
    """Show comprehensive system statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Total users
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        # Active users (with balance or tasks)
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE balance > 0 OR completed_tasks > 0"
        )
        active_users = cursor.fetchone()[0]

        # Total tasks
        cursor.execute("SELECT COUNT(*) FROM tasks")
        total_tasks = cursor.fetchone()[0]

        # Task statuses
        cursor.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
        task_statuses = dict(cursor.fetchall())

        # Active disputes
        cursor.execute("SELECT COUNT(*) FROM disputes WHERE status = 'open'")
        active_disputes = cursor.fetchone()[0]

        # Total balance
        cursor.execute("SELECT SUM(balance) FROM users")
        total_balance = cursor.fetchone()[0] or 0

        # Total frozen balance
        cursor.execute("SELECT SUM(frozen_balance) FROM users")
        total_frozen = cursor.fetchone()[0] or 0

        conn.close()

        text = f"""
📊 <b>СТАТИСТИКА СИСТЕМИ</b>
🕐 {get_kyiv_time()}

👥 <b>Користувачі:</b>
• Всього: {total_users}
• Активні: {active_users}

📋 <b>Завдання:</b>
• Всього: {total_tasks}
• В пошуку: {task_statuses.get('searching', 0)}
• В роботі: {task_statuses.get('in_progress', 0)}
• Завершено: {task_statuses.get('completed', 0)}
• Скасовано: {task_statuses.get('cancelled', 0)}

⚠️ <b>Спори:</b> {active_disputes}

💰 <b>Фінанси:</b>
• Загальний баланс: {total_balance:.2f} грн
• Заморожено: {total_frozen:.2f} грн
• Вільно: {(total_balance - total_frozen):.2f} грн
        """

        keyboard = [[
            InlineKeyboardButton("📊 Детальна статистика",
                                 callback_data="detailed_stats")
        ], [InlineKeyboardButton("🔄 Оновити", callback_data="system_stats")
            ], [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing system stats: {e}")
        await query.edit_message_text("❌ Помилка завантаження статистики")


async def show_detailed_stats(query, context) -> None:
    """Show detailed system statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # User statistics
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_executor = 1")
        total_executors = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        total_admins = cursor.fetchone()[0]

        # Recent activity (last 7 days)
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE created_at > datetime('now', '-7 days')"
        )
        new_users_week = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM tasks WHERE created_at > datetime('now', '-7 days')"
        )
        new_tasks_week = cursor.fetchone()[0]

        # Financial statistics
        cursor.execute("SELECT AVG(balance) FROM users WHERE balance > 0")
        avg_balance = cursor.fetchone()[0] or 0

        cursor.execute("SELECT MAX(balance) FROM users")
        max_balance = cursor.fetchone()[0] or 0

        # Top categories
        cursor.execute(
            "SELECT category, COUNT(*) FROM tasks GROUP BY category ORDER BY COUNT(*) DESC LIMIT 3"
        )
        top_categories = cursor.fetchall()

        conn.close()

        text = f"""
📊 <b>ДЕТАЛЬНА СТАТИСТИКА</b>
🕐 {get_kyiv_time()}

👥 <b>Деталі користувачів:</b>
• Виконавці: {total_executors}
• Адміністратори: {total_admins}

📈 <b>Активність (7 днів):</b>
• Нові користувачі: {new_users_week}
• Нові завдання: {new_tasks_week}

💰 <b>Фінансова статистика:</b>
• Середній баланс: {avg_balance:.2f} грн
• Максимальний баланс: {max_balance:.2f} грн

📋 <b>Топ категорії:</b>
        """

        for i, (category, count) in enumerate(top_categories, 1):
            text += f"{i}. {category}: {count} завдань\n"

        keyboard = [[
            InlineKeyboardButton("🔄 Оновити", callback_data="detailed_stats")
        ],
                    [
                        InlineKeyboardButton("📊 Базова статистика",
                                             callback_data="system_stats")
                    ],
                    [
                        InlineKeyboardButton("🔙 Назад",
                                             callback_data="back_to_main")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing detailed stats: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження детальної статистики")


async def show_financial_operations(query, context) -> None:
    """Show financial operations panel"""
    text = f"""
💰 <b>ФІНАНСОВІ ОПЕРАЦІЇ</b>
🕐 {get_kyiv_time()}

Виберіть дію:
    """

    keyboard = [[
        InlineKeyboardButton("📊 Фінансова статистика",
                             callback_data="financial_stats")
    ], [InlineKeyboardButton("💳 Транзакції", callback_data="transactions")],
                [
                    InlineKeyboardButton("💰 Операції з балансом",
                                         callback_data="balance_management")
                ],
                [
                    InlineKeyboardButton("🔙 Назад",
                                         callback_data="back_to_main")
                ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def show_detailed_user_info(query, user_id: int, context) -> None:
    """Show detailed information about specific user"""
    user_info = get_user_info(user_id)
    if not user_info:
        await query.edit_message_text("❌ Користувач не знайдений")
        return

    username_display = user_info['username'] or f"ID:{user_info['user_id']}"
    admin_level = user_info.get('admin_level', 0)

    text = f"""
👤 <b>ІНФОРМАЦІЯ ПРО КОРИСТУВАЧА</b>
🕐 {get_kyiv_time()}

🆔 <b>ID:</b> {user_info['user_id']}
👤 <b>Ім'я:</b> {username_display}
💰 <b>Баланс:</b> {user_info['balance']:.2f} грн
🔒 <b>Заморожено:</b> {user_info.get('frozen_balance', 0):.2f} грн
⭐ <b>Рейтинг:</b> {user_info['rating']:.1f}
🔧 <b>Виконавець:</b> {'Так' if user_info['is_executor'] else 'Ні'}
🛡 <b>Адмін:</b> {'Так (рівень ' + str(admin_level) + ')' if user_info['is_admin'] else 'Ні'}
📅 <b>Реєстрація:</b> {user_info['created_at'][:10]}
✅ <b>Завершено завдань:</b> {user_info.get('completed_tasks', 0)}
    """

    keyboard = [
        [
            InlineKeyboardButton("⚙️ Дії з користувачем",
                                 callback_data=f"user_actions_{user_id}")
        ],
        [
            InlineKeyboardButton("📋 Завдання користувача",
                                 callback_data=f"user_tasks_{user_id}")
        ],
        [
            InlineKeyboardButton("⭐ Відгуки користувача",
                                 callback_data=f"user_reviews_{user_id}")
        ],
        [
            InlineKeyboardButton("📊 Повна історія",
                                 callback_data=f"user_history_{user_id}")
        ],
        [
            InlineKeyboardButton("🔙 Назад до пошуку",
                                 callback_data="user_search")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def start_command_callback(query, context) -> None:
    """Handle start command as callback"""
    welcome_text = f"""
🛡 <b>ROZDUM ADMIN PANEL</b>
🕐 {get_kyiv_time()}

Повна адміністративна панель керування системою

<b>Основні функції:</b>
• Управління користувачами та адміністраторами
• Вирішення спорів та конфліктів
• Моніторинг системи та статистика
• Фінансові операції та баланси
• Управління завданнями та чатами
• Системні налаштування та alerts

💼 Централізоване управління всією платформою Rozdum
    """

    keyboard = [[
        InlineKeyboardButton("⚠️ Спори", callback_data="active_disputes"),
        InlineKeyboardButton("👥 Користувачі", callback_data="user_management")
    ],
                [
                    InlineKeyboardButton("📊 Статистика",
                                         callback_data="system_stats"),
                    InlineKeyboardButton("💰 Фінанси",
                                         callback_data="financial_operations")
                ],
                [
                    InlineKeyboardButton("📋 Завдання",
                                         callback_data="task_management"),
                    InlineKeyboardButton("🔗 Посилання",
                                         callback_data="link_management")
                ],
                [
                    InlineKeyboardButton("🛡️ FLVS Система",
                                         callback_data="flvs_management"),
                    InlineKeyboardButton("🔐 Безпека",
                                         callback_data="security_management")
                ],
                [
                    InlineKeyboardButton("⚙️ Налаштування",
                                         callback_data="admin_settings"),
                    InlineKeyboardButton("🔔 Сповіщення",
                                         callback_data="system_alerts")
                ],
                [
                    InlineKeyboardButton("📊 Детальна статистика",
                                         callback_data="detailed_stats")
                ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(welcome_text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def show_user_search(query, context) -> None:
    """Show user search interface"""
    text = f"""
🔍 <b>ПОШУК КОРИСТУВАЧІВ</b>
🕐 {get_kyiv_time()}

Надішліть ID користувача або частину username для пошуку.

Приклади:
• 123456789 (пошук за ID)
• @username (пошук за username)
• username (пошук за частиною імені)
    """

    keyboard = [
        [InlineKeyboardButton("📊 Топ користувачі", callback_data="top_users")],
        [
            InlineKeyboardButton("🆕 Нові користувачі",
                                 callback_data="recent_users")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="user_management")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def show_link_management(query, context) -> None:
    """Show link verification management interface"""
    try:
        from database import get_db_connection, get_link_analysis_stats, get_blocked_domains, get_trusted_domains

        # Get statistics
        stats = get_link_analysis_stats()
        blocked_domains = get_blocked_domains()
        trusted_domains = get_trusted_domains()

        text = f"""
🔗 <b>УПРАВЛІННЯ ПОСИЛАННЯМИ</b>
🕐 {get_kyiv_time()}

📊 <b>СТАТИСТИКА АНАЛІЗУ ПОСИЛАНЬ:</b>
• Перевірено посилань: {stats.get('total_analyzed', 0)}
• Безпечних: {stats.get('safe_links', 0)}
• Небезпечних: {stats.get('unsafe_links', 0)}
• Заблокованих доменів: {len(blocked_domains)}
• Довірених доменів: {len(trusted_domains)}

📈 <b>РІВЕНЬ БЕЗПЕКИ:</b>
{calculate_safety_level(stats)}

⚙️ <b>НАЛАШТУВАННЯ:</b>
• Автоматична перевірка посилань: ✅ Увімкнено
• Блокування підозрілих посилань: ✅ Увімкнено
• Логування всіх перевірок: ✅ Увімкнено
        """

        keyboard = [
            [
                InlineKeyboardButton("🚫 Заблоковані домени",
                                     callback_data="link_blocked_domains")
            ],
            [
                InlineKeyboardButton("✅ Довірені домени",
                                     callback_data="link_trusted_domains")
            ],
            [
                InlineKeyboardButton("📊 Детальна статистика",
                                     callback_data="link_detailed_stats")
            ],
            [
                InlineKeyboardButton("⚙️ Налаштування",
                                     callback_data="link_settings")
            ],
            [
                InlineKeyboardButton("🔄 Очистити статистику",
                                     callback_data="link_clear_stats")
            ], [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        await query.edit_message_text(f"❌ Помилка завантаження даних: {str(e)}"
                                      )


def calculate_safety_level(stats):
    """Calculate safety level based on statistics"""
    total = stats.get('total_analyzed', 0)
    if total == 0:
        return "🔍 Аналіз не проводився"

    safe_ratio = stats.get('safe_links', 0) / total
    if safe_ratio >= 0.9:
        return "🟢 Високий рівень безпеки"
    elif safe_ratio >= 0.7:
        return "🟡 Середній рівень безпеки"
    else:
        return "🔴 Низький рівень безпеки"


async def handle_link_callback(query, data, context):
    """Handle link management callbacks"""
    try:
        if data == "link_blocked_domains":
            await show_blocked_domains(query, context)
        elif data == "link_trusted_domains":
            await show_trusted_domains(query, context)
        elif data == "link_detailed_stats":
            await show_detailed_link_stats(query, context)
        elif data == "link_settings":
            await show_link_settings(query, context)
        elif data == "link_clear_stats":
            await handle_clear_link_stats(query, context)
        elif data.startswith("link_unblock_"):
            domain = data.replace("link_unblock_", "")
            await handle_unblock_domain(query, domain, context)
        elif data.startswith("link_untrust_"):
            domain = data.replace("link_untrust_", "")
            await handle_untrust_domain(query, domain, context)
        elif data == "link_confirm_clear":
            await handle_confirm_clear_stats(query, context)

    except Exception as e:
        await query.edit_message_text(f"❌ Помилка: {str(e)}")


async def show_blocked_domains(query, context):
    """Show blocked domains list"""
    from database import get_blocked_domains

    blocked_domains = get_blocked_domains()

    if not blocked_domains:
        text = """
🚫 <b>ЗАБЛОКОВАНІ ДОМЕНИ</b>

📋 Список заблокованих доменів порожній.
Система автоматично додає підозрілі домени до цього списку.
        """
        keyboard = [[
            InlineKeyboardButton("🔙 Назад", callback_data="link_management")
        ]]
    else:
        text = f"""
🚫 <b>ЗАБЛОКОВАНІ ДОМЕНИ</b>
🕐 {get_kyiv_time()}

📋 Всього заблокованих доменів: {len(blocked_domains)}

"""

        for domain_info in blocked_domains[:10]:  # Show first 10
            domain = domain_info['domain']
            reason = domain_info['reason'][:50] + "..." if len(
                domain_info['reason']) > 50 else domain_info['reason']
            text += f"🚫 <code>{domain}</code>\n   <i>{reason}</i>\n\n"

        if len(blocked_domains) > 10:
            text += f"... і ще {len(blocked_domains) - 10} доменів"

        keyboard = [[
            InlineKeyboardButton("🔙 Назад", callback_data="link_management")
        ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def show_trusted_domains(query, context):
    """Show trusted domains list"""
    from database import get_trusted_domains

    trusted_domains = get_trusted_domains()

    if not trusted_domains:
        text = """
✅ <b>ДОВІРЕНІ ДОМЕНИ</b>

📋 Список довірених доменів порожній.
Ви можете додати домени, яким довіряєте, для швидшої перевірки.
        """
    else:
        text = f"""
✅ <b>ДОВІРЕНІ ДОМЕНИ</b>
🕐 {get_kyiv_time()}

📋 Всього довірених доменів: {len(trusted_domains)}

"""

        for domain in trusted_domains[:15]:  # Show first 15
            text += f"✅ <code>{domain}</code>\n"

        if len(trusted_domains) > 15:
            text += f"... і ще {len(trusted_domains) - 15} доменів"

    keyboard = [[
        InlineKeyboardButton("🔙 Назад", callback_data="link_management")
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def show_detailed_link_stats(query, context):
    """Show detailed link analysis statistics"""
    from database import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get recent link analysis data
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN is_safe = 1 THEN 1 ELSE 0 END) as safe,
            SUM(CASE WHEN is_safe = 0 THEN 1 ELSE 0 END) as unsafe,
            COUNT(DISTINCT user_id) as unique_users
        FROM link_analysis_log
        WHERE created_at >= datetime('now', '-30 days')
    """)

    stats = cursor.fetchone()

    # Get top unsafe domains
    cursor.execute("""
        SELECT original_url, COUNT(*) as count
        FROM link_analysis_log
        WHERE is_safe = 0 AND created_at >= datetime('now', '-30 days')
        GROUP BY original_url
        ORDER BY count DESC
        LIMIT 5
    """)

    unsafe_domains = cursor.fetchall()
    conn.close()

    safe_percent = (stats['safe'] / stats['total'] *
                    100) if stats['total'] > 0 else 0
    unsafe_percent = (stats['unsafe'] / stats['total'] *
                      100) if stats['total'] > 0 else 0

    text = f"""
📊 <b>ДЕТАЛЬНА СТАТИСТИКА ПОСИЛАНЬ</b>
🕐 {get_kyiv_time()}

📈 <b>ОСТАННІ 30 ДНІВ:</b>
• Всього перевірено: {stats['total']}
• Безпечних: {stats['safe']} ({safe_percent:.1f}%)
• Небезпечних: {stats['unsafe']} ({unsafe_percent:.1f}%)
• Унікальних користувачів: {stats['unique_users']}

"""

    if unsafe_domains:
        text += "⚠️ <b>НАЙЧАСТІШІ НЕБЕЗПЕЧНІ ДОМЕНИ:</b>\n"
        for domain_info in unsafe_domains:
            domain = domain_info['original_url']
            if len(domain) > 40:
                domain = domain[:37] + "..."
            text += f"• <code>{domain}</code> ({domain_info['count']} разів)\n"

    keyboard = [[
        InlineKeyboardButton("🔙 Назад", callback_data="link_management")
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def show_link_settings(query, context):
    """Show link verification settings"""
    from database import get_link_setting

    # Get current settings
    auto_check = get_link_setting('auto_check_enabled') or 'true'
    block_unsafe = get_link_setting('block_unsafe_links') or 'true'
    log_analysis = get_link_setting('log_analysis') or 'true'

    text = f"""
⚙️ <b>НАЛАШТУВАННЯ ПЕРЕВІРКИ ПОСИЛАНЬ</b>
🕐 {get_kyiv_time()}

🔄 <b>Автоматична перевірка:</b> {'✅ Увімкнено' if auto_check == 'true' else '❌ Вимкнено'}
🚫 <b>Блокування небезпечних:</b> {'✅ Увімкнено' if block_unsafe == 'true' else '❌ Вимкнено'}
📝 <b>Логування аналізу:</b> {'✅ Увімкнено' if log_analysis == 'true' else '❌ Вимкнено'}

📋 <b>ОПИС НАЛАШТУВАНЬ:</b>
• <b>Автоматична перевірка</b> - перевіряє всі посилання в чаті
• <b>Блокування небезпечних</b> - блокує підозрілі посилання
• <b>Логування аналізу</b> - зберігає результати перевірки
    """

    keyboard = [[
        InlineKeyboardButton("🔙 Назад", callback_data="link_management")
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def handle_clear_link_stats(query, context):
    """Handle clearing link statistics"""
    text = """
🔄 <b>ОЧИСТКА СТАТИСТИКИ</b>

⚠️ Ви впевнені, що хочете очистити всю статистику аналізу посилань?

Цю дію неможливо скасувати.
    """

    keyboard = [[
        InlineKeyboardButton("❌ Скасувати", callback_data="link_management")
    ],
                [
                    InlineKeyboardButton("✅ Підтвердити",
                                         callback_data="link_confirm_clear")
                ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def handle_confirm_clear_stats(query, context):
    """Handle confirmed clearing of link statistics"""
    from database import get_db_connection

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Clear link analysis log
        cursor.execute("DELETE FROM link_analysis_log")
        deleted_count = cursor.rowcount

        conn.commit()
        conn.close()

        text = f"""
✅ <b>СТАТИСТИКА ОЧИЩЕНА</b>
🕐 {get_kyiv_time()}

🗑️ Видалено записів: {deleted_count}

Статистика аналізу посилань повністю очищена.
Нова статистика буде накопичуватися з наступних перевірок.
        """

        keyboard = [[
            InlineKeyboardButton("🔙 Назад", callback_data="link_management")
        ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        await query.edit_message_text(f"❌ Помилка при очищенні: {str(e)}")


async def show_top_users(query, context) -> None:
    """Show top users by various metrics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Top users by balance
        cursor.execute("""
            SELECT user_id, username, balance, rating, completed_tasks
            FROM users 
            WHERE user_id > 100000
            ORDER BY balance DESC
            LIMIT 10
        """)
        top_balance = cursor.fetchall()

        # Top users by rating
        cursor.execute("""
            SELECT user_id, username, balance, rating, completed_tasks
            FROM users 
            WHERE user_id > 100000 AND rating > 0
            ORDER BY rating DESC, completed_tasks DESC
            LIMIT 10
        """)
        top_rating = cursor.fetchall()

        conn.close()

        text = f"🏆 <b>ТОП КОРИСТУВАЧІ</b>\n🕐 {get_kyiv_time()}\n\n"

        if top_balance:
            text += "💰 <b>За балансом:</b>\n"
            for i, user in enumerate(top_balance, 1):
                username_display = user['username'] or f"ID:{user['user_id']}"
                text += f"{i}. {username_display} - {user['balance']:.2f} грн\n"

        if top_rating:
            text += "\n⭐ <b>За рейтингом:</b>\n"
            for i, user in enumerate(top_rating, 1):
                username_display = user['username'] or f"ID:{user['user_id']}"
                text += f"{i}. {username_display} - {user['rating']:.1f} ⭐\n"

        keyboard = []
        # Add buttons for top users
        for user in top_balance[:5]:
            username_display = user['username'] or str(user['user_id'])
            keyboard.append([
                InlineKeyboardButton(
                    f"👤 {username_display}",
                    callback_data=f"user_info_{user['user_id']}")
            ])

        keyboard.extend([[
            InlineKeyboardButton("🔄 Оновити", callback_data="top_users")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="user_management")]])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing top users: {e}")
        await query.edit_message_text("❌ Помилка завантаження топ користувачів"
                                      )


async def show_recent_users(query, context) -> None:
    """Show recently registered users"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, username, created_at, balance, rating
            FROM users 
            WHERE user_id > 100000
            ORDER BY created_at DESC
            LIMIT 15
        """)
        recent_users = cursor.fetchall()
        conn.close()

        text = f"🆕 <b>ОСТАННІ КОРИСТУВАЧІ</b>\n🕐 {get_kyiv_time()}\n\n"

        if not recent_users:
            text += "❌ Немає нових користувачів"
        else:
            for user in recent_users:
                username_display = user['username'] or f"ID:{user['user_id']}"
                text += f"👤 {username_display}\n"
                text += f"   📅 {user['created_at'][:10]}\n"
                text += f"   💰 {user['balance']:.2f} грн | ⭐ {user['rating']:.1f}\n\n"

        keyboard = []
        for user in recent_users[:5]:  # Show buttons for first 5 users
            username_display = user['username'] or str(user['user_id'])
            keyboard.append([
                InlineKeyboardButton(
                    f"👤 {username_display}",
                    callback_data=f"user_info_{user['user_id']}")
            ])

        keyboard.extend([[
            InlineKeyboardButton("🔄 Оновити", callback_data="recent_users")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="user_management")]])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing recent users: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження останніх користувачів")


async def show_financial_stats(query, context) -> None:
    """Show financial statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Total balance in system
        cursor.execute("SELECT SUM(balance) FROM users WHERE user_id > 100000")
        total_balance = cursor.fetchone()[0] or 0

        # Total frozen balance
        cursor.execute(
            "SELECT SUM(frozen_balance) FROM users WHERE user_id > 100000")
        total_frozen = cursor.fetchone()[0] or 0

        # Average balance
        cursor.execute(
            "SELECT AVG(balance) FROM users WHERE balance > 0 AND user_id > 100000"
        )
        avg_balance = cursor.fetchone()[0] or 0

        # Users with balance > 0
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE balance > 0 AND user_id > 100000"
        )
        users_with_balance = cursor.fetchone()[0]

        # Top balance holder
        cursor.execute(
            "SELECT username, balance FROM users WHERE user_id > 100000 ORDER BY balance DESC LIMIT 1"
        )
        top_user = cursor.fetchone()

        conn.close()

        text = f"""
💰 <b>ФІНАНСОВА СТАТИСТИКА</b>
🕐 {get_kyiv_time()}

💳 <b>Загальний баланс:</b> {total_balance:.2f} грн
🔒 <b>Заморожено:</b> {total_frozen:.2f} грн
📊 <b>Середній баланс:</b> {avg_balance:.2f} грн
👥 <b>Користувачів з балансом:</b> {users_with_balance}
💹 <b>Вільні кошти:</b> {(total_balance - total_frozen):.2f} грн
        """

        if top_user:
            top_username = top_user['username'] or "Анонім"
            text += f"\n🏆 <b>Найбільший баланс:</b> {top_username} ({top_user['balance']:.2f} грн)"

        keyboard = [[
            InlineKeyboardButton("💳 Транзакції", callback_data="transactions")
        ], [
            InlineKeyboardButton("🔄 Оновити", callback_data="financial_stats")
        ],
                    [
                        InlineKeyboardButton(
                            "🔙 Назад", callback_data="financial_operations")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing financial stats: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження фінансової статистики")


async def show_transactions(query, context) -> None:
    """Show recent transactions"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get users with recent balance changes
        cursor.execute("""
            SELECT user_id, username, balance, frozen_balance, created_at
            FROM users 
            WHERE (balance > 0 OR frozen_balance > 0) AND user_id > 100000
            ORDER BY created_at DESC
            LIMIT 20
        """)
        transactions = cursor.fetchall()

        # Get completed tasks for transaction history
        cursor.execute("""
            SELECT t.task_id, t.price, t.created_at, c.username as customer, e.username as executor
            FROM tasks t
            LEFT JOIN users c ON t.customer_id = c.user_id
            LEFT JOIN users e ON t.executor_id = e.user_id
            WHERE t.status = 'completed' AND t.created_at > datetime('now', '-7 days')
            ORDER BY t.created_at DESC
            LIMIT 10
        """)
        completed_tasks = cursor.fetchall()

        conn.close()

        text = f"💳 <b>ТРАНЗАКЦІЇ</b>\n🕐 {get_kyiv_time()}\n\n"

        if completed_tasks:
            text += "✅ <b>Завершені завдання (7 днів):</b>\n"
            for task in completed_tasks:
                customer_name = task['customer'] or "Анонім"
                executor_name = task['executor'] or "Анонім"
                text += f"💰 {task['price']:.2f} грн - {customer_name} → {executor_name}\n"
                text += f"   📅 {task['created_at'][:10]}\n\n"

        if transactions:
            text += "👥 <b>Користувачі з балансом:</b>\n"
            for trans in transactions[:5]:
                username_display = trans['username'] or f"ID:{trans['user_id']}"
                text += f"👤 {username_display}\n"
                text += f"💰 Баланс: {trans['balance']:.2f} грн\n"
                if trans['frozen_balance'] > 0:
                    text += f"🔒 Заморожено: {trans['frozen_balance']:.2f} грн\n"
                text += "\n"

        keyboard = [[
            InlineKeyboardButton("💰 Фінансова статистика",
                                 callback_data="financial_stats")
        ], [InlineKeyboardButton("🔄 Оновити", callback_data="transactions")],
                    [
                        InlineKeyboardButton(
                            "🔙 Назад", callback_data="financial_operations")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing transactions: {e}")
        await query.edit_message_text("❌ Помилка завантаження транзакцій")


async def send_chat_history(query, task_id: int, context) -> None:
    """Send chat history as text"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get task info and chat code
        cursor.execute(
            """
            SELECT t.description, t.price, t.customer_id, t.executor_id,
                   c.username as customer_name, e.username as executor_name,
                   ch.chat_code
            FROM tasks t
            LEFT JOIN users c ON t.customer_id = c.user_id
            LEFT JOIN users e ON t.executor_id = e.user_id
            LEFT JOIN chats ch ON t.task_id = ch.task_id
            WHERE t.task_id = ?
        """, (task_id, ))
        task = cursor.fetchone()

        if not task:
            await query.edit_message_text("❌ Завдання не знайдено")
            return

        task_dict = dict(task)
        chat_code = task_dict.get('chat_code')

        if not chat_code:
            await query.edit_message_text(
                "❌ Чат не знайдено для цього завдання")
            return

        # Get chat messages for task
        cursor.execute(
            """
            SELECT sender_role, message_text, created_at, file_name
            FROM chat_messages 
            WHERE chat_code = ?
            ORDER BY created_at
        """, (chat_code, ))
        messages = cursor.fetchall()

        conn.close()

        customer_name = task_dict[
            'customer_name'] or f"ID:{task_dict['customer_id']}"
        executor_name = task_dict[
            'executor_name'] or f"ID:{task_dict['executor_id']}"

        # Create text history
        history_text = f"""
📄 <b>ІСТОРІЯ ЧАТУ - ЗАВДАННЯ #{task_id}</b>
🕐 {get_kyiv_time()}

Замовник: {customer_name}
Виконавець: {executor_name}
Опис: {task_dict['description'][:100]}...
Ціна: {task_dict['price']:.2f} грн

ПОВІДОМЛЕННЯ ({len(messages)}):
"""

        if not messages:
            history_text += "\n❌ Повідомлень не знайдено"
        else:
            for msg in messages[-10:]:  # Last 10 messages
                msg_dict = dict(msg)
                timestamp = msg_dict['created_at'][:16]
                role = "Замовник" if msg_dict[
                    'sender_role'] == 'customer' else "Виконавець"

                if msg_dict.get('file_name'):
                    history_text += f"\n[{timestamp}] {role}: 📎 {msg_dict['file_name']}"
                else:
                    history_text += f"\n[{timestamp}] {role}: {msg_dict['message_text'][:100] if msg_dict['message_text'] else 'Порожнє повідомлення'}"

        keyboard = [
            [
                InlineKeyboardButton("📎 Файли чату",
                                     callback_data=f"chat_files_{task_id}_0")
            ],
            [
                InlineKeyboardButton("📋 Деталі завдання",
                                     callback_data=f"task_details_{task_id}")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="active_disputes")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(history_text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error sending chat history: {e}")
        await query.edit_message_text("❌ Помилка завантаження історії чату")


async def show_task_management(query, context) -> None:
    """Show task management interface"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get task statistics
        cursor.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
        status_counts = dict(cursor.fetchall())

        cursor.execute("SELECT COUNT(*) FROM tasks")
        total_tasks = cursor.fetchone()[0]

        conn.close()

        text = f"""
📋 <b>УПРАВЛІННЯ ЗАВДАННЯМИ</b>
🕐 {get_kyiv_time()}

📊 <b>Статистика:</b>
• Всього завдань: {total_tasks}
• В пошуку: {status_counts.get('searching', 0)}
• В роботі: {status_counts.get('in_progress', 0)}
• Завершено: {status_counts.get('completed', 0)}
• Спори: {status_counts.get('dispute', 0)}
• Скасовано: {status_counts.get('cancelled', 0)}
        """

        keyboard = [[
            InlineKeyboardButton("🔍 Активні завдання",
                                 callback_data="active_tasks")
        ],
                    [
                        InlineKeyboardButton("⚠️ Проблемні завдання",
                                             callback_data="problem_tasks")
                    ],
                    [
                        InlineKeyboardButton("📊 Статистика завдань",
                                             callback_data="task_stats")
                    ],
                    [
                        InlineKeyboardButton("🔙 Назад",
                                             callback_data="back_to_main")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing task management: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження управління завданнями")


async def show_system_alerts(query, context) -> None:
    """Show system alerts and notifications"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check for issues
        alerts = []

        # Check for old disputes
        cursor.execute("""
            SELECT COUNT(*) FROM disputes 
            WHERE status = 'open' AND created_at < datetime('now', '-7 days')
        """)
        old_disputes = cursor.fetchone()[0]
        if old_disputes > 0:
            alerts.append(f"⚠️ {old_disputes} спорів старше 7 днів")

        # Check for tasks stuck in searching
        cursor.execute("""
            SELECT COUNT(*) FROM tasks 
            WHERE status = 'searching' AND created_at < datetime('now', '-1 day')
        """)
        stuck_tasks = cursor.fetchone()[0]
        if stuck_tasks > 0:
            alerts.append(f"🔍 {stuck_tasks} завдань в пошуку більше доби")

        # Check for users with high frozen balance
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE frozen_balance > balance AND user_id > 100000
        """)
        balance_issues = cursor.fetchone()[0]
        if balance_issues > 0:
            alerts.append(
                f"💰 {balance_issues} користувачів з проблемами балансу")

        # Check for users with very high balance (possible issues)
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE balance > 10000 AND user_id > 100000
        """)
        high_balance_users = cursor.fetchone()[0]
        if high_balance_users > 0:
            alerts.append(
                f"💎 {high_balance_users} користувачів з балансом > 10000 грн")

        conn.close()

        text = f"🔔 <b>СИСТЕМНІ СПОВІЩЕННЯ</b>\n🕐 {get_kyiv_time()}\n\n"

        if alerts:
            text += "\n".join(alerts)
        else:
            text += "✅ Всі системи працюють нормально"

        keyboard = [
            [
                InlineKeyboardButton("🔧 Системне обслуговування",
                                     callback_data="system_maintenance")
            ],
            [
                InlineKeyboardButton("📢 Відправити повідомлення всім",
                                     callback_data="broadcast_message")
            ],
            [InlineKeyboardButton("🔄 Оновити", callback_data="system_alerts")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing system alerts: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження системних сповіщень")


async def show_admin_settings(query, context) -> None:
    """Show admin settings panel"""
    text = f"""
⚙️ <b>НАЛАШТУВАННЯ АДМІНІСТРАТОРА</b>
🕐 {get_kyiv_time()}

Доступні налаштування:
• Управління адміністраторами
• Налаштування комісій
• Параметри системи
• Налаштування сповіщень
• Системне обслуговування
    """

    keyboard = [[
        InlineKeyboardButton("👑 Список адмінів", callback_data="list_admins")
    ],
                [
                    InlineKeyboardButton("🔧 Системне обслуговування",
                                         callback_data="system_maintenance")
                ],
                [
                    InlineKeyboardButton("📢 Розсилка повідомлень",
                                         callback_data="broadcast_message")
                ],
                [
                    InlineKeyboardButton("🔙 Назад",
                                         callback_data="back_to_main")
                ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def handle_user_action(query, action: str, user_id: int,
                             context) -> None:
    """Handle various user actions from admin panel"""
    try:
        if action == "balance":
            await show_balance_operations(query, user_id, context)
        elif action == "admin":
            success = set_admin_status(user_id, True, 1)
            if success:
                await query.edit_message_text(
                    f"✅ Користувач {user_id} тепер адміністратор")
            else:
                await query.edit_message_text(
                    "❌ Помилка надання прав адміністратора")
        elif action == "block":
            await handle_block_user(query, user_id, context)
        else:
            await query.edit_message_text("❌ Невідома дія")

    except Exception as e:
        logger.error(f"Error handling user action {action} for {user_id}: {e}")
        await query.edit_message_text("❌ Помилка виконання дії")


async def handle_text_input(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input for user search and other operations"""
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    query_text = update.message.text.strip()

    # Check if user is in a context (waiting for input)
    if user_id in user_contexts:
        context_info = user_contexts[user_id]
        await handle_context_input(update, context, context_info, query_text)
        return

    # Remove @ if present
    if query_text.startswith('@'):
        query_text = query_text[1:]

    # Search for users
    users = search_users(query_text)

    if not users:
        await update.message.reply_text("❌ Користувачів не знайдено")
        return

    text = f"🔍 <b>РЕЗУЛЬТАТИ ПОШУКУ</b>\n🕐 {get_kyiv_time()}\n\nЗапит: {query_text}\n\n"
    keyboard = []

    for user in users[:10]:  # Limit to 10 results
        username_display = user['username'] or f"ID:{user['user_id']}"
        text += f"👤 {username_display}\n"
        text += f"   💰 {user['balance']:.2f} грн | ⭐ {user['rating']:.1f}\n"
        text += f"   🔧 {'Виконавець' if user['is_executor'] else 'Клієнт'} | 🛡 {'Адмін' if user['is_admin'] else 'Звичайний'}\n\n"

        keyboard.append([
            InlineKeyboardButton(f"👤 {username_display}",
                                 callback_data=f"user_info_{user['user_id']}")
        ])

    keyboard.append(
        [InlineKeyboardButton("🔍 Новий пошук", callback_data="user_search")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text,
                                    reply_markup=reply_markup,
                                    parse_mode='HTML')


async def handle_context_input(update: Update,
                               context: ContextTypes.DEFAULT_TYPE,
                               context_info: dict, input_text: str) -> None:
    """Handle input when user is in a specific context"""
    user_id = update.effective_user.id

    try:
        if context_info['type'] == 'balance_operation':
            target_user_id = context_info['user_id']
            operation = context_info['operation']

            try:
                amount = float(input_text)
                if amount <= 0:
                    await update.message.reply_text(
                        "❌ Сума повинна бути більше 0")
                    return

                success = update_user_balance(target_user_id, amount,
                                              operation)

                if success:
                    operation_text = "додано" if operation == "add" else "списано"
                    await update.message.reply_text(
                        f"✅ {amount:.2f} грн {operation_text} користувачу {target_user_id}"
                    )
                else:
                    await update.message.reply_text(
                        "❌ Помилка оновлення балансу")

            except ValueError:
                await update.message.reply_text(
                    "❌ Невірний формат суми. Введіть число.")
                return

        elif context_info['type'] == 'broadcast_message':
            await send_broadcast_message(update, context, input_text)

        # Clear context
        if user_id in user_contexts:
            del user_contexts[user_id]

    except Exception as e:
        logger.error(f"Error handling context input: {e}")
        await update.message.reply_text("❌ Помилка обробки введеної інформації"
                                        )


async def notify_admins_about_dispute(dispute_id: int, task_id: int,
                                      reason: str):
    """Notify all admins about new dispute"""
    try:
        admin_bot_token = ADMIN_BOT_TOKEN

        message = f"""
⚠️ <b>НОВИЙ СПІР!</b>

🆔 <b>Спір:</b> #{dispute_id}
📋 <b>Завдання:</b> {task_id}
📝 <b>Причина:</b> {reason}
⏰ <b>Час:</b> {get_kyiv_time()}

Перейдіть до бота для вирішення спору.
        """

        url = f"https://api.telegram.org/bot{admin_bot_token}/sendMessage"
        data = {
            'chat_id': ADMIN_USER_ID,
            'text': message,
            'parse_mode': 'HTML'
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)

        logger.info(f"Dispute notification sent: {response.status_code}")

    except Exception as e:
        logger.error(f"Failed to notify admins about dispute: {e}")


# New functions for enhanced functionality


async def show_list_admins(query, context) -> None:
    """Show list of all administrators"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, username, admin_level, created_at
            FROM users 
            WHERE is_admin = 1
            ORDER BY admin_level DESC, created_at
        """)
        admins = cursor.fetchall()
        conn.close()

        text = f"👑 <b>СПИСОК АДМІНІСТРАТОРІВ</b>\n🕐 {get_kyiv_time()}\n\n"

        if not admins:
            text += "❌ Адміністраторів не знайдено"
        else:
            for admin in admins:
                username_display = admin['username'] or f"ID:{admin['user_id']}"
                level_text = f"Рівень {admin['admin_level']}" if admin[
                    'admin_level'] else "Рівень 1"
                text += f"👑 {username_display} ({level_text})\n"
                text += f"   📅 З {admin['created_at'][:10]}\n\n"

        keyboard = [[
            InlineKeyboardButton("🔄 Оновити", callback_data="list_admins")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing admin list: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження списку адміністраторів")


async def show_active_tasks(query, context) -> None:
    """Show active tasks"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT t.task_id, t.description, t.price, t.status, t.created_at,
                   c.username as customer_name, e.username as executor_name
            FROM tasks t
            LEFT JOIN users c ON t.customer_id = c.user_id
            LEFT JOIN users e ON t.executor_id = e.user_id
            WHERE t.status IN ('searching', 'in_progress')
            ORDER BY t.created_at DESC
            LIMIT 20
        """)
        tasks = cursor.fetchall()
        conn.close()

        text = f"📋 <b>АКТИВНІ ЗАВДАННЯ ({len(tasks)})</b>\n🕐 {get_kyiv_time()}\n\n"

        if not tasks:
            text += "✅ Активних завдань немає"
        else:
            keyboard = []
            for task in tasks:
                customer_name = task[
                    'customer_name'] or f"ID:{task['customer_id']}"
                executor_name = task['executor_name'] or "Не призначено"
                status_emoji = "🔍" if task['status'] == 'searching' else "⚙️"

                text += f"{status_emoji} <b>Завдання #{task['task_id']}</b>\n"
                text += f"💰 {task['price']:.2f} грн\n"
                text += f"👤 Замовник: {customer_name}\n"
                text += f"🔧 Виконавець: {executor_name}\n"
                text += f"📝 {task['description'][:50]}...\n"
                text += f"📅 {task['created_at'][:10]}\n\n"

                keyboard.append([
                    InlineKeyboardButton(
                        f"📋 Завдання #{task['task_id']}",
                        callback_data=f"task_details_{task['task_id']}")
                ])

        keyboard.extend([[
            InlineKeyboardButton("🔄 Оновити", callback_data="active_tasks")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="task_management")]])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing active tasks: {e}")
        await query.edit_message_text("❌ Помилка завантаження активних завдань"
                                      )


async def show_problem_tasks(query, context) -> None:
    """Show problematic tasks"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Tasks stuck in searching
        cursor.execute("""
            SELECT task_id, description, price, created_at
            FROM tasks 
            WHERE status = 'searching' AND created_at < datetime('now', '-1 day')
            ORDER BY created_at
            LIMIT 10
        """)
        stuck_tasks = cursor.fetchall()

        # Disputed tasks
        cursor.execute("""
            SELECT t.task_id, t.description, t.price, d.reason, d.created_at
            FROM tasks t
            JOIN disputes d ON t.task_id = d.task_id
            WHERE t.status = 'dispute' AND d.status = 'open'
            ORDER BY d.created_at
            LIMIT 10
        """)
        disputed_tasks = cursor.fetchall()

        conn.close()

        text = f"⚠️ <b>ПРОБЛЕМНІ ЗАВДАННЯ</b>\n🕐 {get_kyiv_time()}\n\n"
        keyboard = []

        if stuck_tasks:
            text += f"🔍 <b>Застрягли в пошуку ({len(stuck_tasks)}):</b>\n"
            for task in stuck_tasks:
                text += f"#{task['task_id']} - {task['price']:.2f} грн\n"
                text += f"   📅 {task['created_at'][:10]}\n"
                text += f"   📝 {task['description'][:40]}...\n\n"

                keyboard.append([
                    InlineKeyboardButton(
                        f"📋 Завдання #{task['task_id']}",
                        callback_data=f"task_details_{task['task_id']}")
                ])

        if disputed_tasks:
            text += f"⚠️ <b>В спорах ({len(disputed_tasks)}):</b>\n"
            for task in disputed_tasks:
                text += f"#{task['task_id']} - {task['price']:.2f} грн\n"
                text += f"   📅 {task['created_at'][:10]}\n"
                text += f"   📝 {task['reason'][:40]}...\n\n"

        if not stuck_tasks and not disputed_tasks:
            text += "✅ Проблемних завдань немає"

        keyboard.extend([[
            InlineKeyboardButton("🔄 Оновити", callback_data="problem_tasks")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="task_management")]])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(query, text, reply_markup)

    except Exception as e:
        logger.error(f"Error showing problem tasks: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження проблемних завдань")


async def show_user_complete_history(query, user_id: int, context) -> None:
    """Show complete user history with all activities."""
    try:
        history = get_user_complete_history(user_id)
        user = get_user_info(user_id)

        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"

        text = f"📊 <b>ПОВНА ІСТОРІЯ КОРИСТУВАЧА</b>\n"
        text += f"👤 {username_display}\n🕐 {get_kyiv_time()}\n\n"

        # Tasks as customer
        if history.get('tasks_as_customer'):
            text += f"📋 <b>Завдання як замовник ({len(history['tasks_as_customer'])}):</b>\n"
            for task in history['tasks_as_customer'][:5]:
                status_emoji = {
                    "searching": "🔍",
                    "in_progress": "⚙️",
                    "completed": "✅",
                    "cancelled": "❌",
                    "dispute": "⚠️"
                }.get(task['status'], "❓")
                text += f"{status_emoji} #{task['task_id']} - {task['price']:.2f} грн\n"
                text += f"   📅 {task['created_at'][:10]}\n\n"

        # Tasks as executor
        if history.get('tasks_as_executor'):
            text += f"🔧 <b>Завдання як виконавець ({len(history['tasks_as_executor'])}):</b>\n"
            for task in history['tasks_as_executor'][:5]:
                status_emoji = {
                    "searching": "🔍",
                    "in_progress": "⚙️",
                    "completed": "✅",
                    "cancelled": "❌",
                    "dispute": "⚠️"
                }.get(task['status'], "❓")
                text += f"{status_emoji} #{task['task_id']} - {task['price']:.2f} грн\n"
                text += f"   📅 {task['created_at'][:10]}\n\n"

        # Reviews
        if history.get('reviews_given'):
            text += f"⭐ <b>Залишено відгуків:</b> {len(history['reviews_given'])}\n"
        if history.get('reviews_received'):
            text += f"📝 <b>Отримано відгуків:</b> {len(history['reviews_received'])}\n"

        # Chat messages
        if history.get('chat_messages'):
            text += f"💬 <b>Повідомлень у чатах:</b> {len(history['chat_messages'])}\n"

        # Disputes
        if history.get('disputes'):
            text += f"⚠️ <b>Спорів:</b> {len(history['disputes'])}\n"

        keyboard = [
            [
                InlineKeyboardButton("📋 Завдання користувача",
                                     callback_data=f"user_tasks_{user_id}")
            ],
            [
                InlineKeyboardButton("⭐ Відгуки користувача",
                                     callback_data=f"user_reviews_{user_id}")
            ],
            [
                InlineKeyboardButton("🔄 Оновити",
                                     callback_data=f"user_history_{user_id}")
            ],
            [
                InlineKeyboardButton("🔙 Назад",
                                     callback_data=f"user_info_{user_id}")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing user history: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження історії користувача")


async def show_user_action_menu(query, user_id: int, context) -> None:
    """Show user action menu with permission checks."""
    try:
        admin_id = query.from_user.id
        user = get_user_info(user_id)

        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"
        admin_level = get_admin_level(admin_id)
        target_level = get_admin_level(user_id)
        can_manage = can_manage_user(admin_id, user_id)

        text = f"⚙️ <b>ДІЇ З КОРИСТУВАЧЕМ</b>\n"
        text += f"👤 {username_display}\n"
        text += f"🛡 Ваш рівень: {admin_level}\n"
        text += f"🎯 Рівень цілі: {target_level}\n"
        text += f"🕐 {get_kyiv_time()}\n\n"

        keyboard = []

        if can_manage:
            text += "✅ <b>Доступні дії:</b>\n"

            # Balance operations
            keyboard.append([
                InlineKeyboardButton("💰 Операції з балансом",
                                     callback_data=f"balance_ops_{user_id}")
            ])

            # Admin level management
            if not user['is_admin']:
                for level in range(1, admin_level):
                    keyboard.append([
                        InlineKeyboardButton(
                            f"🛡 Зробити адміном рівень {level}",
                            callback_data=f"admin_level_{user_id}_{level}")
                    ])
            else:
                # Promote/demote admin
                for level in range(1, admin_level):
                    if level != target_level:
                        action_text = "Підвищити" if level > target_level else "Понизити"
                        keyboard.append([
                            InlineKeyboardButton(
                                f"📈 {action_text} до рівня {level}",
                                callback_data=f"admin_level_{user_id}_{level}")
                        ])

                keyboard.append([
                    InlineKeyboardButton(
                        "❌ Видалити адміна",
                        callback_data=f"remove_admin_{user_id}")
                ])

            # Block user
            keyboard.append([
                InlineKeyboardButton("🚫 Заблокувати користувача",
                                     callback_data=f"block_user_{user_id}")
            ])

        else:
            text += "❌ <b>Недостатньо прав для управління цим користувачем</b>\n"
            text += "Ви можете управляти тільки користувачами з нижчим рівнем адміністратора.\n"

        keyboard.extend([[
            InlineKeyboardButton("🔄 Оновити",
                                 callback_data=f"user_actions_{user_id}")
        ],
                         [
                             InlineKeyboardButton(
                                 "🔙 Назад",
                                 callback_data=f"user_info_{user_id}")
                         ]])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing user action menu: {e}")
        await query.edit_message_text("❌ Помилка завантаження меню дій")


async def show_balance_operations(query, user_id: int, context) -> None:
    """Show balance operations menu."""
    try:
        user = get_user_info(user_id)

        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"

        text = f"""
💰 <b>ОПЕРАЦІЇ З БАЛАНСОМ</b>
🕐 {get_kyiv_time()}

👤 {username_display}
💰 Поточний баланс: {user['balance']:.2f} грн
🧊 Заморожено: {user['frozen_balance']:.2f} грн

⚠️ <b>Доступні операції:</b>
• Додати кошти на баланс
• Списати кошти з балансу
• Розморозити заморожені кошти
        """

        keyboard = [
            [
                InlineKeyboardButton("➕ Додати кошти",
                                     callback_data=f"add_balance_{user_id}")
            ],
            [
                InlineKeyboardButton("➖ Списати кошти",
                                     callback_data=f"remove_balance_{user_id}")
            ],
            [
                InlineKeyboardButton(
                    "🔓 Розморозити",
                    callback_data=f"unfreeze_balance_{user_id}")
            ],
            [
                InlineKeyboardButton("🔄 Оновити",
                                     callback_data=f"balance_ops_{user_id}")
            ],
            [
                InlineKeyboardButton("🔙 Назад",
                                     callback_data=f"user_actions_{user_id}")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing balance operations: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження операцій з балансом")


async def handle_admin_level_change(query, user_id: int, level: int,
                                    context) -> None:
    """Handle admin level change."""
    try:
        admin_id = query.from_user.id

        if not can_manage_user(admin_id, user_id):
            await query.edit_message_text(
                "❌ Недостатньо прав для цієї операції")
            return

        user = get_user_info(user_id)
        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"

        success = set_admin_status(user_id, True, level)

        if success:
            text = f"✅ <b>УСПІШНО ОНОВЛЕНО</b>\n🕐 {get_kyiv_time()}\n\n"
            text += f"👤 Користувач: {username_display}\n"
            text += f"🛡 Новий рівень адміністратора: {level}\n"
        else:
            text = "❌ Помилка зміни рівня адміністратора"

        keyboard = [[
            InlineKeyboardButton("🔙 Назад до дій",
                                 callback_data=f"user_actions_{user_id}")
        ],
                    [
                        InlineKeyboardButton(
                            "👤 Профіль користувача",
                            callback_data=f"user_info_{user_id}")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error handling admin level change: {e}")
        await query.edit_message_text("❌ Помилка зміни рівня адміністратора")


async def handle_remove_admin(query, user_id: int, context) -> None:
    """Handle removing admin status."""
    try:
        admin_id = query.from_user.id

        if not can_manage_user(admin_id, user_id):
            await query.edit_message_text(
                "❌ Недостатньо прав для цієї операції")
            return

        user = get_user_info(user_id)
        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"

        success = set_admin_status(user_id, False, 0)

        if success:
            text = f"✅ <b>АДМІНІСТРАТОРА ВИДАЛЕНО</b>\n🕐 {get_kyiv_time()}\n\n"
            text += f"👤 Користувач: {username_display}\n"
            text += f"🛡 Статус: Звичайний користувач\n"
        else:
            text = "❌ Помилка видалення адміністратора"

        keyboard = [[
            InlineKeyboardButton("🔙 Назад до дій",
                                 callback_data=f"user_actions_{user_id}")
        ],
                    [
                        InlineKeyboardButton(
                            "👤 Профіль користувача",
                            callback_data=f"user_info_{user_id}")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        await query.edit_message_text("❌ Помилка видалення адміністратора")


async def initiate_balance_operation(query, user_id: int, operation: str,
                                     context) -> None:
    """Initiate balance operation (add/subtract)"""
    try:
        user = get_user_info(user_id)
        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"
        operation_text = "додавання" if operation == "add" else "списання"

        # Set context for user input
        user_contexts[query.from_user.id] = {
            'type': 'balance_operation',
            'user_id': user_id,
            'operation': operation
        }

        text = f"""
💰 <b>ОПЕРАЦІЯ З БАЛАНСОМ</b>
🕐 {get_kyiv_time()}

👤 Користувач: {username_display}
💰 Поточний баланс: {user['balance']:.2f} грн
🔄 Операція: {operation_text}

Введіть суму для {operation_text}:
        """

        keyboard = [[
            InlineKeyboardButton("❌ Скасувати",
                                 callback_data=f"balance_ops_{user_id}")
        ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error initiating balance operation: {e}")
        await query.edit_message_text("❌ Помилка ініціації операції з балансом"
                                      )


async def handle_unfreeze_balance(query, user_id: int, context) -> None:
    """Handle unfreezing user balance"""
    try:
        user = get_user_info(user_id)
        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"
        frozen_amount = user['frozen_balance']

        if frozen_amount <= 0:
            await query.edit_message_text(
                f"❌ У користувача {username_display} немає заморожених коштів")
            return

        success = unfreeze_user_balance(user_id)

        if success:
            text = f"✅ <b>КОШТИ РОЗМОРОЖЕНО</b>\n🕐 {get_kyiv_time()}\n\n"
            text += f"👤 Користувач: {username_display}\n"
            text += f"💰 Розморожено: {frozen_amount:.2f} грн\n"
        else:
            text = "❌ Помилка розморожування коштів"

        keyboard = [[
            InlineKeyboardButton("💰 Операції з балансом",
                                 callback_data=f"balance_ops_{user_id}")
        ],
                    [
                        InlineKeyboardButton(
                            "👤 Профіль користувача",
                            callback_data=f"user_info_{user_id}")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error unfreezing balance: {e}")
        await query.edit_message_text("❌ Помилка розморожування балансу")


async def handle_block_user(query, user_id: int, context) -> None:
    """Handle blocking user"""
    try:
        user = get_user_info(user_id)
        if not user:
            await query.edit_message_text("❌ Користувача не знайдено")
            return

        username_display = user['username'] or f"ID:{user['user_id']}"

        # For now, we'll just show a message since blocking functionality needs to be implemented
        text = f"🚫 <b>БЛОКУВАННЯ КОРИСТУВАЧА</b>\n🕐 {get_kyiv_time()}\n\n"
        text += f"👤 Користувач: {username_display}\n"
        text += f"⚠️ Функція блокування в розробці\n"
        text += f"Поки що можна тільки видалити права адміністратора"

        keyboard = [[
            InlineKeyboardButton("🔙 Назад",
                                 callback_data=f"user_actions_{user_id}")
        ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error blocking user: {e}")
        await query.edit_message_text("❌ Помилка блокування користувача")


async def show_task_details(query, task_id: int, context) -> None:
    """Show detailed task information"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT t.*, c.username as customer_name, e.username as executor_name
            FROM tasks t
            LEFT JOIN users c ON t.customer_id = c.user_id
            LEFT JOIN users e ON t.executor_id = e.user_id
            WHERE t.task_id = ?
        """, (task_id, ))

        task = cursor.fetchone()
        conn.close()

        if not task:
            await query.edit_message_text("❌ Завдання не знайдено")
            return

        customer_name = task['customer_name'] or f"ID:{task['customer_id']}"
        executor_name = task['executor_name'] or "Не призначено"

        status_emojis = {
            'searching': '🔍 В пошуку',
            'in_progress': '⚙️ В роботі',
            'completed': '✅ Завершено',
            'cancelled': '❌ Скасовано',
            'dispute': '⚠️ Спір'
        }

        text = f"""
📋 <b>ДЕТАЛІ ЗАВДАННЯ #{task_id}</b>
🕐 {get_kyiv_time()}

📊 <b>Статус:</b> {status_emojis.get(task['status'], task['status'])}
💰 <b>Ціна:</b> {task['price']:.2f} грн
📅 <b>Створено:</b> {task['created_at'][:10]}
📂 <b>Категорія:</b> {task['category']}
🏷 <b>Теги:</b> {task.get('tags', 'Без тегів')}

👤 <b>Замовник:</b> {customer_name}
🔧 <b>Виконавець:</b> {executor_name}

📝 <b>Опис:</b>
{task['description']}
        """

        keyboard = [
            [
                InlineKeyboardButton(
                    "👤 Інфо замовника",
                    callback_data=f"user_info_{task['customer_id']}")
            ],
            [
                InlineKeyboardButton("📄 Історія чату",
                                     callback_data=f"chat_history_{task_id}")
            ], [InlineKeyboardButton("🔙 Назад", callback_data="active_tasks")]
        ]

        if task['executor_id']:
            keyboard.insert(1, [
                InlineKeyboardButton(
                    "🔧 Інфо виконавця",
                    callback_data=f"user_info_{task['executor_id']}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing task details: {e}")
        await query.edit_message_text("❌ Помилка завантаження деталей завдання"
                                      )


async def show_user_tasks(query, user_id: int, context) -> None:
    """Show user's tasks"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Tasks as customer
        cursor.execute(
            """
            SELECT task_id, description, price, status, created_at
            FROM tasks 
            WHERE customer_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, (user_id, ))
        customer_tasks = cursor.fetchall()

        # Tasks as executor
        cursor.execute(
            """
            SELECT task_id, description, price, status, created_at
            FROM tasks 
            WHERE executor_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, (user_id, ))
        executor_tasks = cursor.fetchall()

        conn.close()

        user = get_user_info(user_id)
        username_display = user['username'] if user else f"ID:{user_id}"

        text = f"📋 <b>ЗАВДАННЯ КОРИСТУВАЧА</b>\n🕐 {get_kyiv_time()}\n"
        text += f"👤 {username_display}\n\n"

        if customer_tasks:
            text += f"📋 <b>Як замовник ({len(customer_tasks)}):</b>\n"
            for task in customer_tasks:
                status_emoji = {
                    "searching": "🔍",
                    "in_progress": "⚙️",
                    "completed": "✅",
                    "cancelled": "❌",
                    "dispute": "⚠️"
                }.get(task['status'], "❓")
                text += f"{status_emoji} #{task['task_id']} - {task['price']:.2f} грн\n"
                text += f"   📝 {task['description'][:40]}...\n"
                text += f"   📅 {task['created_at'][:10]}\n\n"

        if executor_tasks:
            text += f"🔧 <b>Як виконавець ({len(executor_tasks)}):</b>\n"
            for task in executor_tasks:
                status_emoji = {
                    "searching": "🔍",
                    "in_progress": "⚙️",
                    "completed": "✅",
                    "cancelled": "❌",
                    "dispute": "⚠️"
                }.get(task['status'], "❓")
                text += f"{status_emoji} #{task['task_id']} - {task['price']:.2f} грн\n"
                text += f"   📝 {task['description'][:40]}...\n"
                text += f"   📅 {task['created_at'][:10]}\n\n"

        if not customer_tasks and not executor_tasks:
            text += "❌ Завдань не знайдено"

        keyboard = [[
            InlineKeyboardButton("🔄 Оновити",
                                 callback_data=f"user_tasks_{user_id}")
        ],
                    [
                        InlineKeyboardButton(
                            "🔙 Назад", callback_data=f"user_info_{user_id}")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing user tasks: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження завдань користувача")


async def show_user_reviews(query, user_id: int, context) -> None:
    """Show user's reviews"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Reviews given by user
        cursor.execute(
            """
            SELECT r.rating, r.comment, r.created_at, t.task_id
            FROM reviews r
            JOIN tasks t ON r.task_id = t.task_id
            WHERE r.reviewer_id = ?
            ORDER BY r.created_at DESC
            LIMIT 5
        """, (user_id, ))
        given_reviews = cursor.fetchall()

        # Reviews received by user
        cursor.execute(
            """
            SELECT r.rating, r.comment, r.created_at, t.task_id
            FROM reviews r
            JOIN tasks t ON r.task_id = t.task_id
            WHERE r.reviewed_id = ?
            ORDER BY r.created_at DESC
            LIMIT 5
        """, (user_id, ))
        received_reviews = cursor.fetchall()

        conn.close()

        user = get_user_info(user_id)
        username_display = user['username'] if user else f"ID:{user_id}"

        text = f"⭐ <b>ВІДГУКИ КОРИСТУВАЧА</b>\n🕐 {get_kyiv_time()}\n"
        text += f"👤 {username_display}\n\n"

        if given_reviews:
            text += f"📝 <b>Залишені відгуки ({len(given_reviews)}):</b>\n"
            for review in given_reviews:
                stars = "⭐" * review['rating']
                text += f"{stars} (Завдання #{review['task_id']})\n"
                text += f"   💬 {review['comment'][:50]}...\n"
                text += f"   📅 {review['created_at'][:10]}\n\n"

        if received_reviews:
            text += f"📥 <b>Отримані відгуки ({len(received_reviews)}):</b>\n"
            for review in received_reviews:
                stars = "⭐" * review['rating']
                text += f"{stars} (Завдання #{review['task_id']})\n"
                text += f"   💬 {review['comment'][:50]}...\n"
                text += f"   📅 {review['created_at'][:10]}\n\n"

        if not given_reviews and not received_reviews:
            text += "❌ Відгуків не знайдено"

        keyboard = [[
            InlineKeyboardButton("🔄 Оновити",
                                 callback_data=f"user_reviews_{user_id}")
        ],
                    [
                        InlineKeyboardButton(
                            "🔙 Назад", callback_data=f"user_info_{user_id}")
                    ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing user reviews: {e}")
        await query.edit_message_text(
            "❌ Помилка завантаження відгуків користувача")


async def show_system_maintenance(query, context) -> None:
    """Show system maintenance options"""
    text = f"""
🔧 <b>СИСТЕМНЕ ОБСЛУГОВУВАННЯ</b>
🕐 {get_kyiv_time()}

Доступні операції обслуговування:
• Очищення старих даних
• Перевірка цілісності бази даних
• Оптимізація продуктивності
• Резервне копіювання

⚠️ Деякі операції можуть тимчасово вплинути на роботу системи.
    """

    keyboard = [[
        InlineKeyboardButton("🗑 Очистити старі дані",
                             callback_data="cleanup_old_data")
    ], [
        InlineKeyboardButton("🔍 Перевірити БД", callback_data="check_database")
    ], [
        InlineKeyboardButton("📊 Статистика БД", callback_data="database_stats")
    ], [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def initiate_broadcast(query, context) -> None:
    """Initiate broadcast message"""
    user_contexts[query.from_user.id] = {'type': 'broadcast_message'}

    text = f"""
📢 <b>РОЗСИЛКА ПОВІДОМЛЕНЬ</b>
🕐 {get_kyiv_time()}

Введіть текст повідомлення для розсилки всім користувачам:

⚠️ Повідомлення буде відправлено всім зареєстрованим користувачам системи.
    """

    keyboard = [[
        InlineKeyboardButton("❌ Скасувати", callback_data="admin_settings")
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text,
                                  reply_markup=reply_markup,
                                  parse_mode='HTML')


async def send_broadcast_message(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE,
                                 message_text: str) -> None:
    """Send broadcast message to all users via main bot"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT user_id FROM users WHERE user_id > 100000")
        users = cursor.fetchall()
        conn.close()

        # Use main bot token for broadcasting
        MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN")
        if not MAIN_BOT_TOKEN:
            await update.message.reply_text(
                "❌ Помилка: токен головного бота не налаштований")
            return

        sent_count = 0
        failed_count = 0

        # Send broadcast via main bot
        for user in users:
            try:
                url = f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/sendMessage"
                data = {
                    'chat_id': user['user_id'],
                    'text':
                    f"📢 <b>Повідомлення від адміністрації Rozdum:</b>\n\n{message_text}",
                    'parse_mode': 'HTML'
                }

                async with httpx.AsyncClient() as client:
                    response = await client.post(url, data=data)
                    if response.status_code == 200:
                        sent_count += 1
                    else:
                        failed_count += 1

            except Exception as e:
                logger.error(f"Failed to send to user {user['user_id']}: {e}")
                failed_count += 1

        await update.message.reply_text(f"""
✅ <b>РОЗСИЛКА ЗАВЕРШЕНА</b>
🕐 {get_kyiv_time()}

📊 Статистика розсилки:
• Користувачів в базі: {len(users)}
• Відправлено: {sent_count}
• Помилки: {failed_count}

📝 Текст повідомлення:
{message_text}
        """,
                                        parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error sending broadcast: {e}")
        await update.message.reply_text("❌ Помилка розсилки повідомлень")


async def show_chat_history(query: CallbackQuery,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show chat history for dispute resolution"""
    try:
        data = query.data
        if data.startswith("chat_history_"):
            task_id = int(data.split("_")[2])
        else:
            # Extract task_id from callback data format like "chat_files_8"
            task_id = int(data.split("_")[2])

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get chat messages
        cursor.execute(
            """
            SELECT cm.*, u.username 
            FROM chat_messages cm
            LEFT JOIN users u ON cm.sender_id = u.user_id
            WHERE cm.chat_code IN (
                SELECT chat_code FROM chats WHERE task_id = ?
            )
            ORDER BY cm.created_at
        """, (task_id, ))

        messages = cursor.fetchall()
        conn.close()

        if not messages:
            keyboard = [[
                InlineKeyboardButton(
                    "🔙 Назад", callback_data=f"dispute_details_{task_id}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"💬 <b>ІСТОРІЯ ЧАТУ - ЗАВДАННЯ #{task_id}</b>\n🕐 {get_kyiv_time()}\n\n❌ Повідомлень не знайдено",
                reply_markup=reply_markup,
                parse_mode='HTML')
            return

        # Format messages for display with improved readability
        text = f"💬 <b>ІСТОРІЯ ЧАТУ - ЗАВДАННЯ #{task_id}</b>\n🕐 {get_kyiv_time()}\n\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, msg in enumerate(messages):
            role_emoji = "🛒" if msg['sender_role'] == 'customer' else "⚡"
            role_name = "Замовник" if msg[
                'sender_role'] == 'customer' else "Виконавець"
            username = msg['username'] or f"ID:{msg['sender_id']}"

            # Format timestamp
            timestamp = msg['created_at'][:16] if msg[
                'created_at'] else "Невідомо"

            text += f"┌ {role_emoji} <b>{role_name}</b> ({username})\n"
            text += f"├ 🕐 {timestamp}\n"
            text += f"└ 💬 {msg['message_text']}\n"

            # Add separator except for last message
            if i < len(messages) - 1:
                text += "\n─────────────────────────────\n\n"

            # Prevent message from being too long
            if len(text) > 3500:
                text += "\n\n... (показано перші повідомлення)\n\n"
                break

        keyboard = [[
            InlineKeyboardButton("📎 Файли чату",
                                 callback_data=f"chat_files_{task_id}")
        ],
                    [
                        InlineKeyboardButton(
                            "🔙 Назад",
                            callback_data=f"dispute_details_{task_id}")
                    ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing chat history: {e}")
        keyboard = [[
            InlineKeyboardButton("🔙 Назад", callback_data="disputes")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ Помилка завантаження історії чату",
                                      reply_markup=reply_markup)


async def show_chat_files(query: CallbackQuery,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show files from chat for dispute resolution"""
    try:
        parts = query.data.split("_")
        task_id = int(parts[2])
        page = int(parts[3])

        conn = get_db_connection()
        cursor = conn.cursor()

        # Get chat code for this task
        cursor.execute("SELECT chat_code FROM chats WHERE task_id = ?",
                       (task_id, ))
        chat_result = cursor.fetchone()

        if not chat_result:
            text = f"""
📎 <b>ФАЙЛИ ЧАТУ - ЗАВДАННЯ #{task_id}</b>
🕐 {get_kyiv_time()}

❌ Чат не знайдено
            """
            keyboard = [[
                InlineKeyboardButton("🔙 Назад до історії",
                                     callback_data=f"chat_history_{task_id}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text,
                                          reply_markup=reply_markup,
                                          parse_mode='HTML')
            conn.close()
            return

        chat_code = chat_result['chat_code']

        # Get all chat files with message text
        cursor.execute(
            """
            SELECT cf.file_name, cf.file_size, cf.sender_role, cf.created_at,
                   cm.message_text
            FROM chat_files cf
            LEFT JOIN chat_messages cm ON cf.chat_code = cm.chat_code 
                AND cf.sender_id = cm.sender_id 
                AND cf.file_name = cm.file_name
            WHERE cf.chat_code = ?
            ORDER BY cf.created_at
        """, (chat_code, ))
        files = cursor.fetchall()

        conn.close()

        if not files:
            text = f"""
📎 <b>ФАЙЛИ ЧАТУ - ЗАВДАННЯ #{task_id}</b>
🕐 {get_kyiv_time()}

❌ Файлів у чаті не знайдено
            """
            keyboard = [[
                InlineKeyboardButton("🔙 Назад до історії",
                                     callback_data=f"chat_history_{task_id}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text,
                                          reply_markup=reply_markup,
                                          parse_mode='HTML')
            return

        # Show current file
        if page >= len(files):
            page = 0
        elif page < 0:
            page = len(files) - 1

        file_dict = dict(files[page])
        role = "Замовник" if file_dict[
            'sender_role'] == 'customer' else "Виконавець"
        file_size_mb = (file_dict.get('file_size', 0) or 0) / (1024 * 1024)
        message_text = file_dict.get('message_text', '')

        text = f"""
📎 <b>ФАЙЛ {page + 1} з {len(files)} - ЗАВДАННЯ #{task_id}</b>
🕐 {get_kyiv_time()}

📄 <b>Назва файлу:</b> {file_dict['file_name']}
📅 <b>Дата:</b> {file_dict['created_at'][:16]}
👤 <b>Відправник:</b> {role}
📊 <b>Розмір:</b> {file_size_mb:.2f} MB

💬 <b>Прикріплений текст:</b>
{message_text if message_text else 'Текст не додано'}
        """

        keyboard = []

        # Navigation buttons
        nav_buttons = []
        if len(files) > 1:
            prev_page = page - 1 if page > 0 else len(files) - 1
            next_page = page + 1 if page < len(files) - 1 else 0
            nav_buttons = [
                InlineKeyboardButton(
                    "⬅️ Назад",
                    callback_data=f"chat_files_{task_id}_{prev_page}"),
                InlineKeyboardButton(
                    "➡️ Далі",
                    callback_data=f"chat_files_{task_id}_{next_page}")
            ]

        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.extend([[
            InlineKeyboardButton("📄 Історія чату",
                                 callback_data=f"chat_history_{task_id}")
        ],
                         [
                             InlineKeyboardButton(
                                 "🔙 Назад до спору",
                                 callback_data="active_disputes")
                         ]])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing chat files: {e}")
        await query.edit_message_text("❌ Помилка завантаження файлів чату")


async def show_current_chat_file(query: CallbackQuery,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current chat file with navigation"""
    try:
        files = context.user_data.get('chat_files', [])
        current_index = context.user_data.get('current_file_index', 0)
        task_id = context.user_data.get('task_id')

        if not files or current_index >= len(files):
            keyboard = [[
                InlineKeyboardButton(
                    "🔙 Назад", callback_data=f"dispute_details_{task_id}")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("❌ Файл не знайдено",
                                          reply_markup=reply_markup)
            return

        file_info = files[current_index]
        role_emoji = "🛒" if file_info.get('sender_role') == 'customer' else "⚡"
        role_name = "Замовник" if file_info.get(
            'sender_role') == 'customer' else "Виконавець"
        username = file_info.get(
            'username') or f"ID:{file_info.get('sender_id', 'Невідомо')}"
        timestamp = file_info.get(
            'created_at',
            '')[:16] if file_info.get('created_at') else "Невідомо"

        # Extract file name from message text or file_name field
        message_text = file_info.get('message_text', '') or ""
        file_name = file_info.get('file_name') or "Невідомий файл"
        caption_text = ""

        if "📎" in message_text:
            parts = message_text.split("📎")
            if len(parts) > 1:
                file_part = parts[1].strip()
                if "💬" in file_part:
                    # Has caption
                    file_caption_parts = file_part.split("💬")
                    extracted_name = file_caption_parts[0].strip()
                    if extracted_name and not extracted_name.startswith('('):
                        file_name = extracted_name
                    caption_text = file_caption_parts[1].strip() if len(
                        file_caption_parts) > 1 else ""
                else:
                    extracted_name = file_part.strip()
                    if extracted_name and not extracted_name.startswith('('):
                        file_name = extracted_name

        text = f"📎 <b>ФАЙЛ ЧАТУ #{current_index + 1}/{len(files)}</b>\n"
        text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"📋 <b>Завдання:</b> #{task_id}\n"
        text += f"🕐 <b>Час надсилання:</b> {timestamp}\n\n"
        text += f"┌ {role_emoji} <b>Відправник:</b> {role_name}\n"
        text += f"├ 👤 <b>Користувач:</b> {username}\n"
        text += f"└ 📄 <b>Файл:</b> {file_name}\n"

        if caption_text:
            text += f"\n💬 <b>Прикріплений текст:</b>\n{caption_text}"

        # Navigation buttons
        nav_buttons = []
        if current_index > 0:
            nav_buttons.append(
                InlineKeyboardButton("◀️ Попередній",
                                     callback_data="chat_file_prev"))
        if current_index < len(files) - 1:
            nav_buttons.append(
                InlineKeyboardButton("Наступний ▶️",
                                     callback_data="chat_file_next"))

        keyboard = []
        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.extend([[
            InlineKeyboardButton("💬 Історія чату",
                                 callback_data=f"chat_history_{task_id}")
        ],
                         [
                             InlineKeyboardButton(
                                 "🔙 Назад",
                                 callback_data=f"dispute_details_{task_id}")
                         ]])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing current chat file: {e}")
        keyboard = [[
            InlineKeyboardButton("🔙 Назад", callback_data="disputes")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ Помилка показу файлу",
                                      reply_markup=reply_markup)


async def handle_cleanup_old_data(query, context) -> None:
    """Handle cleanup of old data"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Clean old completed tasks (older than 30 days)
        cursor.execute("""
            DELETE FROM tasks 
            WHERE status = 'completed' AND created_at < datetime('now', '-30 days')
        """)
        deleted_tasks = cursor.rowcount

        # Clean old chat messages (older than 60 days)
        cursor.execute("""
            DELETE FROM chat_messages 
            WHERE created_at < datetime('now', '-60 days')
        """)
        deleted_messages = cursor.rowcount

        # Clean old resolved disputes (older than 90 days)
        cursor.execute("""
            DELETE FROM disputes 
            WHERE status = 'resolved' AND created_at < datetime('now', '-90 days')
        """)
        deleted_disputes = cursor.rowcount

        conn.commit()
        conn.close()

        text = f"""
🗑 <b>ОЧИЩЕННЯ ЗАВЕРШЕНО</b>
🕐 {get_kyiv_time()}

✅ <b>Видалено:</b>
• Завдання: {deleted_tasks}
• Повідомлення: {deleted_messages}
• Спори: {deleted_disputes}

🧹 Стара інформація очищена
        """

        keyboard = [[
            InlineKeyboardButton("🔧 Обслуговування",
                                 callback_data="system_maintenance")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error cleaning old data: {e}")
        await query.edit_message_text("❌ Помилка очищення даних")


async def handle_check_database(query, context) -> None:
    """Handle database integrity check"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        issues = []

        # Check for orphaned tasks
        cursor.execute("""
            SELECT COUNT(*) FROM tasks t
            LEFT JOIN users c ON t.customer_id = c.user_id
            WHERE c.user_id IS NULL
        """)
        orphaned_customers = cursor.fetchone()[0]
        if orphaned_customers > 0:
            issues.append(f"Завдання без замовників: {orphaned_customers}")

        # Check for negative balances
        cursor.execute("SELECT COUNT(*) FROM users WHERE balance < 0")
        negative_balances = cursor.fetchone()[0]
        if negative_balances > 0:
            issues.append(f"Негативні баланси: {negative_balances}")

        # Check for excessive frozen balances
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE frozen_balance > balance + 1000")
        excessive_frozen = cursor.fetchone()[0]
        if excessive_frozen > 0:
            issues.append(f"Надмірно заморожено: {excessive_frozen}")

        conn.close()

        text = f"""
🔍 <b>ПЕРЕВІРКА БАЗИ ДАНИХ</b>
🕐 {get_kyiv_time()}

        """

        if issues:
            text += "⚠️ <b>Знайдені проблеми:</b>\n"
            for issue in issues:
                text += f"• {issue}\n"
        else:
            text += "✅ <b>Проблем не знайдено</b>\nБаза даних в порядку"

        keyboard = [[
            InlineKeyboardButton("🔧 Обслуговування",
                                 callback_data="system_maintenance")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error checking database: {e}")
        await query.edit_message_text("❌ Помилка перевірки бази даних")


async def handle_database_stats(query, context) -> None:
    """Handle database statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Table sizes
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM tasks")
        tasks_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM chat_messages")
        messages_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM disputes")
        disputes_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reviews")
        reviews_count = cursor.fetchone()[0]

        # Database size (approximate)
        cursor.execute("PRAGMA page_count")
        page_count = cursor.fetchone()[0]
        cursor.execute("PRAGMA page_size")
        page_size = cursor.fetchone()[0]
        db_size_mb = (page_count * page_size) / (1024 * 1024)

        conn.close()

        text = f"""
📊 <b>СТАТИСТИКА БАЗИ ДАНИХ</b>
🕐 {get_kyiv_time()}

📁 <b>Розмір БД:</b> {db_size_mb:.2f} MB

📊 <b>Кількість записів:</b>
• Користувачі: {users_count:,}
• Завдання: {tasks_count:,}
• Повідомлення: {messages_count:,}
• Спори: {disputes_count:,}
• Відгуки: {reviews_count:,}

💾 <b>Технічні дані:</b>
• Сторінки: {page_count:,}
• Розмір сторінки: {page_size:,} байт
        """

        keyboard = [[
            InlineKeyboardButton("🔧 Обслуговування",
                                 callback_data="system_maintenance")
        ], [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text,
                                      reply_markup=reply_markup,
                                      parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        await query.edit_message_text("❌ Помилка отримання статистики БД")


async def show_flvs_management(query, context) -> None:
    """Show FLVS (Full Link Verification System) management interface"""
    try:
        # Import FLVS module
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from check_pas import FLVSAnalyzer
        from database import get_link_analysis_stats

        # Get FLVS statistics
        stats = get_link_analysis_stats()
        
        text = f"""
🛡️ <b>FLVS - СИСТЕМА ПОВНОЇ ПЕРЕВІРКИ ПОСИЛАНЬ</b>
🕐 {get_kyiv_time()}

📊 <b>СТАТИСТИКА FLVS:</b>
• Всього проаналізовано: {stats.get('total_analyzed', 0)}
• Безпечних посилань: {stats.get('safe_links', 0)}
• Небезпечних посилань: {stats.get('unsafe_links', 0)}
• Фішингових атак: {stats.get('phishing_detected', 0)}
• Спроб крадіжки ТГ: {stats.get('telegram_theft_detected', 0)}

🔍 <b>АНАЛІЗ ОСТАННІХ 24 ГОДИН:</b>
• Перевірено посилань: {stats.get('links_24h', 0)}
• Заблоковано небезпечних: {stats.get('blocked_24h', 0)}
• Рівень загрози: {get_threat_level(stats)}

⚙️ <b>НАЛАШТУВАННЯ FLVS:</b>
• ✅ Автоматична перевірка активна
• ✅ 6-точкова перевірка безпеки
• ✅ Виявлення фішингу включено
• ✅ Захист від крадіжки ТГ включено
• ✅ Перевірка віку доменів активна
• ✅ Аналіз перенаправлень включено

🛠️ <b>ФУНКЦІЇ СИСТЕМИ:</b>
1️⃣ Перевірка віку домену
2️⃣ Аналіз схожості з відомими ресурсами  
3️⃣ Відстеження перенаправлень
4️⃣ Виявлення збору даних
5️⃣ Детекція фішингу/вірусів
6️⃣ Захист від крадіжки ТГ акаунтів
        """

        keyboard = [
            [
                InlineKeyboardButton("📊 Детальна статистика", 
                                   callback_data="flvs_detailed_stats")
            ],
            [
                InlineKeyboardButton("🔗 Тестувати посилання", 
                                   callback_data="flvs_test_link"),
                InlineKeyboardButton("📋 Журнал загроз", 
                                   callback_data="flvs_threat_log")
            ],
            [
                InlineKeyboardButton("⚙️ Налаштування FLVS", 
                                   callback_data="flvs_settings"),
                InlineKeyboardButton("🛡️ Довірені домени", 
                                   callback_data="flvs_trusted_domains")
            ],
            [
                InlineKeyboardButton("🚫 Заблоковані домени", 
                                   callback_data="flvs_blocked_domains"),
                InlineKeyboardButton("🔄 Очистити статистику", 
                                   callback_data="flvs_clear_stats")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing FLVS management: {e}")
        await query.edit_message_text(f"❌ Помилка завантаження FLVS: {str(e)}")


async def handle_flvs_callback(query, data, context):
    """Handle FLVS management callbacks"""
    try:
        if data == "flvs_detailed_stats":
            await show_flvs_detailed_stats(query, context)
        elif data == "flvs_test_link":
            await show_flvs_test_interface(query, context)
        elif data == "flvs_threat_log":
            await show_flvs_threat_log(query, context)
        elif data == "flvs_settings":
            await show_flvs_settings(query, context)
        elif data == "flvs_trusted_domains":
            await show_flvs_trusted_domains(query, context)
        elif data == "flvs_blocked_domains":
            await show_flvs_blocked_domains(query, context)
        elif data == "flvs_clear_stats":
            await handle_flvs_clear_stats(query, context)
        elif data.startswith("flvs_test_"):
            await handle_flvs_test_result(query, data, context)
    except Exception as e:
        logger.error(f"Error handling FLVS callback: {e}")
        await query.edit_message_text(f"❌ Помилка: {str(e)}")


async def show_flvs_detailed_stats(query, context):
    """Show detailed FLVS statistics"""
    try:
        from database import get_link_analysis_stats
        
        stats = get_link_analysis_stats()
        
        text = f"""
📊 <b>ДЕТАЛЬНА СТАТИСТИКА FLVS</b>
🕐 {get_kyiv_time()}

🔢 <b>ЗАГАЛЬНІ ПОКАЗНИКИ:</b>
• Всього перевірено: {stats.get('total_analyzed', 0)}
• Безпечних: {stats.get('safe_links', 0)} ({get_percentage(stats.get('safe_links', 0), stats.get('total_analyzed', 0))}%)
• Небезпечних: {stats.get('unsafe_links', 0)} ({get_percentage(stats.get('unsafe_links', 0), stats.get('total_analyzed', 0))}%)

🎯 <b>ВИЯВЛЕНІ ЗАГРОЗИ:</b>
• Фішингові сайти: {stats.get('phishing_detected', 0)}
• Крадіжка ТГ акаунтів: {stats.get('telegram_theft_detected', 0)}
• Збір персональних даних: {stats.get('data_harvesting_detected', 0)}
• Підозрілі перенаправлення: {stats.get('suspicious_redirects', 0)}
• Молоді домени (<30 днів): {stats.get('new_domains_detected', 0)}
• Typosquatting атаки: {stats.get('typosquatting_detected', 0)}

📈 <b>ДИНАМІКА ЗА ПЕРІОДИ:</b>
• Сьогодні: {stats.get('links_today', 0)} перевірок
• Цього тижня: {stats.get('links_week', 0)} перевірок  
• Цього місяця: {stats.get('links_month', 0)} перевірок

🛡️ <b>ЕФЕКТИВНІСТЬ СИСТЕМИ:</b>
• Точність виявлення: {get_accuracy_score(stats)}%
• Швидкість аналізу: <2 секунди
• Помилкових спрацьовувань: {stats.get('false_positives', 0)}
• Пропущених загроз: {stats.get('false_negatives', 0)}

⚡ <b>НАЙЧАСТІШІ ЗАГРОЗИ:</b>
• Фішинг Telegram: {stats.get('telegram_phishing', 0)}
• Фальшиві сайти обміну крипто: {stats.get('crypto_scams', 0)}
• Вірусні файли: {stats.get('malware_detected', 0)}
• Підозрілі скорочувачі: {stats.get('suspicious_shorteners', 0)}
        """

        keyboard = [
            [InlineKeyboardButton("📋 Експорт звіту", callback_data="flvs_export_report")],
            [InlineKeyboardButton("🔄 Оновити", callback_data="flvs_detailed_stats")],
            [InlineKeyboardButton("🔙 Назад", callback_data="flvs_management")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing FLVS detailed stats: {e}")
        await query.edit_message_text("❌ Помилка завантаження статистики")


async def show_flvs_test_interface(query, context):
    """Show FLVS link testing interface"""
    text = f"""
🔗 <b>ТЕСТУВАННЯ ПОСИЛАНЬ ЧЕРЕЗ FLVS</b>
🕐 {get_kyiv_time()}

Надішліть посилання для повного аналізу системою FLVS.
Система проведе 6-точкову перевірку безпеки:

🔍 <b>ЩО БУДЕ ПЕРЕВІРЕНО:</b>
1️⃣ Вік домену та історія реєстрації
2️⃣ Схожість з відомими ресурсами  
3️⃣ Аналіз ланцюжка перенаправлень
4️⃣ Виявлення збору особистих даних
5️⃣ Скануванння на фішинг/віруси
6️⃣ Перевірка на крадіжку ТГ акаунтів

💡 <b>ПРИКЛАДИ ДЛЯ ТЕСТУВАННЯ:</b>
• https://telegram.org
• https://google.com
• https://github.com

⚠️ <b>УВАГА:</b> Не тестуйте посилання, в безпеці яких ви не впевнені!
    """

    keyboard = [
        [InlineKeyboardButton("📊 Останні результати", callback_data="flvs_last_tests")],
        [InlineKeyboardButton("🔙 Назад", callback_data="flvs_management")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    # Set the context to await FLVS testing
    context.user_data['awaiting_flvs_test'] = True


async def show_security_management(query, context):
    """Show security management interface"""
    try:
        text = f"""
🔐 <b>УПРАВЛІННЯ БЕЗПЕКОЮ СИСТЕМИ</b>
🕐 {get_kyiv_time()}

🛡️ <b>АКТИВНІ СИСТЕМИ БЕЗПЕКИ:</b>
• ✅ FLVS - повна перевірка посилань
• ✅ Антифішинг система  
• ✅ Захист від крадіжки акаунтів
• ✅ Моніторинг підозрілої активності
• ✅ Автоматичне блокування загроз
• ✅ Логування всіх інцидентів

⚡ <b>СТАТИСТИКА БЕЗПЕКИ:</b>
• Заблоковано загроз сьогодні: 0
• Активних інцидентів: 0
• Рівень загрози: 🟢 Низький

🔧 <b>НАЛАШТУВАННЯ:</b>
• Автоматичне блокування: Увімкнено
• Сповіщення адміна: Увімкнено  
• Детальне логування: Увімкнено
• Карантин файлів: Увімкнено
        """

        keyboard = [
            [
                InlineKeyboardButton("🚨 Журнал інцидентів", 
                                   callback_data="security_incidents"),
                InlineKeyboardButton("🛡️ Налаштування", 
                                   callback_data="security_settings")
            ],
            [
                InlineKeyboardButton("📊 Звіт безпеки", 
                                   callback_data="security_report"),
                InlineKeyboardButton("🔄 Оновити статус", 
                                   callback_data="security_refresh")
            ],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing security management: {e}")
        await query.edit_message_text(f"❌ Помилка: {str(e)}")


def get_threat_level(stats):
    """Calculate threat level based on statistics"""
    unsafe_ratio = 0
    total = stats.get('total_analyzed', 0)
    
    if total > 0:
        unsafe = stats.get('unsafe_links', 0)
        unsafe_ratio = unsafe / total
    
    if unsafe_ratio >= 0.3:
        return "🔴 Високий"
    elif unsafe_ratio >= 0.1:
        return "🟡 Середній"
    else:
        return "🟢 Низький"


def get_percentage(value, total):
    """Calculate percentage"""
    if total == 0:
        return 0
    return round((value / total) * 100, 1)


def get_accuracy_score(stats):
    """Calculate accuracy score"""
    total = stats.get('total_analyzed', 0)
    if total == 0:
        return 100
    
    false_positives = stats.get('false_positives', 0)
    false_negatives = stats.get('false_negatives', 0)
    accuracy = ((total - false_positives - false_negatives) / total) * 100
    return round(accuracy, 1)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input for FLVS testing and other admin operations"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return
    
    text = update.message.text.strip()
    
    # Check if waiting for FLVS link testing
    if context.user_data and context.user_data.get('awaiting_flvs_test'):
        await handle_flvs_link_test(update, context, text)
        return
    
    # Handle user search
    if text and (text.isdigit() or text.startswith('@')):
        await handle_user_search_input(update, context, text)


async def handle_flvs_link_test(update, context, url):
    """Handle FLVS link testing"""
    try:
        # Clear the awaiting state
        context.user_data['awaiting_flvs_test'] = False
        
        # Import FLVS
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from check_pas import analyze_link
        
        # Send processing message
        processing_msg = await update.message.reply_text("🔍 Аналізую посилання через FLVS...")
        
        # Analyze the link
        result = analyze_link(url)
        
        # Format the result
        if result.get('status') == 'invalid_url':
            await processing_msg.edit_text("❌ Невірний формат посилання")
            return
        
        safety_score = result.get('safety_score', 0)
        is_safe = result.get('is_safe', False)
        recommendation = result.get('recommendation', 'Невідомо')
        
        # Get detailed analysis
        domain_age = result.get('domain_age', {})
        domain_similarity = result.get('domain_similarity', {})
        redirects = result.get('redirects', {})
        data_harvesting = result.get('data_harvesting', {})
        phishing_malware = result.get('phishing_malware', {})
        telegram_theft = result.get('telegram_theft', {})
        
        # Create detailed report
        text = f"""
🛡️ <b>ЗВІТ FLVS ПРО АНАЛІЗ ПОСИЛАННЯ</b>
🕐 {get_kyiv_time()}

🔗 <b>URL:</b> {url[:100]}{'...' if len(url) > 100 else ''}

📊 <b>ЗАГАЛЬНА ОЦІНКА:</b>
🛡️ Рівень безпеки: {safety_score*100:.1f}%
✅ Безпечний: {'Так' if is_safe else 'НІ'}
💡 Рекомендація: {recommendation}

🔍 <b>ДЕТАЛЬНИЙ АНАЛІЗ:</b>

1️⃣ <b>Вік домену:</b>
{format_domain_age_analysis(domain_age)}

2️⃣ <b>Схожість з відомими ресурсами:</b>
{format_similarity_analysis(domain_similarity)}

3️⃣ <b>Перенаправлення:</b>
{format_redirects_analysis(redirects)}

4️⃣ <b>Збір даних:</b>
{format_data_harvesting_analysis(data_harvesting)}

5️⃣ <b>Фішинг/Шкідливий код:</b>
{format_phishing_analysis(phishing_malware)}

6️⃣ <b>Крадіжка Telegram:</b>
{format_telegram_theft_analysis(telegram_theft)}
        """
        
        keyboard = [
            [InlineKeyboardButton("📊 Зберегти звіт", callback_data=f"flvs_save_report_{hash(url)}")],
            [InlineKeyboardButton("🔗 Тестувати інше", callback_data="flvs_test_link")],
            [InlineKeyboardButton("🔙 Назад", callback_data="flvs_management")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await processing_msg.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        
        # Log the analysis
        from database import log_link_analysis
        log_link_analysis(
            update.effective_user.id, 
            'ADMIN_TEST', 
            url, 
            url, 
            int(safety_score * 100), 
            is_safe, 
            f"FLVS Analysis: {recommendation}",
            None  # chat_code
        )
        
    except Exception as e:
        logger.error(f"Error in FLVS link test: {e}")
        await update.message.reply_text(f"❌ Помилка аналізу: {str(e)}")


def format_domain_age_analysis(domain_age):
    """Format domain age analysis"""
    if domain_age.get('status') != 'success':
        return "❌ Не вдалося визначити"
    
    age_days = domain_age.get('age_days', 0)
    creation_date = domain_age.get('creation_date', 'Невідомо')
    is_new = domain_age.get('is_new', False)
    is_very_new = domain_age.get('is_very_new', False)
    
    status = "🔴 Дуже новий" if is_very_new else "🟡 Новий" if is_new else "✅ Зрілий"
    
    return f"• Вік: {age_days} днів ({creation_date})\n• Статус: {status}"


def format_similarity_analysis(similarity):
    """Format similarity analysis"""
    if similarity.get('status') != 'success':
        return "❌ Не вдалося перевірити"
    
    is_suspicious = similarity.get('is_suspicious', False)
    similarities = similarity.get('similarities', [])
    
    if not is_suspicious:
        return "✅ Схожості з відомими ресурсами не виявлено"
    
    result = "🔴 Виявлено підозрілу схожість:\n"
    for sim in similarities[:3]:
        trusted = sim.get('trusted_domain', '')
        risk = sim.get('risk_level', 'medium')
        sim_type = sim.get('similarity_type', 'similarity')
        result += f"  • {trusted} ({risk}, {sim_type})\n"
    
    return result


def format_redirects_analysis(redirects):
    """Format redirects analysis"""
    if redirects.get('status') != 'success':
        return "❌ Не вдалося перевірити"
    
    has_redirects = redirects.get('has_redirects', False)
    redirect_count = redirects.get('redirect_count', 0)
    is_suspicious = redirects.get('is_suspicious', False)
    
    if not has_redirects:
        return "✅ Перенаправлень не виявлено"
    
    status = "🔴 Підозрілі" if is_suspicious else "✅ Нормальні"
    return f"• Кількість: {redirect_count}\n• Статус: {status}"


def format_data_harvesting_analysis(data_harvesting):
    """Format data harvesting analysis"""
    if data_harvesting.get('status') != 'success':
        return "❌ Не вдалося перевірити"
    
    is_suspicious = data_harvesting.get('is_suspicious', False)
    forms_count = data_harvesting.get('forms_count', 0)
    uses_https = data_harvesting.get('uses_https', False)
    
    https_status = "✅" if uses_https else "🔴"
    data_status = "🔴 Підозрілий збір даних" if is_suspicious else "✅ Безпечно"
    
    return f"• HTTPS: {https_status}\n• Форми: {forms_count}\n• Статус: {data_status}"


def format_phishing_analysis(phishing):
    """Format phishing analysis"""
    if phishing.get('status') != 'success':
        return "❌ Не вдалося перевірити"
    
    is_phishing = phishing.get('is_phishing', False)
    is_suspicious = phishing.get('is_suspicious', False)
    risk_score = phishing.get('risk_score', 0)
    
    if is_phishing:
        return f"🔴 Фішинг виявлено (ризик: {risk_score*100:.1f}%)"
    elif is_suspicious:
        return f"🟡 Підозрілий контент (ризик: {risk_score*100:.1f}%)"
    else:
        return "✅ Фішинг не виявлено"


def format_telegram_theft_analysis(telegram_theft):
    """Format Telegram theft analysis"""
    if telegram_theft.get('status') != 'success':
        return "❌ Не вдалося перевірити"
    
    is_theft = telegram_theft.get('is_telegram_theft', False)
    is_suspicious = telegram_theft.get('is_suspicious', False)
    risk_score = telegram_theft.get('risk_score', 0)
    
    if is_theft:
        return f"🔴 Загроза крадіжки ТГ (ризик: {risk_score*100:.1f}%)"
    elif is_suspicious:
        return f"🟡 Підозрілий контент (ризик: {risk_score*100:.1f}%)"
    else:
        return "✅ Загроз для ТГ не виявлено"


async def handle_user_search_input(update, context, search_text):
    """Handle user search input"""
    try:
        # Basic user search functionality
        user_id = None
        username = None
        
        if search_text.isdigit():
            user_id = int(search_text)
        elif search_text.startswith('@'):
            username = search_text[1:]
        else:
            username = search_text
        
        from database import get_user_by_id, get_user_by_username
        
        user = None
        if user_id:
            user = get_user_by_id(user_id)
        elif username:
            user = get_user_by_username(username)
        
        if user:
            await update.message.reply_text(f"✅ Знайдено користувача: {user.get('username', 'N/A')} (ID: {user.get('user_id', 'N/A')})")
        else:
            await update.message.reply_text("❌ Користувача не знайдено")
            
    except Exception as e:
        logger.error(f"Error searching user: {e}")
        await update.message.reply_text("❌ Помилка пошуку користувача")


def main():
    """Start the admin bot"""
    # Initialize @fezerstop as highest level admin with both ID and username
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if fezerstop user exists by ID
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?",
                       (5857065034, ))
        if not cursor.fetchone():
            # Create fezerstop user with Level 5 admin
            cursor.execute(
                """
                INSERT INTO users (user_id, username, balance, rating, is_executor, is_admin, admin_level, created_at)
                VALUES (?, ?, 0.0, 5.0, 0, 1, 5, datetime('now'))
            """, (5857065034, "fezerstop"))
            logger.info("Created @fezerstop user with Level 5 admin")
        else:
            # Update existing user to ensure proper admin status and username
            cursor.execute(
                """
                UPDATE users SET username = ?, is_admin = 1, admin_level = 5
                WHERE user_id = ?
            """, ("fezerstop", 5857065034))
            logger.info("Updated @fezerstop to Level 5 admin")

        # Ensure any existing user with username 'fezerstop' gets proper admin status
        cursor.execute(
            """
            UPDATE users SET is_admin = 1, admin_level = 5
            WHERE username = ? AND user_id != ?
        """, ("fezerstop", 5857065034))

        conn.commit()
        conn.close()
        logger.info(
            "@fezerstop (ID: 5857065034, username: fezerstop) set as highest level admin (Level 5)"
        )
    except Exception as e:
        logger.error(f"Failed to set @fezerstop as admin: {e}")

    application = Application.builder().token(ADMIN_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("disputes", disputes_command))
    application.add_handler(CommandHandler("code_pas", code_pas_command))
    application.add_handler(CommandHandler("adminssss", adminssss_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    logger.info("Rozdum Admin Bot starting...")
    application.run_polling()


if __name__ == '__main__':
    main()