"""
Rating and review system for chat bot
"""

import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters
from database import get_user, get_task, add_review, get_user_reviews, get_user_rating_history

logger = logging.getLogger(__name__)

async def show_rating_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show rating request after task completion."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Extract task_id and role from callback data
        _, task_id, role = query.data.split('_')
        task_id = int(task_id)

        task = get_task(task_id)
        if not task:
            await query.answer("❌ Завдання не знайдено")
            return

        # Determine who rates whom
        if role == 'customer':
            reviewer_id = task['customer_id']
            reviewed_id = task['executor_id']
            reviewed_role = "виконавця"
        else:
            reviewer_id = task['executor_id']
            reviewed_id = task['customer_id']
            reviewed_role = "замовника"

        if reviewer_id != user_id:
            await query.answer("❌ Помилка доступу")
            return

        text = f"""
⭐ <b>Оцініть роботу</b>

Завдання #{task_id} завершено!

Будь ласка, оцініть {reviewed_role} за 5-бальною шкалою:

🌟 1 - Дуже погано
🌟🌟 2 - Погано  
🌟🌟🌟 3 - Задовільно
🌟🌟🌟🌟 4 - Добре
🌟🌟🌟🌟🌟 5 - Відмінно
        """

        keyboard = []
        for rating in range(1, 6):
            stars = "⭐" * rating
            keyboard.append([InlineKeyboardButton(
                f"{stars} {rating}", 
                callback_data=f"rate_{task_id}_{role}_{rating}"
            )])

        keyboard.append([InlineKeyboardButton("⏭️ Пропустити", callback_data="skip_rating")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing rating request: {e}")
        await query.answer("❌ Помилка відображення рейтингу")

async def handle_rating_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle rating submission."""
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "skip_rating":
        await query.edit_message_text(
            "Дякуємо за використання ROZDUM 2.0! 🎉",
            reply_markup=None
        )
        return

    try:
        _, task_id, role, rating = query.data.split('_')
        task_id = int(task_id)
        rating = int(rating)

        task = get_task(task_id)
        if not task:
            await query.answer("❌ Завдання не знайдено")
            return

        # Determine who rates whom
        if role == 'customer':
            reviewer_id = task['customer_id']
            reviewed_id = task['executor_id']
            reviewed_role = "виконавця"
        else:
            reviewer_id = task['executor_id']
            reviewed_id = task['customer_id']
            reviewed_role = "замовника"

        if reviewer_id != user_id:
            await query.answer("❌ Помилка доступу")
            return

        # Show comment input request
        context.user_data['pending_review'] = {
            'task_id': task_id,
            'reviewer_id': reviewer_id,
            'reviewed_id': reviewed_id,
            'rating': rating,
            'reviewed_role': reviewed_role
        }

        text = f"""
✅ <b>Оцінка прийнята: {rating} {'зірка' if rating == 1 else 'зірки' if rating < 5 else 'зірок'}</b>

Бажаєте залишити коментар про {reviewed_role}? 

Ваш відгук допоможе іншим користувачам зробити правильний вибір.

💬 Напишіть коментар або натисніть "Пропустити":
        """

        keyboard = [[InlineKeyboardButton("⏭️ Пропустити коментар", callback_data="submit_rating_no_comment")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error handling rating submission: {e}")
        await query.answer("❌ Помилка обробки рейтингу")

async def handle_rating_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle rating comment input."""
    user_id = update.effective_user.id

    if 'pending_review' not in context.user_data:
        return

    comment = update.message.text.strip()

    if len(comment) > 500:
        await update.message.reply_text("❌ Коментар занадто довгий. Максимум 500 символів.")
        return

    try:
        review_data = context.user_data['pending_review']

        # Add review with comment
        success = add_review(
            task_id=review_data['task_id'],
            reviewer_id=review_data['reviewer_id'],
            reviewed_id=review_data['reviewed_id'],
            rating=review_data['rating'],
            comment=comment
        )

        if success:
            await finalize_rating(update, context, review_data, comment)
        else:
            await update.message.reply_text("❌ Помилка збереження відгуку")

        # Clear pending review
        del context.user_data['pending_review']

    except Exception as e:
        logger.error(f"Error handling rating comment: {e}")
        await update.message.reply_text("❌ Помилка обробки коментарю")

async def submit_rating_no_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit rating without comment."""
    query = update.callback_query

    if 'pending_review' not in context.user_data:
        await query.answer("❌ Помилка: немає активного відгуку")
        return

    try:
        review_data = context.user_data['pending_review']

        # Add review without comment
        success = add_review(
            task_id=review_data['task_id'],
            reviewer_id=review_data['reviewer_id'],
            reviewed_id=review_data['reviewed_id'],
            rating=review_data['rating']
        )

        if success:
            await finalize_rating_query(query, context, review_data)
        else:
            await query.answer("❌ Помилка збереження відгуку")

        # Clear pending review
        del context.user_data['pending_review']

    except Exception as e:
        logger.error(f"Error submitting rating without comment: {e}")
        await query.answer("❌ Помилка збереження відгуку")

async def finalize_rating(update: Update, context: ContextTypes.DEFAULT_TYPE, review_data: dict, comment: str = None) -> None:
    """Finalize rating process."""
    text = f"""
🎉 <b>Дякуємо за відгук!</b>

Ви оцінили {review_data['reviewed_role']} на {review_data['rating']} {'зірку' if review_data['rating'] == 1 else 'зірки' if review_data['rating'] < 5 else 'зірок'}.

{'📝 Ваш коментар: "' + comment + '"' if comment else ''}

Ваша оцінка допомагає покращити якість платформи! ⭐
    """

    await update.message.reply_text(text, parse_mode='HTML')

async def finalize_rating_query(query, context: ContextTypes.DEFAULT_TYPE, review_data: dict) -> None:
    """Finalize rating process from callback query."""
    text = f"""
🎉 <b>Дякуємо за відгук!</b>

Ви оцінили {review_data['reviewed_role']} на {review_data['rating']} {'зірку' if review_data['rating'] == 1 else 'зірки' if review_data['rating'] < 5 else 'зірок'}.

Ваша оцінка допомагає покращити якість платформи! ⭐
    """

    await query.edit_message_text(text, reply_markup=None, parse_mode='HTML')

async def show_user_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's rating statistics and reviews."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Extract target user ID from callback data if present
        if '_' in query.data:
            target_user_id = int(query.data.split('_')[-1])
        else:
            target_user_id = user_id

        # Get rating statistics
        stats = get_user_rating_stats(target_user_id)
        reviews = get_user_reviews(target_user_id, limit=10)

        if not stats:
            text = "📊 <b>Статистика рейтингу</b>\n\nУ користувача поки немає оцінок."
        else:
            text = f"""
📊 <b>Статистика рейтингу</b>

⭐ Середній рейтинг: {stats['average_rating']:.1f}/5.0
📈 Всього оцінок: {stats['total_reviews']}
🎯 Завершених завдань: {stats['completed_tasks']}

📊 <b>Розподіл оцінок:</b>
⭐⭐⭐⭐⭐ 5 зірок: {stats.get('rating_5', 0)}
⭐⭐⭐⭐ 4 зірки: {stats.get('rating_4', 0)}
⭐⭐⭐ 3 зірки: {stats.get('rating_3', 0)}
⭐⭐ 2 зірки: {stats.get('rating_2', 0)}
⭐ 1 зірка: {stats.get('rating_1', 0)}
            """

        if reviews:
            text += "\n\n💬 <b>Останні відгуки:</b>\n"
            for review in reviews:
                stars = "⭐" * review['rating']
                text += f"\n{stars} {review['rating']}/5"
                if review.get('comment'):
                    comment = review['comment'][:100] + "..." if len(review['comment']) > 100 else review['comment']
                    text += f"\n💭 \"{comment}\""
                text += f"\n📅 {review['created_at'][:10]}\n"

        keyboard = [
            [InlineKeyboardButton("🔄 Оновити", callback_data=f"reviews_{target_user_id}")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing user reviews: {e}")
        await query.answer("❌ Помилка завантаження відгуків")

# Rating handler exports
rating_handlers = [
    CallbackQueryHandler(show_rating_request, pattern="^rating_"),
    CallbackQueryHandler(handle_rating_submission, pattern="^rate_"),
    CallbackQueryHandler(submit_rating_no_comment, pattern="^submit_rating_no_comment$"),
    CallbackQueryHandler(show_user_reviews, pattern="^reviews"),
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rating_comment),
]