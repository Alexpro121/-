
"""
Admin handlers for task scheduler management
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database import get_user, get_tasks_waiting_for_executors
from utils.task_scheduler import manual_search_executors as scheduler_manual_search, get_scheduler_status

logger = logging.getLogger(__name__)

async def admin_manual_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin manual search for all waiting tasks."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Check admin permissions
    user = get_user(user_id)
    if not user or user.get('admin_level', 0) < 3:
        await query.answer("❌ Доступ заборонений")
        return
    
    try:
        await query.edit_message_text(
            "🔍 <b>Запуск ручного пошуку виконавців...</b>\n\n"
            "Обробляємо всі завдання в черзі.\n"
            "Це може зайняти кілька хвилин...",
            parse_mode='HTML'
        )
        
        # Run manual search
        results = await scheduler_manual_search()
        
        text = f"✅ <b>Ручний пошук завершено!</b>\n\n"
        text += f"📊 <b>Результати:</b>\n"
        text += f"• Оброблено завдань: {results['processed']}\n"
        text += f"• Знайдено виконавців: {results['found']}\n"
        text += f"• Помилок: {results['failed']}\n\n"
        
        if results['found'] > 0:
            text += "🎉 Виконавці отримали сповіщення про нові завдання!"
        else:
            text += "⏳ Підходящих виконавців наразі немає."
        
        keyboard = [
            [InlineKeyboardButton("📊 Статус черги", callback_data="search_status")],
            [InlineKeyboardButton("🔄 Повторити пошук", callback_data="admin_manual_search")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in admin manual search: {e}")
        await query.answer("❌ Помилка виконання пошуку")

# Admin handler exports
admin_handlers = [
    CallbackQueryHandler(admin_manual_search, pattern="^admin_manual_search$"),
]
