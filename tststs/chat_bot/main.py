"""
Rozdum Chat Bot - Anonymous communication system
Provides secure, anonymous messaging between customers and executors
"""

import os
import logging
import asyncio
import json
import sqlite3
import sys
import httpx
import telegram
from datetime import datetime
from typing import Dict, Optional

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Configure logging with better filtering
import os
os.makedirs('../logs/chat_bot', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('../logs/chat_bot/chat_bot.log'),
        logging.StreamHandler()
    ]
)

# Disable verbose HTTP logging from httpx and telegram
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.info("✅ Chat bot logger initialized")

# Try to import file handler with fallback
try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.file_handler import handle_chat_file_upload
    logger.info("✅ File handler imported successfully")
except ImportError as e:
    logger.warning(f"⚠️ File handler not available: {e}")
    # Fallback file handler
    async def handle_chat_file_upload(update, context, chat_code, user_role):
        """Fallback file handler when utils.file_handler is not available"""
        try:
            if update.message.document:
                file_info = {
                    'original_name': update.message.document.file_name or 'unknown_file',
                    'file_size': update.message.document.file_size or 0,
                    'file_size_formatted': f"{(update.message.document.file_size or 0) / 1024:.1f} KB"
                }
            elif update.message.photo:
                file_info = {
                    'original_name': 'photo.jpg',
                    'file_size': update.message.photo[-1].file_size or 0,
                    'file_size_formatted': f"{(update.message.photo[-1].file_size or 0) / 1024:.1f} KB"
                }
            else:
                file_info = {
                    'original_name': 'media_file',
                    'file_size': 0,
                    'file_size_formatted': "Unknown size"
                }
            return file_info
        except Exception as e:
            logger.error(f"Error in fallback file handler: {e}")
            return None

# Try to import link checker and FLVS
try:
    from utils.link_checker import validate_message_links, format_link_warning, link_checker

    def check_message_links(text):
        is_safe, link_results, phishing_check = validate_message_links(text)
        return is_safe

    def has_unsafe_links(text):
        is_safe, link_results, phishing_check = validate_message_links(text)
        return not is_safe

except ImportError:
    logger.warning("⚠️ Link checker not available")
    check_message_links = None
    has_unsafe_links = None
    link_checker = None

# Import FLVS (Full Link Verification System)
try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from check_pas import FLVSAnalyzer, analyze_text_links

    def check_message_with_flvs(text):
        """Check message for links using FLVS"""
        try:
            analyzer = FLVSAnalyzer()
            urls = analyzer.extract_urls_from_text(text)
            
            if not urls:
                return True, []
            
            results = []
            for url in urls:
                result = analyzer.analyze_url(url)
                results.append(result)
            
            # Check if any links are unsafe
            unsafe_links = [r for r in results if not r.get('is_safe', False)]
            
            return len(unsafe_links) == 0, results
        except Exception as e:
            logger.error(f"FLVS error: {e}")
            return True, []  # Default to safe if FLVS fails
    
    logger.info("✅ FLVS system loaded successfully")
    
except ImportError as e:
    logger.warning(f"⚠️ FLVS not available: {e}")
    check_message_with_flvs = None

# Try to import database functions
try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from database import (get_user_reviews, get_user_rating_history, get_task_reviews, 
                             add_review, check_review_exists, get_user, get_task)
except ImportError:
    # Fallback functions
    def get_user_reviews(user_id, as_reviewer=False):
        return []
    def get_user_rating_history(user_id):
        return {}
    def get_task_reviews(task_id):
        return []
    def add_review(task_id, reviewer_id, reviewed_id, rating, comment=None):
        return False
    def check_review_exists(task_id, reviewer_id, reviewed_id):
        return False
    def get_user(user_id):
        return None
    def get_task(task_id):
        return None



# Configure event logging
event_logger = logging.getLogger('chat_events')
event_handler = logging.FileHandler('../logs/chat_bot/chat_events.log')
event_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
event_logger.addHandler(event_handler)
event_logger.setLevel(logging.INFO)
event_logger.propagate = False  # Don't propagate to root logger

# Security events logger
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)
security_handler = logging.FileHandler('security.log')
security_handler.setFormatter(logging.Formatter('%(asctime)s - SECURITY - %(message)s'))
security_logger.addHandler(security_handler)

def log_chat_event(event_type: str, user_id: int, chat_code: str = None, details: dict = None):
    """Log chat events with structured format"""
    log_data = {
        'event': event_type,
        'user_id': user_id,
        'chat_code': chat_code,
        'timestamp': datetime.now().isoformat(),
        'details': details or {}
    }
    event_logger.info(f"CHAT_EVENT: {json.dumps(log_data, ensure_ascii=False)}")

def log_security_event(event_type: str, user_id: int, details: dict = None):
    """Log security events"""
    log_data = {
        'event': event_type,
        'user_id': user_id,
        'timestamp': datetime.now().isoformat(),
        'details': details or {}
    }
    security_logger.warning(f"SECURITY_EVENT: {json.dumps(log_data, ensure_ascii=False)}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot."""
    error_msg = str(context.error)

    # Handle network errors quietly (they're temporary)
    if any(error_type in error_msg for error_type in ["httpx.ReadError", "NetworkError", "TimeoutError", "ConnectError"]):
        logger.warning(f"Network error (temporary): {error_msg}")
        return

    # Log other errors
    logger.error(f"Exception while handling an update: {context.error}")

    # Handle Telegram API conflicts gracefully
    if "Conflict" in str(context.error) and "getUpdates" in str(context.error):
        logger.warning("Bot conflict detected - another instance may be running")
        return

    # Handle other specific errors
    if "Message is not modified" in str(context.error):
        logger.warning("Attempted to edit message with same content - ignoring")
        if update.callback_query:
            await update.callback_query.answer("✅ Оновлено")
        return

    # For other errors, try to inform the user
    try:
        if update.callback_query:
            await update.callback_query.answer("❌ Виникла помилка. Спробуйте ще раз.")
        elif update.message:
            await update.message.reply_text("❌ Виникла помилка. Спробуйте ще раз.")
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}")

# Bot configuration - use dedicated chat bot token
CHAT_BOT_TOKEN = os.getenv("CHAT_BOT_TOKEN")
if not CHAT_BOT_TOKEN:
    logger.error("CHAT_BOT_TOKEN not found in environment variables")
    print("❌ CHAT_BOT_TOKEN not found in environment variables")
    sys.exit(1)

# Chat data storage
active_chats: Dict[str, Dict] = {}
user_sessions: Dict[int, str] = {}
# Track private command usage for warnings
private_command_warnings: Dict[int, int] = {}

class ChatRoles:
    CUSTOMER = "customer"
    EXECUTOR = "executor"

class ChatStatus:
    WAITING = "waiting"
    CONNECTED = "connected"
    COMPLETED = "completed"
    DISPUTED = "disputed"

def get_db_connection():
    """Get database connection with row factory."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rozdum.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def save_user_session(user_id: int, chat_code: str):
    """Save user session to database for persistence"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                user_id INTEGER PRIMARY KEY,
                chat_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO chat_sessions (user_id, chat_code)
            VALUES (?, ?)
        """, (user_id, chat_code))

        conn.commit()
        conn.close()

        # Enhanced logging
        log_chat_event('SESSION_SAVED', user_id, chat_code, {
            'action': 'session_created',
            'success': True
        })
        logger.info(f"✅ Session saved: user {user_id} → chat {chat_code}")

    except Exception as e:
        log_chat_event('SESSION_SAVE_ERROR', user_id, chat_code, {
            'action': 'session_creation_failed',
            'error': str(e)
        })
        logger.error(f"❌ Error saving session for user {user_id}: {e}")

def load_user_session(user_id: int) -> Optional[str]:
    """Load user session from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT chat_code FROM chat_sessions 
            WHERE user_id = ?
        """, (user_id,))

        result = cursor.fetchone()
        conn.close()

        return result['chat_code'] if result else None

    except Exception as e:
        logger.error(f"Error loading user session: {e}")
        return None

def remove_user_session(user_id: int):
    """Remove user session from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,))

        conn.commit()
        conn.close()
        logger.info(f"Removed session for user {user_id}")

    except Exception as e:
        logger.error(f"Error removing user session: {e}")

def save_chat_message(chat_code: str, sender_id: int, sender_role: str, 
                     message_text: str, message_type: str = "text", 
                     file_name: str = None, file_size: int = None):
    """Save chat message to database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO chat_messages 
            (chat_code, sender_id, sender_role, message_text, message_type, file_name, file_size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (chat_code, sender_id, sender_role, message_text, message_type, file_name, file_size))

        conn.commit()
        conn.close()

        # Enhanced logging
        log_chat_event('MESSAGE_SAVED', sender_id, chat_code, {
            'sender_role': sender_role,
            'message_type': message_type,
            'message_length': len(message_text) if message_text else 0,
            'has_file': file_name is not None,
            'file_size': file_size
        })
        logger.info(f"💬 Message saved: {sender_role} → chat {chat_code} ({message_type})")

    except Exception as e:
        log_chat_event('MESSAGE_SAVE_ERROR', sender_id, chat_code, {
            'sender_role': sender_role,
            'message_type': message_type,
            'error': str(e)
        })
        logger.error(f"❌ Error saving message from {sender_role} in chat {chat_code}: {e}")

def save_chat_file(chat_code: str, sender_id: int, sender_role: str,
                  file_name: str, file_size: int, file_path: str = None):
    """Save chat file info to database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO chat_files 
            (chat_code, sender_id, sender_role, file_name, file_size, file_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_code, sender_id, sender_role, file_name, file_size, file_path))

        conn.commit()
        conn.close()

        logger.info(f"Saved file {file_name} from {sender_role} in chat {chat_code}")

    except Exception as e:
        logger.error(f"Error saving chat file: {e}")

def store_message_mapping(chat_code: str, original_msg_id: int, forwarded_msg_id: int, sender_id: int, recipient_id: int):
    """Store mapping between original and forwarded messages for reaction syncing"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_mappings (
                chat_code TEXT,
                original_msg_id INTEGER,
                forwarded_msg_id INTEGER,
                sender_id INTEGER,
                recipient_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            INSERT INTO message_mappings 
            (chat_code, original_msg_id, forwarded_msg_id, sender_id, recipient_id)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_code, original_msg_id, forwarded_msg_id, sender_id, recipient_id))

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error storing message mapping: {e}")

def get_message_mapping(chat_code: str, message_id: int):
    """Get message mapping for reaction syncing"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT original_msg_id, forwarded_msg_id, sender_id, recipient_id 
            FROM message_mappings 
            WHERE chat_code = ? AND (original_msg_id = ? OR forwarded_msg_id = ?)
        """, (chat_code, message_id, message_id))

        result = cursor.fetchone()
        conn.close()

        return result

    except Exception as e:
        logger.error(f"Error getting message mapping: {e}")
        return None

async def notify_admin_bot(message: str, task_id: int = None):
    """Send notification to admin bot"""
    try:
        import httpx

        admin_bot_token = os.getenv("ADMIN_BOT_TOKEN", "")
        admin_user_id = os.getenv("ADMIN_ID", "")

        if admin_bot_token and admin_user_id:
            url = f"https://api.telegram.org/bot{admin_bot_token}/sendMessage"

            data = {
                "chat_id": admin_user_id,
                "text": message,
                "parse_mode": "HTML"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data)

            if response.status_code == 200:
                logger.info("Admin notification sent successfully")
            else:
                logger.warning(f"Failed to send admin notification: {response.status_code}")

    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")

def get_user_role_in_chat(user_id: int, chat_code: str) -> Optional[str]:
    """Determine user's role in the chat"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT customer_id, executor_id FROM chats 
            WHERE chat_code = ? AND status = 'active'
        """, (chat_code,))
        result = cursor.fetchone()
        conn.close()

        if result:
            if result[0] == user_id:
                return ChatRoles.CUSTOMER
            elif result[1] == user_id:
                return ChatRoles.EXECUTOR
        return None
    except Exception as e:
        logger.error(f"Error getting user role: {e}")
        return None

def get_role_emoji(role: str) -> str:
    """Get emoji for user role"""
    return "🛒" if role == ChatRoles.CUSTOMER else "⚡"

def get_role_name(role: str) -> str:
    """Get localized role name"""
    return "Замовник" if role == ChatRoles.CUSTOMER else "Виконавець"

def format_tags_display(tags_json: str) -> str:
    """Format tags for display - handle both JSON and plain text"""
    try:
        if tags_json.startswith('[') and tags_json.endswith(']'):
            # Parse JSON array
            tags_list = json.loads(tags_json)
            return ", ".join(tags_list)
        else:
            # Plain text
            return tags_json
    except:
        # Fallback to original string
        return tags_json

def format_star_rating(rating: float) -> str:
    """Format rating as stars."""
    stars = "⭐" * int(rating)
    if rating - int(rating) >= 0.5:
        stars += "⭐"
    return f"{stars} ({rating:.1f})"

def format_review_date(date_str: str) -> str:
    """Format review date for display."""
    try:
        from datetime import datetime
        date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return date_obj.strftime("%d.%m.%Y")
    except:
        return date_str

async def show_rating_interface(query, chat_code: str, user_id: int, other_user_id: int, task_id: int, role: str):
    """Show rating interface for chat users."""
    task = get_task(task_id)
    if not task:
        await query.edit_message_text(
            "❌ Завдання не знайдено",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    # Check if already rated
    if check_review_exists(task_id, user_id, other_user_id):
        await query.edit_message_text(
            "✅ Ви вже оцінили цього користувача за це завдання",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    other_role = "замовника" if role == "executor" else "виконавця"

    text = f"""
⭐ <b>Оцініть {other_role}</b>

Завдання: {task.get('description', 'Без опису')[:50]}...

Оцініть якість роботи {other_role} за 5-бальною шкалою:
"""

    keyboard = []
    for rating in range(1, 6):
        stars = "⭐" * rating
        keyboard.append([InlineKeyboardButton(
            f"{stars} {rating}", 
            callback_data=f"rate_{task_id}_{other_user_id}_{rating}"
        )])

    keyboard.append([InlineKeyboardButton("📝 Оцінити з коментарем", callback_data=f"rate_comment_{task_id}_{other_user_id}")])
    keyboard.append([InlineKeyboardButton("⏭️ Пропустити", callback_data="skip_rating")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_user_rating_history(query, user_id: int, other_user_id: int):
    """Show detailed rating history for a user."""
    user = get_user(other_user_id)
    if not user:
        await query.edit_message_text(
            "❌ Користувач не знайдений",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    rating_history = get_user_rating_history(other_user_id)
    reviews = get_user_reviews(other_user_id)

    text = f"""
📊 <b>Рейтинг користувача</b>

👤 {user.get('username', 'Без імені')}
⭐ <b>Загальний рейтинг:</b> {format_star_rating(user.get('rating', 0))}
📝 <b>Кількість відгуків:</b> {user.get('reviews_count', 0)}

"""

    # Rating distribution
    if rating_history.get('rating_distribution'):
        text += "<b>📈 Розподіл оцінок:</b>\n"
        for rating in sorted(rating_history['rating_distribution'].keys(), reverse=True):
            count = rating_history['rating_distribution'][rating]
            stars = "⭐" * rating
            text += f"{stars} {rating}: {count} відгуків\n"
        text += "\n"

    # Category ratings
    if rating_history.get('category_ratings'):
        text += "<b>📂 Рейтинг за категоріями:</b>\n"
        for category_data in rating_history['category_ratings'][:3]:  # Top 3 categories
            category = category_data['category']
            avg_rating = category_data['avg_rating']
            count = category_data['count']
            text += f"• {category}: {format_star_rating(avg_rating)} ({count} відгуків)\n"
        text += "\n"

    # Recent reviews
    if reviews:
        text += "<b>📝 Останні відгуки:</b>\n"
        for review in reviews[:3]:  # Last 3 reviews
            date = format_review_date(review.get('created_at', ''))
            rating = review.get('rating', 0)
            comment = review.get('comment', '').strip()
            text += f"• {format_star_rating(rating)} - {date}"
            if comment:
                text += f"\n  💬 {comment[:50]}..."
            text += "\n"

    keyboard = [
        [InlineKeyboardButton("📝 Всі відгуки", callback_data=f"all_reviews_{other_user_id}")],
        [InlineKeyboardButton("⭐ Оцінити", callback_data=f"show_rating_{other_user_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_all_user_reviews(query, user_id: int, other_user_id: int):
    """Show all reviews for a user."""
    user = get_user(other_user_id)
    if not user:
        await query.edit_message_text(
            "❌ Користувач не знайдений",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    reviews = get_user_reviews(other_user_id)

    text = f"""
📝 <b>Всі відгуки про {user.get('username', 'Без імені')}</b>

⭐ <b>Загальний рейтинг:</b> {format_star_rating(user.get('rating', 0))}
📊 <b>Всього відгуків:</b> {len(reviews)}

"""

    if reviews:
        text += "<b>📋 Останні відгуки:</b>\n\n"
        for i, review in enumerate(reviews[:10]):  # Show last 10 reviews
            date = format_review_date(review.get('created_at', ''))
            rating = review.get('rating', 0)
            comment = review.get('comment', '').strip()
            category = review.get('category', 'Без категорії')

            text += f"<b>{i+1}.</b> {format_star_rating(rating)} - {date}\n"
            text += f"📂 {category}\n"
            if comment:
                text += f"💬 {comment}\n"
            text += "\n"
    else:
        text += "Поки що відгуків немає."

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data=f"rating_stats_{other_user_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_rating_submission(query, task_id: int, reviewed_id: int, rating: int, comment: str = None):
    """Handle rating submission."""
    user_id = query.from_user.id

    # Get task and validate
    task = get_task(task_id)
    if not task:
        await query.edit_message_text(
            "❌ Завдання не знайдено",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    # Check if user is part of this task
    if user_id not in [task['customer_id'], task['executor_id']]:
        await query.edit_message_text(
            "❌ Ви не можете оцінити цього користувача",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    # Check if already rated
    if check_review_exists(task_id, user_id, reviewed_id):
        await query.edit_message_text(
            "✅ Ви вже оцінили цього користувача за це завдання",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    # Add review
    success = add_review(task_id, user_id, reviewed_id, rating, comment)

    if success:
        reviewed_user = get_user(reviewed_id)
        role = "замовника" if reviewed_id == task['customer_id'] else "виконавця"

        text = f"""
✅ <b>Відгук залишено!</b>

Ви оцінили {role} на {rating} {'зірку' if rating == 1 else 'зірки' if rating < 5 else 'зірок'}.

{f"💬 Ваш коментар: {comment}" if comment else ""}

Дякуємо за оцінку! Це допомагає підтримувати якість платформи.
"""

        keyboard = [
            [InlineKeyboardButton("📊 Переглянути рейтинг", callback_data=f"rating_stats_{reviewed_id}")],
            [InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await query.edit_message_text(
            "❌ Помилка збереження оцінки. Спробуйте пізніше.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )

async def show_task_reviews(query, task_id: int):
    """Show all reviews for a specific task."""
    task = get_task(task_id)
    if not task:
        await query.edit_message_text(
            "❌ Завдання не знайдено",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]])
        )
        return

    reviews = get_task_reviews(task_id)

    text = f"""
📝 <b>Відгуки про завдання #{task_id}</b>

📋 <b>Опис:</b> {task.get('description', 'Без опису')[:100]}...
💰 <b>Вартість:</b> {task.get('price', 0)} грн
📊 <b>Кількість відгуків:</b> {len(reviews)}

"""

    if reviews:
        text += "<b>⭐ Відгуки:</b>\n\n"
        for i, review in enumerate(reviews):
            reviewer_name = review.get('reviewer_username', 'Без імені')
            reviewed_name = review.get('reviewed_username', 'Без імені')
            rating = review.get('rating', 0)
            comment = review.get('comment', '').strip()
            date = format_review_date(review.get('created_at', ''))

            text += f"<b>{i+1}.</b> {reviewer_name} → {reviewed_name}\n"
            text += f"⭐ {format_star_rating(rating)} - {date}\n"
            if comment:
                text += f"💬 {comment}\n"
            text += "\n"
    else:
        text += "Поки що відгуків немає."

    keyboard = [
        [InlineKeyboardButton("⭐ Залишити відгук", callback_data=f"leave_review_{task_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user_id = update.effective_user.id

    # Check if user has existing session
    saved_chat_code = load_user_session(user_id)
    if saved_chat_code:
        # Restore session
        user_sessions[user_id] = saved_chat_code

        # Get chat info
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.task_id, c.customer_id, c.executor_id, t.description, t.price 
                FROM chats c 
                JOIN tasks t ON c.task_id = t.task_id 
                WHERE c.chat_code = ? AND c.status = 'active'
            """, (saved_chat_code,))
            result = cursor.fetchone()
            conn.close()

            if result:
                task_id, customer_id, executor_id, description, price = result
                user_role = get_user_role_in_chat(user_id, saved_chat_code)

                if user_role:
                    # Restore chat
                    active_chats[saved_chat_code] = {
                        'task_id': task_id,
                        'customer_id': customer_id,
                        'executor_id': executor_id,
                        'status': ChatStatus.CONNECTED,
                        'participants': {user_id}
                    }

                    role_emoji = get_role_emoji(user_role)
                    role_name = get_role_name(user_role)

                    welcome_msg = f"""
🔄 <b>Сесію відновлено!</b>

{role_emoji} <b>Ваша роль:</b> {role_name}
📋 <b>Завдання:</b> {description[:100]}{'...' if len(description) > 100 else ''}
💰 <b>Ціна:</b> {price} грн

💬 Продовжуйте спілкування
                    """

                    keyboard = build_chat_interface(user_role, task_id)
                    await update.message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode='HTML')
                    return
        except Exception as e:
            logger.error(f"Error restoring session: {e}")

    welcome_text = """
🤝 <b>Розdum Чат</b>

Цей бот призначений для анонімного спілкування між замовником і виконавцем.

<b>Як користуватися:</b>
1️⃣ Отримайте код доступу від основного бота @RozdumBot
2️⃣ Введіть команду: <code>/private [КОД]</code>
3️⃣ Очікуйте підключення другої сторони
4️⃣ Почніть```python
 анонімне спілкування

<b>Приклад:</b> <code>/private A4B8C1</code>

💡 Ваша особистість залишається повністю анонімною
    """

    # Check if user has active task to show return button
    keyboard = []
    if user_id in user_sessions:
        chat_code = user_sessions[user_id]
        if chat_code in active_chats:
            keyboard.append([InlineKeyboardButton("🔙 Вернутися до панелі завдання", callback_data="back_to_chat")])

    keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')

async def private_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /private [code] command"""
    user_id = update.effective_user.id

    if not context.args or len(context.args) != 1:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "❌ Неправильний формат команди\n\n"
            "Використовуйте: <code>/private [КОД]</code>\n"
            "Приклад: <code>/private A4B8C1</code>",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return

    chat_code = context.args[0].upper()

    # Check if user is already in this chat
    if user_id in user_sessions and user_sessions[user_id] == chat_code:
        # Delete the /private message
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        except:
            pass

        # Track warnings
        if user_id not in private_command_warnings:
            private_command_warnings[user_id] = 0

        private_command_warnings[user_id] += 1

        # Show warning after 5 attempts
        if private_command_warnings[user_id] >= 5:
            keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ <b>Попередження!</b>\n\n"
                     "Ви вже знаходитесь в цьому чаті. Немає сенсу використовувати цю команду повторно.",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        return

    user_role = get_user_role_in_chat(user_id, chat_code)

    if not user_role:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "❌ Недійсний код або у вас немає доступу до цього чату\n\n"
            "Перевірте правильність коду або отримайте новий від @RozdumBot",
            reply_markup=reply_markup
        )
        return

    # Check if chat exists and get task info
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.task_id, c.customer_id, c.executor_id, t.description, t.price, t.tags 
            FROM chats c 
            JOIN tasks t ON c.task_id = t.task_id 
            WHERE c.chat_code = ? AND c.status = 'active'
        """, (chat_code,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("❌ Чат більше недоступний", reply_markup=reply_markup)
            return

        task_id, customer_id, executor_id, description, price, tags = result

        # Store user session in both memory and database
        user_sessions[user_id] = chat_code
        save_user_session(user_id, chat_code)

        # Initialize chat if not exists
        if chat_code not in active_chats:
            active_chats[chat_code] = {
                'task_id': task_id,
                'customer_id': customer_id,
                'executor_id': executor_id,
                'status': ChatStatus.WAITING,
                'participants': set()
            }
            log_chat_event('CHAT_INITIALIZED', user_id, chat_code, {
                'task_id': task_id,
                'customer_id': customer_id,
                'executor_id': executor_id,
                'user_role': user_role
            })

        active_chats[chat_code]['participants'].add(user_id)
        log_chat_event('USER_JOINED_CHAT', user_id, chat_code, {
            'user_role': user_role,
            'participants_count': len(active_chats[chat_code]['participants'])
        })

        role_emoji = get_role_emoji(user_role)
        role_name = get_role_name(user_role)

        # Check if both participants are connected
        chat = active_chats[chat_code]
        other_user_id = executor_id if user_role == ChatRoles.CUSTOMER else customer_id
        other_connected = other_user_id in user_sessions and len(chat['participants']) >= 2

        if other_connected:
            chat['status'] = ChatStatus.CONNECTED
            other_role = ChatRoles.EXECUTOR if user_role == ChatRoles.CUSTOMER else ChatRoles.CUSTOMER
            other_name = get_role_name(other_role)
            status_text = f"🟢 {other_name} підключився до чату!"
        else:
            status_text = "🟡 Очікування підключення другої сторони..."

        # Calculate executor earnings (price - 10% commission)
        executor_earnings = price * 0.9

        # Send welcome message
        welcome_msg = f"""🤝 <b>Анонімний чат активовано!</b>

{role_emoji} <b>Ваша роль:</b> {role_name}

📋 <b>Завдання:</b> {description[:100]}{'...' if len(description) > 100 else ''}
🏷️ <b>Теги:</b> {format_tags_display(tags)}
💰 <b>Ціна:</b> {price} грн
{f"💵 <b>Ви отримаєте:</b> {executor_earnings:.0f} грн" if user_role == ChatRoles.EXECUTOR else ""}

{status_text}

💬 Надсилайте повідомлення для спілкування з іншою стороною"""

        keyboard = build_chat_interface(user_role, task_id)
        sent_message = await update.message.reply_text(welcome_msg, reply_markup=keyboard, parse_mode='HTML')

        # Store message ID for potential later deletion (pinned messages)
        chat['main_message_id'] = sent_message.message_id

        # If other user is already connected, notify them and schedule message cleanup
        if other_connected:
            other_role = ChatRoles.EXECUTOR if user_role == ChatRoles.CUSTOMER else ChatRoles.CUSTOMER
            other_name = get_role_name(other_role)

            # Send notification to other user
            notification_msg = await context.bot.send_message(
                chat_id=other_user_id,
                text=f"🟢 <b>{other_name} підключився до чату!</b>\n\n💬 Тепер ви можете спілкуватися",
                parse_mode='HTML'
            )

            # Schedule deletion of notification message after 10 seconds
            async def delete_notification():
                await asyncio.sleep(10)
                try:
                    await context.bot.delete_message(
                        chat_id=other_user_id,
                        message_id=notification_msg.message_id
                    )

                    # Also try to unpin any old pinned messages
                    try:
                        await context.bot.unpin_chat_message(chat_id=other_user_id)
                    except:
                        pass

                except:
                    pass

            # Run deletion in background
            asyncio.create_task(delete_notification())

    except Exception as e:
        logger.error(f"Error in private command: {e}")
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("❌ Помилка підключення до чату", reply_markup=reply_markup)

def build_chat_interface(role: str, task_id: int) -> InlineKeyboardMarkup:
    """Build role-specific chat interface"""
    if role == ChatRoles.CUSTOMER:
        buttons = [
            [InlineKeyboardButton("📋 Переглянути завдання", callback_data=f"view_task_{task_id}"),
             InlineKeyboardButton("📎 Переглянути файли", callback_data=f"view_files_{task_id}")],
            [InlineKeyboardButton("⭐ Рейтинг виконавця", callback_data=f"rating_executor_{task_id}"),
             InlineKeyboardButton("📝 Відгуки завдання", callback_data=f"task_reviews_{task_id}")],
            [InlineKeyboardButton("✅ Підтвердити виконання", callback_data=f"approve_task_{task_id}")],
            [InlineKeyboardButton("⚠️ Відкрити спір", callback_data=f"open_dispute_{task_id}")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu"),
             InlineKeyboardButton("❌ Закрити чат", callback_data=f"close_chat")]
        ]
    else:  # Executor
        buttons = [
            [InlineKeyboardButton("📋 Переглянути завдання", callback_data=f"view_task_{task_id}"),
             InlineKeyboardButton("📎 Переглянути файли", callback_data=f"view_files_{task_id}")],
            [InlineKeyboardButton("⭐ Рейтинг замовника", callback_data=f"rating_customer_{task_id}"),
             InlineKeyboardButton("📝 Відгуки завдання", callback_data=f"task_reviews_{task_id}")],
            [InlineKeyboardButton("🎯 Завершити роботу", callback_data=f"complete_task_{task_id}")],
            [InlineKeyboardButton("💬 Надіслати файл", callback_data=f"send_file")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu"),
             InlineKeyboardButton("❌ Закрити чат", callback_data=f"close_chat")]
        ]

    return InlineKeyboardMarkup(buttons)

async def handle_rating_comment_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle rating comment input from user."""
    user_id = update.effective_user.id
    rating_context = context.user_data.get('rating_context', {})

    if not rating_context.get('awaiting_comment'):
        return

    text = update.message.text.strip()
    task_id = rating_context['task_id']
    reviewed_id = rating_context['reviewed_id']

    # Parse rating and comment
    parts = text.split(' ', 1)
    try:
        rating = int(parts[0])
        if rating < 1 or rating > 5:
            raise ValueError("Rating must be 1-5")

        comment = parts[1] if len(parts) > 1 else None
    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ Неправильний формат. Використовуйте:\n"
            "<code>5 Відмінна робота!</code>\n"
            "або просто <code>5</code>",
            parse_mode='HTML'
        )
        return

    # Clear context
    context.user_data['rating_context'] = {}

    # Submit rating
    success = add_review(task_id, user_id, reviewed_id, rating, comment)

    if success:
        text = f"""
✅ <b>Відгук залишено!</b>

Ваша оцінка: {rating} {'зірка' if rating == 1 else 'зірки' if rating < 5 else 'зірок'}
{f"Коментар: {comment}" if comment else ""}

Дякуємо за оцінку! Це допомагає підтримувати якість платформи.
"""
        keyboard = [
            [InlineKeyboardButton("📊 Переглянути рейтинг", callback_data=f"rating_stats_{reviewed_id}")],
            [InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text("❌ Помилка збереження оцінки. Спробуйте пізніше.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular messages in active chats"""
    user_id = update.effective_user.id

    # Check if user is waiting to provide rating comment
    if context.user_data and context.user_data.get('rating_context', {}).get('awaiting_comment'):
        await handle_rating_comment_input(update, context)
        return

    if user_id not in user_sessions:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "❌ Ви не в активному чаті\n\n"
            "Використовуйте /private [КОД] для входу в чат",
            reply_markup=reply_markup
        )
        return

    chat_code = user_sessions[user_id]
    chat = active_chats.get(chat_code)

    if not chat or chat['status'] != ChatStatus.CONNECTED:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "❌ Чат недоступний або очікує підключення другої сторони",
            reply_markup=reply_markup
        )
        return

    # Determine sender role and get recipient
    user_role = get_user_role_in_chat(user_id, chat_code)
    if not user_role:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("❌ Помилка доступу до чату", reply_markup=reply_markup)
        return

    recipient_id = chat['executor_id'] if user_role == ChatRoles.CUSTOMER else chat['customer_id']

    # Check if recipient is connected
    if recipient_id not in user_sessions:
        await update.message.reply_text(
            "⚠️ Повідомлення надіслано, але інша сторона поки не підключена"
        )
        return

    # Check for links before processing message using FLVS
    message_text_content = update.message.text
    has_links = False
    link_report = ""

    try:
        # Check if message contains links using FLVS
        if check_message_with_flvs:
            is_safe, link_results = check_message_with_flvs(message_text_content)
            
            if link_results:
                has_links = True
                
                # Check if any links are unsafe
                unsafe_links = [r for r in link_results if not r.get('is_safe', False)]
                
                if unsafe_links:
                    # Log security event with detailed FLVS analysis
                    log_security_event('FLVS_UNSAFE_LINK_BLOCKED', user_id, {
                        'chat_code': chat_code,
                        'user_role': user_role,
                        'message_preview': message_text_content[:100] + '...' if len(message_text_content) > 100 else message_text_content,
                        'unsafe_links_count': len(unsafe_links),
                        'total_links_count': len(link_results)
                    })

                    # Create detailed warning message
                    warning_text = "🚫 <b>ПОВІДОМЛЕННЯ ЗАБЛОКОВАНО FLVS!</b>\n\n"
                    warning_text += f"Виявлено {len(unsafe_links)} небезпечних посилань з {len(link_results)} загальних:\n\n"
                    
                    for i, link_result in enumerate(unsafe_links[:3]):  # Show max 3 unsafe links
                        url = link_result.get('url', 'Unknown URL')
                        safety_score = link_result.get('safety_score', 0)
                        recommendation = link_result.get('recommendation', 'Небезпечне посилання')
                        
                        warning_text += f"🔗 <b>Посилання {i+1}:</b> {url[:50]}...\n"
                        warning_text += f"🛡️ <b>Рівень безпеки:</b> {safety_score*100:.1f}%\n"
                        warning_text += f"⚠️ <b>Рекомендація:</b> {recommendation}\n\n"
                    
                    if len(unsafe_links) > 3:
                        warning_text += f"... і ще {len(unsafe_links) - 3} небезпечних посилань\n\n"
                    
                    warning_text += "Повідомлення заблоковано для вашої безпеки. Перевірте посилання та надішліть повідомлення без небезпечних URL."

                    await update.message.reply_text(warning_text, parse_mode='HTML')
                    return
                else:
                    # Safe links - create security report
                    safe_links_count = len([r for r in link_results if r.get('is_safe', False)])
                    link_report = f"\n\n🛡️ <i>FLVS: {safe_links_count} посилань перевірено ✅</i>"
                    
                    # Log safe links
                    log_security_event('FLVS_SAFE_LINKS_PASSED', user_id, {
                        'chat_code': chat_code,
                        'user_role': user_role,
                        'safe_links_count': safe_links_count,
                        'total_links_count': len(link_results)
                    })
        else:
            # Fallback to old link checker if FLVS is not available
            if check_message_links:
                is_safe = check_message_links(message_text_content)
                if not is_safe:
                    log_security_event('UNSAFE_LINK_BLOCKED', user_id, {
                        'chat_code': chat_code,
                        'user_role': user_role,
                        'message_preview': message_text_content[:100] + '...' if len(message_text_content) > 100 else message_text_content
                    })
                    await update.message.reply_text(
                        "🚫 <b>ПОВІДОМЛЕННЯ ЗАБЛОКОВАНО!</b>\n\n"
                        "Ваше повідомлення містить підозрілі посилання та не буде надіслано.\n"
                        "Будь ласка, перевірте посилання та надішліть повідомлення без небезпечних URL.",
                        parse_mode='HTML'
                    )
                    return
                    
    except Exception as e:
        logger.error(f"❌ Error checking links with FLVS: {e}")
        log_security_event('FLVS_CHECK_ERROR', user_id, {
            'chat_code': chat_code,
            'error': str(e)
        })
        # Continue without link checking if error occurs

    # Save message to database
    save_chat_message(chat_code, user_id, user_role, message_text_content)

    # Forward message with role indicator and link analysis
    role_emoji = get_role_emoji(user_role)
    message_text = f"{role_emoji} {message_text_content}"

    # Add link safety report if there were safe links
    if has_links and link_report:
        message_text += link_report

    try:
        sent_message = await context.bot.send_message(
            chat_id=recipient_id,
            text=message_text
        )

        # Set reaction on original message to show it was sent
        try:
            import httpx
            bot_token = BOT_TOKEN
            url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"

            data = {
                "chat_id": update.effective_chat.id,
                "message_id": update.message.message_id,
                "reaction": json.dumps([{"type": "emoji", "emoji": "👍"}])
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data)

            if response.status_code == 200:
                logger.info("👍 reaction set successfully")
            else:
                logger.warning(f"Failed to set reaction: {response.status_code}")

        except Exception as reaction_error:
            logger.warning(f"Could not set reaction: {reaction_error}")

    except Exception as e:
        logger.error(f"Error forwarding message: {e}")
        # Set error reaction
        try:
            import httpx
            bot_token = BOT_TOKEN
            url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"

            data = {
                "chat_id": update.effective_chat.id,
                "message_id": update.message.message_id,
                "reaction": json.dumps([{"type": "emoji", "emoji": "❌"}])
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=data)

        except:
            pass

async def handle_file_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file messages in active chats"""
    user_id = update.effective_user.id

    if user_id not in user_sessions:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "❌ Ви не в активному чаті\n\n"
            "Використовуйте /private [КОД] для входу в чат",
            reply_markup=reply_markup
        )
        return

    chat_code = user_sessions[user_id]
    chat = active_chats.get(chat_code)

    if not chat or chat['status'] != ChatStatus.CONNECTED:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "❌ Чат недоступний або очікує підключення другої сторони",
            reply_markup=reply_markup
        )
        return

    # Determine sender role and get recipient
    user_role = get_user_role_in_chat(user_id, chat_code)
    if not user_role:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("❌ Помилка доступу до чату", reply_markup=reply_markup)
        return

    recipient_id = chat['executor_id'] if user_role == ChatRoles.CUSTOMER else chat['customer_id']

    # Check if recipient is connected
    if recipient_id not in user_sessions:
        await update.message.reply_text(
            "⚠️ Файл надіслано, але інша сторона поки не підключена"
        )

    try:
        # Process and save file
        file_data = await handle_chat_file_upload(update, context, chat_code, user_role)

        if file_data:
            # Get original caption/text from the message
            original_caption = update.message.caption or ""

            # Save message to database with file info and original text
            if original_caption:
                message_text = f"📎 {file_data['original_name']} ({file_data['file_size_formatted']})\n💬 {original_caption}"
            else:
                message_text = f"📎 {file_data['original_name']} ({file_data['file_size_formatted']})"
            save_chat_message(chat_code, user_id, user_role, message_text)

            # Forward file to recipient with role indicator and original text
            role_emoji = get_role_emoji(user_role)
            if original_caption:
                caption = f"{role_emoji} {original_caption}\n\n📎 Файл: {file_data['original_name']}"
            else:
                caption = f"{role_emoji} Файл: {file_data['original_name']}"

            try:
                # Forward the original file to recipient
                if update.message.document:
                    await context.bot.send_document(
                        chat_id=recipient_id,
                        document=update.message.document.file_id,
                        caption=caption
                    )
                elif update.message.photo:
                    await context.bot.send_photo(
                        chat_id=recipient_id,
                        photo=update.message.photo[-1].file_id,
                        caption=caption
                    )
                elif update.message.video:
                    await context.bot.send_video(
                        chat_id=recipient_id,
                        video=update.message.video.file_id,
                        caption=caption
                    )
                elif update.message.audio:
                    await context.bot.send_audio(
                        chat_id=recipient_id,
                        audio=update.message.audio.file_id,
                        caption=caption
                    )
                elif update.message.voice:
                    await context.bot.send_voice(
                        chat_id=recipient_id,
                        voice=update.message.voice.file_id,
                        caption=caption
                    )

                # Set success reaction on original message
                try:
                    import httpx
                    bot_token = BOT_TOKEN
                    url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"

                    data = {
                        "chat_id": update.effective_chat.id,
                        "message_id": update.message.message_id,
                        "reaction": json.dumps([{"type": "emoji", "emoji": "👍"}])
                    }

                    async with httpx.AsyncClient() as client:
                        response = await client.post(url, data=data)

                except Exception as reaction_error:
                    logger.warning(f"Could not set reaction: {reaction_error}")

            except Exception as forward_error:
                logger.error(f"Error forwarding file: {forward_error}")
                # Set error reaction
                try:
                    import httpx
                    bot_token = BOT_TOKEN
                    url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"

                    data = {
                        "chat_id": update.effective_chat.id,
                        "message_id": update.message.message_id,
                        "reaction": json.dumps([{"type": "emoji", "emoji": "❌"}])
                    }

                    async with httpx.AsyncClient() as client:
                        response = await client.post(url, data=data)

                except:
                    pass
        else:
            await update.message.reply_text("❌ Помилка обробки файлу")

    except Exception as e:
        logger.error(f"Error handling file in chat: {e}")
        await update.message.reply_text("❌ Помилка обробки файлу")

def mark_message_as_read(chat_code: str, message_id: int, reader_id: int):
    """Mark message as read in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_reads (
                chat_code TEXT,
                message_id INTEGER,
                reader_id INTEGER,
                read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_code, message_id, reader_id)
            )
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO message_reads 
            (chat_code, message_id, reader_id)
            VALUES (?, ?, ?)
        """, (chat_code, message_id, reader_id))

        conn.commit()
        conn.close()
        logger.info(f"Message {message_id} marked as read by {reader_id}")

    except Exception as e:
        logger.error(f"Error marking message as read: {e}")

def init_message_mappings_table():
    """Initialize message mappings table if it doesn't exist"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_mappings (
                chat_code TEXT,
                original_msg_id INTEGER,
                forwarded_msg_id INTEGER,
                sender_id INTEGER,
                recipient_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Also create message reads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_reads (
                chat_code TEXT,
                message_id INTEGER,
                reader_id INTEGER,
                read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_code, message_id, reader_id)
            )
        """)

        # Create chat sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                user_id INTEGER PRIMARY KEY,
                chat_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
        logger.info("Message mappings, reads and sessions tables initialized")

    except Exception as e:
        logger.error(f"Error initializing message mappings table: {e}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "main_menu":
        # Return to main menu
        welcome_text = """
🤝 <b>Розdum Чат</b>

Цей бот призначений для анонімного спілкування між замовником і виконавцем.

<b>Як користуватися:</b>
1️⃣ Отримайте код доступу від основного бота @RozdumBot
2️⃣ Введіть команду: <code>/private [КОД]</code>
3️⃣ Очікуйте підключення другої сторони
4️⃣ Почніть анонімне спілкування

<b>Приклад:</b> <code>/private A4B8C1</code>

💡 Ваша особистість залишається повністю анонімною
        """

        # Check if user has active task to show return button
        keyboard = []
        if user_id in user_sessions:
            chat_code = user_sessions[user_id]
            if chat_code in active_chats:
                keyboard.append([InlineKeyboardButton("🔙 Вернутися до панелі завдання", callback_data="back_to_chat")])

        keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')
        except telegram.error.BadRequest as e:
            if "Message is not modified" in str(e):
                # Message content is the same, just answer the callback
                pass
            else:
                raise e
        return


    if user_id not in user_sessions:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ Сеанс чату завершено", reply_markup=reply_markup)
        return

    chat_code = user_sessions[user_id]

    if data.startswith("view_task_"):
        task_id = int(data.split("_")[2])

        # Get task details from database
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT description, price, category, tags 
                FROM tasks WHERE task_id = ?
            """, (task_id,))
            result = cursor.fetchone()

            # Get task files
            cursor.execute("""
                SELECT tf.*, u.username
                FROM task_files tf 
                LEFT JOIN users u ON tf.user_id = u.user_id
                WHERE tf.task_id = ? 
                ORDER BY tf.created_at
            """, (task_id,))
            files = cursor.fetchall()

            conn.close()

            if result:
                # Convert Row to dict for easier access
                task_data = dict(result)
                description = task_data['description']
                price = task_data['price']
                category = task_data['category']
                tags = task_data['tags']

                # Format files list
                files_text = ""
                if files:
                    files_text = "\n\n📎 <b>Прикріплені файли:</b>\n"
                    for file in files:
                        file_dict = dict(file)
                        file_size_mb = file_dict['file_size'] / (1024 * 1024)
                        files_text += f"📄 {file_dict['original_name']} ({file_size_mb:.1f} MB)\n"

                task_info = f"""
📋 <b>Деталі завдання</b>

<b>Категорія:</b> {category}
<b>Теги:</b> {format_tags_display(tags)}
<b>Ціна:</b> {price} грн

<b>Опис:</b>
{description}{files_text}
                """

                keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(task_info, reply_markup=reply_markup, parse_mode='HTML')
            else:
                keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("❌ Завдання не знайдено", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error viewing task: {e}")
            keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("❌ Помилка отримання даних", reply_markup=reply_markup)

    elif data.startswith("view_files_"):
        task_id = int(data.split("_")[2])

        # Get task files from database
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Get task files
            cursor.execute("""
                SELECT tf.*, u.username, tf.file_path, tf.original_name, tf.file_type
                FROM task_files tf 
                LEFT JOIN users u ON tf.user_id = u.user_id
                WHERE tf.task_id = ? 
                ORDER BY tf.created_at
            """, (task_id,))
            files = cursor.fetchall()

            conn.close()

            if files:
                # Send actual files instead of just text list
                await query.answer("📎 Відправляю файли...")

                # Send message first, then files below
                files_text = "📎 <b>Файли завдання:</b>\n\n"
                keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(files_text, reply_markup=reply_markup, parse_mode='HTML')

                for file in files:
                    # Convert Row object to dict for safer access
                    file_dict = dict(file)
                    file_path = file_dict.get('file_path')
                    original_name = file_dict.get('original_name', 'unknown_file')
                    file_type = file_dict.get('file_type', '')
                    file_name = file_dict.get('file_name', original_name)

                    # Build file paths to try
                    possible_paths = []
                    if file_path:
                        possible_paths.append(str(file_path))
                    
                    file_sent = False
                    for path in possible_paths:
                        if path and os.path.exists(path):
                            try:
                                # Determine file type by extension if not set
                                if not file_type:
                                    ext = os.path.splitext(str(original_name))[1].lower()
                                    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                                        file_type = 'image/'
                                    elif ext in ['.mp4', '.avi', '.mkv', '.mov']:
                                        file_type = 'video/'
                                    else:
                                        file_type = 'document'

                                # Send file based on type
                                if file_type.startswith('image/') or str(original_name).lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                                    with open(path, 'rb') as f:
                                        await context.bot.send_photo(
                                            chat_id=user_id,
                                            photo=f,
                                            caption=f"📎 {original_name}\n💼 Файл завдання #{task_id}"
                                        )
                                elif file_type.startswith('video/') or str(original_name).lower().endswith(('.mp4', '.avi', '.mkv', '.mov')):
                                    with open(path, 'rb') as f:
                                        await context.bot.send_video(
                                            chat_id=user_id,
                                            video=f,
                                            caption=f"📎 {original_name}\n💼 Файл завдання #{task_id}"
                                        )
                                else:
                                    # Send as document
                                    with open(path, 'rb') as f:
                                        await context.bot.send_document(
                                            chat_id=user_id,
                                            document=f,
                                            filename=str(original_name),
                                            caption=f"📎 {original_name}\n💼 Файл завдання #{task_id}"
                                        )
                                file_sent = True
                                break
                            except Exception as e:
                                logger.error(f"Error sending file {original_name} from {path}: {e}")
                                continue

                    if not file_sent:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"❌ Файл не знайдено: {original_name}"
                        )
                        logger.error(f"File not found in any location: {original_name}, tried paths: {possible_paths}")

                return



            else:
                files_text = "📎 <b>Файли не прикріплені</b>\n\nДо цього завдання не було завантажено жодного файлу."
                keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(files_text, reply_markup=reply_markup, parse_mode='HTML')

        except Exception as e:
            logger.error(f"Error viewing files: {e}")
            keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("❌ Помилка отримання файлів", reply_markup=reply_markup)

    elif data == "back_to_chat":
        # Return to chat interface
        chat = active_chats.get(chat_code)
        if chat:
            user_role = get_user_role_in_chat(user_id, chat_code)
            task_id = chat['task_id']

            keyboard = build_chat_interface(user_role, task_id)
            await query.edit_message_text(
                "💬 <b>Повернення до чату</b>\n\nПродовжуйте спілкування",
                reply_markup=keyboard,
                parse_mode='HTML'
            )

    elif data.startswith("complete_task_"):
        # Executor marks task as complete
        task_id = int(data.split("_")[2])

        # Update task status in database
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE tasks SET status = 'completed' WHERE task_id = ?", (task_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error updating task status: {e}")

        keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🎯 <b>Роботу відмічено як завершену!</b>\n\n"
            "Замовника сповіщено про завершення. Очікуйте підтвердження або відповіді.",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        # Notify customer with detailed interface
        chat = active_chats.get(chat_code)
        if chat:
            try:
                # Get task details for customer notification
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT description, price, category, tags 
                    FROM tasks WHERE task_id = ?
                """, (task_id,))
                task_details = cursor.fetchone()
                conn.close()

                if task_details:
                    task_info = f"""
🎯 <b>Виконавець завершив роботу!</b>

📋 <b>Завдання:</b> {task_details['description'][:100]}{'...' if len(task_details['description']) > 100 else ''}
💰 <b>Вартість:</b> {task_details['price']} грн
📂 <b>Категорія:</b> {task_details['category']}

Перевірте результат та підтвердіть виконання або відкрийте спір.
"""
                else:
                    task_info = "🎯 <b>Виконавець завершив роботу!</b>\n\nПеревірте результат та підтвердіть виконання або відкрийте спір."

                # Enhanced notification with buttons
                notification_keyboard = [
                    [InlineKeyboardButton("📋 Деталі завдання", callback_data=f"view_task_details_{task_id}"),
                     InlineKeyboardButton("📎 Файли завдання", callback_data=f"view_task_files_{task_id}")],
                    [InlineKeyboardButton("✅ Підтвердити виконання", callback_data=f"approve_task_{task_id}"),
                     InlineKeyboardButton("⚠️ Відкрити спір", callback_data=f"dispute_task_{task_id}")],
                    [InlineKeyboardButton("💬 Перейти в чат", url=f"https://t.me/Rozdum_ChatBot")]
                ]
                notification_markup = InlineKeyboardMarkup(notification_keyboard)

                await context.bot.send_message(
                    chat_id=chat['customer_id'],
                    text=task_info,
                    parse_mode='HTML',
                    reply_markup=notification_markup
                )
            except Exception as e:
                logger.error(f"Error sending completion notification: {e}")

    elif data.startswith("view_task_details_"):
        # Customer views task details from completion notification
        task_id = int(data.split("_")[3])

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.*, u.username as customer_username
                FROM tasks t
                LEFT JOIN users u ON t.customer_id = u.user_id
                WHERE t.task_id = ?
            """, (task_id,))
            task = cursor.fetchone()
            conn.close()

            if task:
                # Format task details display
                tags_display = format_tags_display(task['tags'])

                task_details = f"""
📋 <b>Деталі завдання #{task_id}</b>

👤 <b>Замовник:</b> {task['customer_username'] or 'Невідомий'}
📂 <b>Категорія:</b> {task['category']}
🏷️ <b>Теги:</b> {tags_display}
💰 <b>Вартість:</b> {task['price']} грн

📝 <b>Опис:</b>
{task['description']}

📅 <b>Створено:</b> {task['created_at']}
📊 <b>Статус:</b> {task['status']}
"""

                keyboard = [
                    [InlineKeyboardButton("📎 Файли завдання", callback_data=f"view_task_files_{task_id}")],
                    [InlineKeyboardButton("✅ Підтвердити виконання", callback_data=f"approve_task_{task_id}"),
                     InlineKeyboardButton("⚠️ Відкрити спір", callback_data=f"dispute_task_{task_id}")],
                    [InlineKeyboardButton("🔙 Закрити", callback_data="close_notification")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    task_details,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            else:
                await query.edit_message_text("❌ Завдання не знайдено")

        except Exception as e:
            logger.error(f"Error viewing task details: {e}")
            await query.edit_message_text("❌ Помилка завантаження деталей завдання")

    elif data.startswith("approve_task_"):
        # Customer approves task completion
        task_id = int(data.split("_")[2])

        try:
            # Get task details
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            task = cursor.fetchone()

            if task and task['status'] == 'completed':
                # Update task status to 'finished'
                cursor.execute("UPDATE tasks SET status = 'finished' WHERE task_id = ?", (task_id,))

                # Transfer money to executor
                executor_fee = task['price'] * 0.9  # 10% platform commission
                cursor.execute("""
                    UPDATE users SET balance = balance + ?, earned_balance = earned_balance + ? WHERE user_id = ?
                """, (executor_fee, executor_fee, task['executor_id']))

                # Unfreeze customer money and deduct the task cost
                cursor.execute("""
                    UPDATE users SET frozen_balance = frozen_balance - ?, balance = balance - ? 
                    WHERE user_id = ?
                """, (task['price'], task['price'], task['customer_id']))

                conn.commit()
                conn.close()

                await query.edit_message_text(
                    f"✅ <b>Завдання підтверджено!</b>\n\n"
                    f"💰 Виконавець отримав: {executor_fee:.2f} грн\n"
                    f"💳 Комісія платформи: {task['price'] * 0.1:.2f} грн\n\n"
                    f"Дякуємо за використання нашої платформи!",
                    parse_mode='HTML'
                )

                # Notify executor
                try:
                    await context.bot.send_message(
                        chat_id=task['executor_id'],
                        text=f"🎉 <b>Замовник підтвердив виконання!</b>\n\n"
                             f"💰 Ви отримали: {executor_fee:.2f} грн\n"
                             f"📋 Завдання #{task_id} завершено",
                        parse_mode='HTML'
                    )
                except:
                    pass

                # Close chat sessions
                chat = active_chats.get(chat_code)
                if chat:
                    # Remove both users from sessions
                    if chat['customer_id'] in user_sessions:
                        del user_sessions[chat['customer_id']]
                        remove_user_session(chat['customer_id'])
                    if chat['executor_id'] in user_sessions:
                        del user_sessions[chat['executor_id']]
                        remove_user_session(chat['executor_id'])

                    # Remove chat from active chats
                    if chat_code in active_chats:
                        del active_chats[chat_code]

            else:
                await query.edit_message_text("❌ Завдання не може бути підтверджено")

        except Exception as e:
            logger.error(f"Error approving task: {e}")
            await query.edit_message_text("❌ Помилка підтвердження завдання")

    elif data.startswith("dispute_task_"):
        # Customer opens dispute
        task_id = int(data.split("_")[2])

        try:
            # Get task details
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            task = cursor.fetchone()

            if not task:
                await query.edit_message_text("❌ Завдання не знайдено")
                return

            if task['customer_id'] != user_id:
                await query.edit_message_text("❌ Ви не можете відкрити спір по цьому завданню")
                return

            if task['status'] != 'completed':
                await query.edit_message_text("❌ Спір можна відкрити тільки після завершення завдання")
                return

            # Create dispute in database
            dispute_reason = f"Замовник оспорив виконання завдання #{task_id}"
            cursor.execute('''
                INSERT INTO disputes (task_id, customer_id, executor_id, reason, status, created_at)
                VALUES (?, ?, ?, ?, 'open', datetime('now'))
            ''', (task_id, task['customer_id'], task['executor_id'], dispute_reason))

            dispute_id = cursor.lastrowid

            # Update task status to 'disputed'
            cursor.execute("UPDATE tasks SET status = 'disputed' WHERE task_id = ?", (task_id,))

            conn.commit()
            conn.close()

            logger.info(f"Created dispute {dispute_id} for task {task_id}")

            keyboard = [
                [InlineKeyboardButton("📋 Деталі завдання", callback_data=f"view_task_details_{task_id}")],
                [InlineKeyboardButton("🔙 Закрити", callback_data="close_notification")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"⚠️ <b>Спір відкрито</b>\n\n"
                f"🆔 <b>Спір ID:</b> #{dispute_id}\n"
                f"📋 <b>Завдання:</b> #{task_id}\n"
                f"💰 <b>Кошти заморожені до вирішення спору</b>\n\n"
                f"Адміністратор розгляне ситуацію та прийме рішення.\n\n"
                f"📞 <b>Підтримка:</b> @Admin_fartobot",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

            # Notify executor about dispute
            try:
                executor_text = f"""
⚠️ <b>Відкрито спір</b>

🆔 <b>Спір ID:</b> #{dispute_id}
📋 <b>Завдання:</b> #{task_id}
💰 <b>Кошти заморожені до вирішення спору</b>

Замовник оспорив виконання завдання.
Адміністратор розгляне ситуацію та прийме рішення.

📞 <b>Підтримка:</b> @Admin_fartobot
                """

                await context.bot.send_message(
                    chat_id=task['executor_id'],
                    text=executor_text,
                    parse_mode='HTML'
                )
                logger.info(f"Executor {task['executor_id']} notified about dispute {dispute_id}")
            except Exception as e:
                logger.error(f"Failed to notify executor about dispute: {e}")

            # Notify admin about dispute
            try:
                await notify_admin_bot(
                    f"🚨 НОВИЙ СПІР #{dispute_id}\n\n"
                    f"📋 Завдання #{task_id}\n"
                    f"💰 Сума: {task['price']:.2f} грн\n"
                    f"👤 Замовник: ID {task['customer_id']}\n"
                    f"🔧 Виконавець: ID {task['executor_id']}\n\n"
                    f"Перейдіть до @Admin_fartobot для вирішення спору",
                    task_id
                )
            except Exception as e:
                logger.error(f"Failed to notify admin about dispute: {e}")

        except Exception as e:
            logger.error(f"Error creating dispute: {e}")
            await query.edit_message_text("❌ Помилка створення спору")

    elif data.startswith("open_dispute_"):
        # Customer opens dispute directly from chat interface
        task_id = int(data.split("_")[2])

        try:
            # Get task details
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            task = cursor.fetchone()

            if not task:
                await query.edit_message_text("❌ Завдання не знайдено")
                return

            if task['customer_id'] != user_id:
                await query.edit_message_text("❌ Ви не можете відкрити спір по цьому завданню")
                return

            if task['status'] not in ['in_progress', 'completed']:
                await query.edit_message_text("❌ Спір можна відкрити тільки по активному або завершеному завданню")
                return

            # Create dispute in database
            dispute_reason = f"Замовник відкрив спір з чату по завданню #{task_id}"
            cursor.execute('''
                INSERT INTO disputes (task_id, customer_id, executor_id, reason, status, created_at)
                VALUES (?, ?, ?, ?, 'open', datetime('now'))
            ''', (task_id, task['customer_id'], task['executor_id'], dispute_reason))

            dispute_id = cursor.lastrowid

            # Update task status to 'disputed'
            cursor.execute("UPDATE tasks SET status = 'disputed' WHERE task_id = ?", (task_id,))

            conn.commit()
            conn.close()

            # Log dispute creation
            log_chat_event('DISPUTE_CREATED', user_id, chat_code, {
                'dispute_id': dispute_id,
                'task_id': task_id,
                'customer_id': task['customer_id'],
                'executor_id': task['executor_id'],
                'reason': dispute_reason
            })
            logger.info(f"⚠️ Dispute {dispute_id} created for task {task_id} from chat by user {user_id}")

            keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"⚠️ <b>Спір відкрито!</b>\n\n"
                f"🆔 <b>Спір ID:</b> #{dispute_id}\n"
                f"📋 <b>Завдання:</b> #{task_id}\n"
                f"💰 <b>Кошти заморожені до вирішення спору</b>\n\n"
                f"Адміністратор розгляне ситуацію та прийме рішення.\n\n"
                f"📞 <b>Підтримка:</b> @Admin_fartobot",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

            # Notify executor about dispute
            try:
                executor_text = f"""
⚠️ <b>Відкрито спір</b>

🆔 <b>Спір ID:</b> #{dispute_id}
📋 <b>Завдання:</b> #{task_id}
💰 <b>Кошти заморожені до вирішення спору</b>

Замовник відкрив спір по завданню з чату.
Адміністратор розгляне ситуацію та прийме рішення.

📞 <b>Підтримка:</b> @Admin_fartobot
                """

                await context.bot.send_message(
                    chat_id=task['executor_id'],
                    text=executor_text,
                    parse_mode='HTML'
                )
                logger.info(f"Executor {task['executor_id']} notified about dispute {dispute_id}")
            except Exception as e:
                logger.error(f"Failed to notify executor about dispute: {e}")

            # Notify admin about dispute
            try:
                await notify_admin_bot(
                    f"🚨 НОВИЙ СПІР З ЧАТУ #{dispute_id}\n\n"
                    f"📋 Завдання #{task_id}\n"
                    f"💰 Сума: {task['price']:.2f} грн\n"
                    f"👤 Замовник: ID {task['customer_id']}\n"
                    f"🔧 Виконавець: ID {task['executor_id']}\n\n"
                    f"Перейдіть до @Admin_fartobot для вирішення спору",
                    task_id
                )
            except Exception as e:
                logger.error(f"Failed to notify admin about dispute: {e}")

        except Exception as e:
            logger.error(f"Error creating dispute from chat: {e}")
            await query.edit_message_text("❌ Помилка створення спору")

    elif data == "close_notification":
        # Close notification message
        await query.edit_message_text("ℹ️ Сповіщення закрито")

    elif data.startswith("rating_executor_") or data.startswith("rating_customer_"):
        # Show rating interface for executor or customer
        task_id = int(data.split("_")[2])
        chat = active_chats.get(chat_code)

        if chat:
            user_role = get_user_role_in_chat(user_id, chat_code)
            if data.startswith("rating_executor_"):
                # Customer wants to rate executor
                other_user_id = chat['executor_id']
            else:
                # Executor wants to rate customer
                other_user_id = chat['customer_id']

            await show_user_rating_history(query, user_id, other_user_id)
        else:
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("❌ Чат не знайдено", reply_markup=reply_markup)

    elif data.startswith("task_reviews_"):
        # Show reviews for the task
        task_id = int(data.split("_")[2])
        await show_task_reviews(query, task_id)

    elif data.startswith("all_reviews_"):
        # Show all reviews for a user
        other_user_id = int(data.split("_")[2])
        await show_all_user_reviews(query, user_id, other_user_id)

    elif data.startswith("rating_stats_"):
        # Show detailed rating statistics for a user
        other_user_id = int(data.split("_")[2])
        await show_user_rating_history(query, user_id, other_user_id)

    elif data.startswith("show_rating_"):
        # Show rating interface
        other_user_id = int(data.split("_")[2])
        chat = active_chats.get(chat_code)

        if chat:
            user_role = get_user_role_in_chat(user_id, chat_code)
            task_id = chat['task_id']
            await show_rating_interface(query, chat_code, user_id, other_user_id, task_id, user_role)
        else:
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("❌ Чат не знайдено", reply_markup=reply_markup)

    elif data.startswith("rate_") and not data.startswith("rate_comment_"):
        # Handle rating submission
        parts = data.split("_")
        if len(parts) >= 4:
            task_id = int(parts[1])
            reviewed_id = int(parts[2])
            rating = int(parts[3])
            await handle_rating_submission(query, task_id, reviewed_id, rating)

    elif data.startswith("rate_comment_"):
        # Show comment input interface
        parts = data.split("_")
        if len(parts) >= 3:
            task_id = int(parts[2])
            reviewed_id = int(parts[3])

            # Store context for text input
            context.user_data['rating_context'] = {
                'task_id': task_id,
                'reviewed_id': reviewed_id,
                'awaiting_comment': True
            }

            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_chat")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "📝 <b>Залишити коментар</b>\n\n"
                "Надішліть текстове повідомлення з вашим коментарем та оцінкою (1-5).\n\n"
                "Формат: <code>5 Відмінна робота!</code>\n"
                "або просто: <code>5</code> (без коментаря)",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

    elif data == "skip_rating":
        # Skip rating
        keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "⏭️ Оцінювання пропущено",
            reply_markup=reply_markup
        )

    elif data.startswith("dispute_task_"):
        task_id = int(data.split("_")[2])

        # Create dispute in database
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Get task and chat info
            cursor.execute("""
                SELECT c.customer_id, c.executor_id, c.task_id, t.description, t.price
                FROM chats c
                JOIN tasks t ON c.task_id = t.task_id
                WHERE c.chat_code = ?
            """, (chat_code,))

            result = cursor.fetchone()
            if result:
                customer_id, executor_id, task_id, description, price = result

                # Create dispute record with proper fields
                cursor.execute("""
                    INSERT INTO disputes (task_id, customer_id, executor_id, reason, status, created_at)
                    VALUES (?, ?, ?, ?, 'open', datetime('now'))
                """, (task_id, customer_id, executor_id, "Спір відкрито через чат"))

                dispute_id = cursor.lastrowid

                # Update task status
                cursor.execute("UPDATE tasks SET status = 'dispute' WHERE task_id = ?", (task_id,))

                conn.commit()

                # Get user info for better notifications
                cursor.execute("SELECT username FROM users WHERE user_id = ?", (customer_id,))
                customer_info = cursor.fetchone()
                cursor.execute("SELECT username FROM users WHERE user_id = ?", (executor_id,))
                executor_info = cursor.fetchone()

                customer_username = customer_info['username'] if customer_info and customer_info['username'] else f"ID:{customer_id}"
                executor_username = executor_info['username'] if executor_info and executor_info['username'] else f"ID:{executor_id}"

                # Notify admin bot
                admin_message = f"""
🚨 <b>НОВИЙ СПІР З ЧАТУ!</b>

🆔 <b>Спір:</b> #{dispute_id}
📋 <b>Завдання:</b> #{task_id}
💰 <b>Ціна:</b> {price} грн

👥 <b>Учасники:</b>
🛒 <b>Замовник:</b> {customer_username}
⚡ <b>Виконавець:</b> {executor_username}

💬 <b>Причина:</b> Спір відкрито через чат
📝 <b>Опис:</b> {description[:200]}{'...' if len(description) > 200 else ''}

🔧 <b>Дії:</b> Перейдіть до @Admin_fartobot для розгляду
                """

                await notify_admin_bot(admin_message, task_id)
                logger.info(f"Created dispute {dispute_id} for task {task_id} from chat")

            conn.close()

        except Exception as e:
            logger.error(f"Error creating dispute from chat: {e}")

        # Customer opens dispute
        keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "⚠️ <b>Спір відкрито!</b>\n\n"
            "Адміністрація отримала сповіщення та розгляне ситуацію. "
            "Кошти заморожені до вирішення спору.\n\n"
            "📞 <b>Підтримка:</b> @Admin_fartobot",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        chat = active_chats.get(chat_code)
        if chat:
            # Notify executor
            try:
                await context.bot.send_message(
                    chat_id=chat['executor_id'],
                    text="⚠️ <b>Замовник відкрив спір!</b>\n\n"
                         "Адміністрація розгляне ситуацію та прийме рішення.\n\n"
                         "📞 <b>Підтримка:</b> @Admin_fartobot",
                    parse_mode='HTML'
                )
                logger.info(f"Notified executor {chat['executor_id']} about dispute")
            except Exception as e:
                logger.error(f"Failed to notify executor about dispute: {e}")

    elif data == "close_chat":
        # Propose closing chat to other participant
        chat = active_chats.get(chat_code)
        if chat:
            user_role = get_user_role_in_chat(user_id, chat_code)
            role_name = get_role_name(user_role)

            other_user_id = chat['executor_id'] if user_role == ChatRoles.CUSTOMER else chat['customer_id']

            # Send proposal to other user
            if other_user_id in user_sessions:
                try:
                    keyboard = [
                        [InlineKeyboardButton("✅ Закінчити чат", callback_data=f"confirm_close_chat_{user_id}")],
                        [InlineKeyboardButton("⚠️ Скарга", callback_data=f"dispute_task_{chat['task_id']}")],
                        [InlineKeyboardButton("❌ Відміна", callback_data="cancel_close_chat")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await context.bot.send_message(
                        chat_id=other_user_id,
                        text=f"🔔 <b>{role_name} хоче закінчити чат</b>\n\n"
                             "Оберіть дію:",
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )

                    # Inform initiator
                    keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await query.edit_message_text(
                        f"⏳ <b>Запит надіслано</b>\n\n"
                        f"Іншій стороні запропоновано закінчити чат. Очікуйте відповіді.",
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )

                except Exception as e:
                    logger.error(f"Error sending close chat proposal: {e}")
                    # Fallback to direct close
                    await query.edit_message_text(
                        "❌ <b>Чат закрито</b>\n\n"
                        "Для нового чату отримайте код від @RozdumBot",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
                    )
                    if user_id in user_sessions:
                        del user_sessions[user_id]
                        remove_user_session(user_id)
            else:
                # Other user not connected, close directly
                await query.edit_message_text(
                    "❌ <b>Чат закрито</b>\n\n"
                    "Для нового чату отримайте код від @RozdumBot",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
                )
                if user_id in user_sessions:
                    del user_sessions[user_id]
                    remove_user_session(user_id)

    elif data.startswith("confirm_close_chat_"):
        # Confirm closing chat from other user
        initiator_id = int(data.split("_")[3])

        # Close chat for both users
        chat = active_chats.get(chat_code)
        if chat:
            # Close for initiator
            if initiator_id in user_sessions:
                try:
                    await context.bot.send_message(
                        chat_id=initiator_id,
                        text="✅ <b>Чат закінчено за взаємною згодою</b>\n\n"
                             "Для нового чату отримайте код від @RozdumBot",
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
                    )
                    del user_sessions[initiator_id]
                    remove_user_session(initiator_id)
                except:
                    pass

            # Close for current user
            await query.edit_message_text(
                "✅ <b>Чат закінчено за взаємною згодою</b>\n\n"
                "Для нового чату отримайте код від @RozdumBot",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]),
                parse_mode='HTML'
            )

            if user_id in user_sessions:
                del user_sessions[user_id]
                remove_user_session(user_id)

            # Remove chat from active chats
            if chat_code in active_chats:
                del active_chats[chat_code]

    elif data == "cancel_close_chat":
        # Cancel closing chat
        await query.edit_message_text(
            "❌ <b>Закриття чату скасовано</b>\n\n"
            "Чат продовжується.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]])
        )

    elif data == "send_file":
        keyboard = [[InlineKeyboardButton("🔙 Назад до чату", callback_data="back_to_chat")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "💬 <b>Надсилання файлів</b>\n\n"
            "Надішліть файл звичайним повідомленням - він буде переданий іншій стороні",
            reply_markup=reply_markup
        )

async def admin_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /code_pas command for admin access."""
    user_id = update.effective_user.id
    args = context.args

    if not args:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("❌ Введіть код після команди", reply_markup=reply_markup)
        return

    code = args[0]

    # Check if code is correct
    if code == "09111":
        # Set admin status directly in database
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET is_admin = ?, admin_level = ? 
                WHERE user_id = ?
            """, (True, 1, user_id))
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()

            if success:
                keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    "✅ <b>Адміністративні права надано!</b>\n\n"
                    "Тепер ви маєте доступ до адміністративних функцій у всіх ботах системи.",
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                logger.info(f"Admin access granted to user {user_id}")
            else:
                keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("❌ Помилка надання адміністративних прав", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error setting admin status: {e}")
            keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("❌ Помилка надання адміністративних прав", reply_markup=reply_markup)
    else:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("❌ Неправильний код", reply_markup=reply_markup)

def restore_sessions_on_startup():
    """Restore user sessions from database on bot startup"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Load all active sessions
        cursor.execute("SELECT user_id, chat_code FROM chat_sessions")
        sessions = cursor.fetchall()

        for session in sessions:
            user_id, chat_code = session['user_id'], session['chat_code']

            # Verify chat is still active
            cursor.execute("""
                SELECT task_id, customer_id, executor_id FROM chats 
                WHERE chat_code = ? AND status = 'active'
            """, (chat_code,))

            chat_data = cursor.fetchone()
            if chat_data:
                user_sessions[user_id] = chat_code

                # Restore active chat data
                if chat_code not in active_chats:
                    active_chats[chat_code] = {
                        'task_id': chat_data['task_id'],
                        'customer_id': chat_data['customer_id'],
                        'executor_id': chat_data['executor_id'],
                        'status': ChatStatus.CONNECTED,
                        'participants': set()
                    }

                active_chats[chat_code]['participants'].add(user_id)
                logger.info(f"Restored session for user {user_id} in chat {chat_code}")

        conn.close()
        logger.info(f"Restored {len(sessions)} user sessions")

    except Exception as e:
        logger.error(f"Error restoring sessions: {e}")

def main():
    """Start the chat bot"""
    try:
        print("🚀 Starting Rozdum Chat Bot...")

        # Check for environment variables first
        if not CHAT_BOT_TOKEN:
            print("❌ CHAT_BOT_TOKEN environment variable not found!")
            print("Please set CHAT_BOT_TOKEN in Replit Secrets")
            return

        print(f"✅ Bot token found: ...{CHAT_BOT_TOKEN[-10:]}")

        # Initialize database tables
        print("📊 Initializing database...")
        init_message_mappings_table()

        # Restore sessions from previous run
        print("🔄 Restoring sessions...")
        restore_sessions_on_startup()

        # Set @fezerstop as highest level admin (Level 5) with both ID and username
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Check if fezerstop user exists by ID
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (5857065034,))
            if not cursor.fetchone():
                # Create fezerstop user with Level 5 admin
                cursor.execute("""
                    INSERT INTO users (user_id, username, balance, rating, is_executor, is_admin, admin_level, created_at)
                    VALUES (?, ?, 0.0, 5.0, 0, 1, 5, datetime('now'))
                """, (5857065034, "fezerstop"))
                print("✅ Created @fezerstop user with Level 5 admin")
            else:
                # Update existing user to ensure proper admin status and username
                cursor.execute("""
                    UPDATE users SET username = ?, is_admin = 1, admin_level = 5
                    WHERE user_id = ?
                """, ("fezerstop", 5857065034))
                print("✅ Updated @fezerstop to Level 5 admin")

            conn.commit()
            conn.close()
            logger.info("@fezerstop (ID: 5857065034, username: fezerstop) set as highest level admin (Level 5)")
        except Exception as e:
            logger.error(f"Failed to set @fezerstop as admin: {e}")
            print(f"⚠️ Warning: Failed to set admin: {e}")

        # Create application with better network configuration and conflict handling
        print("🔧 Creating Telegram application...")
        application = (
            Application.builder()
            .token(CHAT_BOT_TOKEN)
            .read_timeout(30)
            .write_timeout(30)
            .connect_timeout(30)
            .pool_timeout(30)
            .get_updates_read_timeout(30)
            .get_updates_write_timeout(30)
            .get_updates_connect_timeout(30)
            .build()
        )

        # Add error handler
        application.add_error_handler(error_handler)

        # Add handlers
        print("📝 Adding handlers...")

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("code_pas", admin_code_command))
        application.add_handler(CommandHandler("private", private_command))

        # File handlers
        application.add_handler(MessageHandler(filters.Document.ALL, handle_file_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_file_message))
        application.add_handler(MessageHandler(filters.VIDEO, handle_file_message))
        application.add_handler(MessageHandler(filters.AUDIO, handle_file_message))
        application.add_handler(MessageHandler(filters.VOICE, handle_file_message))

        # Text message handler (should be last to avoid conflicts)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(handle_callback))

        print("🚀 Rozdum Chat Bot starting...")
        logger.info("🚀 Rozdum Chat Bot starting...")
        log_chat_event('BOT_STARTUP', 0, None, {
            'restored_sessions': len(user_sessions),
            'active_chats': len(active_chats),
            'startup_time': datetime.now().isoformat()
        })

        # Try to start with proper error handling
        try:
            print("✅ Bot started successfully! Listening for messages...")
            application.run_polling(drop_pending_updates=True)
        except Exception as e:
            if "Conflict" in str(e) and "getUpdates" in str(e):
                print("⚠️ Another bot instance is already running!")
                print("Please stop other instances before starting this one.")
                logger.warning(f"Bot conflict detected: {e}")
            else:
                print(f"❌ Error starting bot: {e}")
                logger.error(f"❌ Error starting chat bot: {e}")
            log_chat_event('BOT_STARTUP_ERROR', 0, None, {
                'error': str(e),
                'error_time': datetime.now().isoformat()
            })

    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
        logger.info("Bot stopped by user interrupt")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        logger.error(f"Fatal error in main: {e}")

if __name__ == '__main__':
    main()