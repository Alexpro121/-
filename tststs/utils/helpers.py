"""
Utility helper functions for Rozdum Bot
"""

from typing import Dict, List, Optional, Any
import logging
import re
from datetime import datetime, timedelta
from config import CATEGORIES

logger = logging.getLogger(__name__)

def get_category_emoji(category_key: str) -> str:
    """Get emoji for category"""
    emoji_map = {
        'design': '🎨',
        'programming': '💻',
        'marketing': '📢',
        'writing': '✍️',
        'translation': '🌍',
        'data_entry': '📊',
        'photography': '📸',
        'video': '🎬',
        'audio': '🎵',
        'consulting': '💼',
        'tutoring': '📚',
        'other': '🔧'
    }
    return emoji_map.get(category_key, '❓')

def format_currency(amount: float) -> str:
    """Format currency amount"""
    return f"{amount:.2f} грн"

def format_task_status(status: str) -> str:
    """Format task status for display"""
    status_map = {
        'searching': 'Пошук виконавця',
        'in_progress': 'Виконується',
        'completed': 'Завершено',
        'dispute': 'Спір',
        'canceled': 'Скасовано',
        'pending_approval': 'Очікує підтвердження'
    }
    return status_map.get(status, status)

def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text with ellipsis if too long"""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."

def validate_price(price_str: str, min_price: float = 25.0) -> tuple:
    """
    Validate price input
    Returns (is_valid, price_value, error_message)
    """
    try:
        price = float(price_str.replace(',', '.'))
        if price < min_price:
            return False, 0, f"Мінімальна ціна: {min_price} грн"
        return True, price, None
    except ValueError:
        return False, 0, "Введіть коректну ціну (число)"

def build_pagination_keyboard(items: List[Dict], page: int = 0, per_page: int = 5) -> tuple:
    """
    Build pagination for lists
    Returns (current_page_items, has_next, has_prev)
    """
    start_idx = page * per_page
    end_idx = start_idx + per_page

    current_items = items[start_idx:end_idx]
    has_next = end_idx < len(items)
    has_prev = page > 0

    return current_items, has_next, has_prev

def calculate_rating_stars(rating: float) -> str:
    """Convert numeric rating to star representation"""
    full_stars = int(rating)
    half_star = 1 if rating - full_stars >= 0.5 else 0
    empty_stars = 5 - full_stars - half_star

    return "⭐" * full_stars + "⭐" * half_star + "☆" * empty_stars

def get_user_display_name(user_data: Dict) -> str:
    """Get display name for user"""
    if user_data.get('first_name'):
        name = user_data['first_name']
        if user_data.get('last_name'):
            name += f" {user_data['last_name']}"
        return name
    return f"User #{user_data['user_id']}"

def format_task_tags(tags: List[str]) -> str:
    """Format task tags for display"""
    if not tags:
        return "Без тегів"
    return ", ".join([tag.replace('_', ' ').title() for tag in tags])

def get_time_ago(timestamp: str) -> str:
    """Get human readable time ago string"""
    # This would need proper datetime parsing
    # For now, return placeholder
    return "нещодавно"

def sanitize_input(text: str, max_length: int = 1000) -> str:
    """Sanitize user input"""
    if not text:
        return ""

    # Remove potential harmful characters
    sanitized = text.strip()

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    return sanitized

def format_datetime(dt_string: str, format_type: str = "short") -> str:
    """Format datetime string for display."""
    try:
        if dt_string in ["CURRENT_TIMESTAMP", None]:
            dt = datetime.now()
        else:
            dt = datetime.fromisoformat(dt_string)
        
        if format_type == "short":
            return dt.strftime("%d.%m.%Y %H:%M")
        elif format_type == "date":
            return dt.strftime("%d.%m.%Y")
        elif format_type == "time":
            return dt.strftime("%H:%M")
        else:
            return dt.strftime("%d.%m.%Y %H:%M:%S")
            
    except Exception as e:
        logger.error(f"Error formatting datetime {dt_string}: {e}")
        return "Невідомо"

def calculate_time_ago(dt_string: str) -> str:
    """Calculate and format time ago."""
    try:
        if dt_string in ["CURRENT_TIMESTAMP", None]:
            return "щойно"
            
        dt = datetime.fromisoformat(dt_string)
        now = datetime.now()
        diff = now - dt
        
        if diff.days > 0:
            return f"{diff.days} дн. тому"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} год. тому"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} хв. тому"
        else:
            return "щойно"
            
    except Exception as e:
        logger.error(f"Error calculating time ago for {dt_string}: {e}")
        return "невідомо коли"

def validate_user_input(text: str, input_type: str) -> tuple[bool, str]:
    """
    Validate user input based on type.
    Returns (is_valid, error_message).
    """
    if not text or not text.strip():
        return False, "Поле не може бути порожнім"
    
    text = text.strip()
    
    if input_type == "description":
        if len(text) < 20:
            return False, "Опис надто короткий (мінімум 20 символів)"
        if len(text) > 2000:
            return False, "Опис надто довгий (максимум 2000 символів)"
        return True, ""
    
    elif input_type == "price":
        price_valid, price, error_message = validate_price(text)
        if not price_valid:
            return False, error_message
        if price < 50:
            return False, "Мінімальна ціна: 50 грн"
        if price > 50000:
            return False, "Максимальна ціна: 50,000 грн"
        return True, ""
    
    elif input_type == "comment":
        if len(text) > 500:
            return False, "Коментар надто довгий (максимум 500 символів)"
        return True, ""
    
    return True, ""

def calculate_platform_fee(amount: float, commission_rate: float = 0.10) -> tuple[float, float]:
    """
    Calculate platform fee and net amount.
    Returns (fee_amount, net_amount).
    """
    fee = amount * commission_rate
    net = amount - fee
    return round(fee, 2), round(net, 2)

def generate_chat_id(task_id: int, customer_id: int, executor_id: int) -> str:
    """Generate unique chat ID for task communication."""
    import hashlib
    raw_string = f"{task_id}_{customer_id}_{executor_id}"
    hash_object = hashlib.md5(raw_string.encode())
    return hash_object.hexdigest()[:8].upper()

def format_user_stats(stats: Dict[str, Any]) -> str:
    """Format user statistics for display."""
    lines = []
    
    if 'total_created' in stats:
        lines.append(f"Створено завдань: {stats['total_created']}")
    
    if 'total_executed' in stats:
        lines.append(f"Виконано завдань: {stats['total_executed']}")
    
    if 'success_rate' in stats:
        lines.append(f"Успішність: {stats['success_rate']*100:.1f}%")
    
    if 'rating' in stats:
        lines.append(f"Рейтинг: {stats['rating']:.1f}/5.0")
    
    return "\n".join(lines) if lines else "Статистика недоступна"

def escape_markdown(text: str) -> str:
    """Escape special characters for Markdown."""
    special_chars = ['_', '*', '`', '[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text

def is_valid_telegram_user_id(user_id: Any) -> bool:
    """Check if user_id is valid Telegram user ID."""
    try:
        uid = int(user_id)
        # Telegram user IDs are positive integers
        return uid > 0
    except (ValueError, TypeError):
        return False

def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def format_balance_display(balance: float, frozen: float = 0) -> str:
    """Format balance display with frozen amount if applicable."""
    if frozen > 0:
        return f"{balance:.2f} грн (заморожено: {frozen:.2f} грн)"
    return f"{balance:.2f} грн"

def format_executor_tags_display(tags: List[str], category_key: str = None) -> str:
    """Format executor tags with category context."""
    if not tags:
        return "Не налаштовано"
    
    formatted_tags = [tag.replace('_', ' ').title() for tag in tags]
    
    if category_key:
        emoji = get_category_emoji(category_key)
        return f"{emoji} {', '.join(formatted_tags)}"
    
    return ", ".join(formatted_tags)

class MessageBuilder:
    """Helper class for building formatted messages."""
    
    def __init__(self):
        self.lines = []
    
    def add_header(self, text: str) -> 'MessageBuilder':
        """Add header line."""
        self.lines.append(f"<b>{text}</b>")
        return self
    
    def add_line(self, text: str = "") -> 'MessageBuilder':
        """Add regular line."""
        self.lines.append(text)
        return self
    
    def add_field(self, label: str, value: Any, bold_label: bool = True) -> 'MessageBuilder':
        """Add field with label and value."""
        if bold_label:
            self.lines.append(f"<b>{label}:</b> {value}")
        else:
            self.lines.append(f"{label}: {value}")
        return self
    
    def add_separator(self) -> 'MessageBuilder':
        """Add empty line as separator."""
        self.lines.append("")
        return self
    
    def build(self) -> str:
        """Build final message."""
        return "\n".join(self.lines)

# Logging helpers
def log_user_action(user_id: int, action: str, details: str = None):
    """Log user action for analytics."""
    log_msg = f"User {user_id}: {action}"
    if details:
        log_msg += f" - {details}"
    logger.info(log_msg)

def log_task_event(task_id: int, event: str, user_id: int = None, details: str = None):
    """Log task-related event."""
    log_msg = f"Task {task_id}: {event}"
    if user_id:
        log_msg += f" (User: {user_id})"
    if details:
        log_msg += f" - {details}"
    logger.info(log_msg)