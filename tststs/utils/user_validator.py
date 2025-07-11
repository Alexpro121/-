
"""
User Validator - Перевірка реальних користувачів
"""

import logging
from typing import Optional
from database import get_user

logger = logging.getLogger(__name__)

def is_real_user(user_id: int) -> bool:
    """Перевірити чи є користувач реальним (не фейковим)"""
    # Базова перевірка ID
    if user_id < 100000:
        return False
    
    # Перевірка в базі даних
    user = get_user(user_id)
    if not user:
        return False
    
    # Перевірка наявності username
    if not user.get('username') or user.get('username') == '':
        return False
    
    # Перевірка чи не заблокований
    if user.get('is_blocked', False):
        return False
    
    # Перевірка підозрілих імен
    username = user.get('username', '').lower()
    suspicious_names = ['test', 'fake', 'template', 'example', 'demo', 'bot']
    
    for suspicious in suspicious_names:
        if suspicious in username:
            return False
    
    return True

def is_working_user(user_id: int) -> bool:
    """Перевірити чи є користувач робочим"""
    if not is_real_user(user_id):
        return False
    
    user = get_user(user_id)
    if not user:
        return False
    
    return user.get('is_working', False)

def validate_user_for_task(user_id: int) -> tuple[bool, str]:
    """Валідація користувача для участі в завданнях"""
    if not is_real_user(user_id):
        return False, "Користувач не є реальним"
    
    if not is_working_user(user_id):
        return False, "Користувач не працює"
    
    user = get_user(user_id)
    if user.get('missed_tasks_count', 0) > 10:
        return False, "Занадто багато пропущених завдань"
    
    return True, "Користувач валідний"

def filter_real_users(user_list: list) -> list:
    """Фільтрувати список користувачів, залишивши лише реальних"""
    real_users = []
    
    for user in user_list:
        user_id = user.get('user_id') if isinstance(user, dict) else user
        
        if is_real_user(user_id):
            real_users.append(user)
    
    return real_users

def get_real_user_count() -> int:
    """Отримати кількість реальних користувачів"""
    from database import get_db_connection
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM users 
            WHERE user_id >= 100000 
            AND username IS NOT NULL 
            AND username != ''
            AND COALESCE(is_blocked, 0) = 0
        """)
        
        count = cursor.fetchone()[0]
        return count
        
    except Exception as e:
        logger.error(f"Error getting real user count: {e}")
        return 0
    finally:
        conn.close()
