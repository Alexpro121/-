"""
Chat integration utilities for main Rozdum bot
Handles communication with chat bot system
"""

import logging
import asyncio
from typing import Optional, Tuple
from database import get_db_connection, get_task, get_user

logger = logging.getLogger(__name__)

def create_chat_for_task(task_id: int, customer_id: int, executor_id: int) -> Optional[str]:
    """Create a new chat session and return the chat code (alias for create_chat_session_for_task)"""
    return create_chat_session_for_task(task_id, customer_id, executor_id)

def create_chat_session_for_task(task_id: int, customer_id: int, executor_id: int) -> Optional[str]:
    """Create a new chat session and return the chat code"""
    try:
        import random
        import string
        
        # Generate 6-character chat code
        chat_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        # Store chat session in database for separate chat bot
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO chats (task_id, customer_id, executor_id, chat_code, status)
            VALUES (?, ?, ?, ?, 'active')
        """, (task_id, customer_id, executor_id, chat_code))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Created chat session {chat_code} for task {task_id}")
        return chat_code
        
    except Exception as e:
        logger.error(f"Failed to create chat session: {e}")
        return None

def get_chat_code_for_task(task_id: int) -> Optional[str]:
    """Get existing chat code for a task"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT chat_code FROM chats 
            WHERE task_id = ? AND status = 'active'
        """, (task_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result['chat_code'] if result else None
        
    except Exception as e:
        logger.error(f"Failed to get chat code for task {task_id}: {e}")
        return None

def format_chat_invitation_message(chat_code: str, role: str, task_title: str) -> str:
    """Format invitation message for chat bot"""
    role_emoji = "🛒" if role == "customer" else "⚡"
    role_name = "Замовник" if role == "customer" else "Виконавець"
    
    return f"""
🤝 <b>Анонімний чат створено!</b>

{role_emoji} <b>Ваша роль:</b> {role_name}
📋 <b>Завдання:</b> {task_title[:50]}...

<b>Для входу в чат:</b>
1️⃣ Перейдіть до окремого бота @Rozdum_ChatBot
2️⃣ Введіть команду: <code>/private {chat_code}</code>
3️⃣ Почніть анонімне спілкування

💡 <b>Код доступу:</b> <code>{chat_code}</code>
🔒 Повна анонімність через окремий бот!
    """

def send_chat_invitations(task_id: int, customer_id: int, executor_id: int, bot) -> dict:
    """Send chat invitations to both parties"""
    try:
        # Create chat session
        chat_code = create_chat_session_for_task(task_id, customer_id, executor_id)
        
        if not chat_code:
            logger.error(f"Failed to create chat code for task {task_id}")
            return {}
        
        # Get task details
        task = get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return {}
        
        task_title = task['description'][:50] + "..." if len(task['description']) > 50 else task['description']
        
        # Send invitation to customer
        customer_message = format_chat_invitation_message(chat_code, "customer", task_title)
        
        # Send invitation to executor  
        executor_message = format_chat_invitation_message(chat_code, "executor", task_title)
        
        # Store messages to be sent by the calling function
        # Since we can't easily send async messages from sync context,
        # we'll return the messages to be sent
        return {
            'chat_code': chat_code,
            'customer_id': customer_id,
            'executor_id': executor_id,
            'customer_message': customer_message,
            'executor_message': executor_message
        }
        
        logger.info(f"Chat invitation data prepared for task {task_id} with code {chat_code}")
        return {
            'chat_code': chat_code,
            'customer_id': customer_id,
            'executor_id': executor_id,
            'customer_message': customer_message,
            'executor_message': executor_message
        }
        
    except Exception as e:
        logger.error(f"Failed to prepare chat invitations: {e}")
        return {}

def close_chat_session(task_id: int) -> bool:
    """Close chat session for completed/cancelled task"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE chats SET status = 'closed'
            WHERE task_id = ?
        """, (task_id,))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Closed chat session for task {task_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to close chat session for task {task_id}: {e}")
        return False

def is_chat_active(task_id: int) -> bool:
    """Check if chat session is active for task"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT status FROM chats 
            WHERE task_id = ?
        """, (task_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result and result['status'] == 'active'
        
    except Exception as e:
        logger.error(f"Failed to check chat status for task {task_id}: {e}")
        return False