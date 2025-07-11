"""
User profile handlers for Rozdum Bot
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

from database import get_user, update_user, get_user_tasks
from config import UserStates, CATEGORIES

logger = logging.getLogger(__name__)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user profile."""
    query = update.callback_query
    user_id = query.from_user.id if query else update.effective_user.id

    user = get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Помилка: профіль не знайдено")
        return

    # Count tasks
    customer_tasks = get_user_tasks(user_id, as_customer=True)
    executor_tasks = get_user_tasks(user_id, as_customer=False)

    completed_as_customer = len([t for t in customer_tasks if t['status'] == 'completed'])
    completed_as_executor = len([t for t in executor_tasks if t['status'] == 'completed'])

    # Format tags display
    tags_text = "Без тегів"
    if user['executor_tags']:
        try:
            if isinstance(user['executor_tags'], str):
                # Parse JSON if it's a string
                import json
                executor_tags = json.loads(user['executor_tags'])
            elif isinstance(user['executor_tags'], dict):
                executor_tags = user['executor_tags']
            else:
                executor_tags = {}
            
            if executor_tags:
                tags_display = []
                for category, category_tags in executor_tags.items():
                    if category_tags and isinstance(category_tags, list):
                        category_name = CATEGORIES.get(category, {}).get('name', category)
                        tags_list = ', '.join(category_tags)
                        tags_display.append(f"📂 {category_name}: {tags_list}")
                tags_text = '\n'.join(tags_display) if tags_display else "Без тегів"
        except (json.JSONDecodeError, AttributeError, TypeError):
            tags_text = "Без тегів"

    earned_balance = user.get('earned_balance', 0.0)
    available_for_withdrawal = earned_balance
    
    profile_text = f"""
👤 <b>Ваш Профіль</b>

<b>🆔 ID:</b> {user_id}
<b>💰 Загальний баланс:</b> {user['balance']:.2f} грн
<b>💎 Заробленого:</b> {earned_balance:.2f} грн (доступно для виведення)
<b>🧊 Заморожено:</b> {user['frozen_balance']:.2f} грн
<b>⭐ Рейтинг:</b> {user['rating']:.1f}/5.0 ({user['reviews_count']} відгуків)

<b>📊 Статистика:</b>
• Завдань створено: {len(customer_tasks)}
• Завдань виконано: {completed_as_executor}
• Завершено як замовник: {completed_as_customer}

<b>🏷 Теги:</b> {tags_text}

<b>🎯 Профіль виконавця:</b>
{'Налаштований' if user['executor_tags'] else 'Не налаштований'}
    """

    keyboard = [
        [InlineKeyboardButton("💰 Поповнити", callback_data="add_balance"),
         InlineKeyboardButton("💸 Вивести", callback_data="withdraw_balance")],
        [InlineKeyboardButton("⚙️ Профіль Виконавця", callback_data="setup_executor")],
        [InlineKeyboardButton("📊 Детальна Статистика", callback_data="detailed_stats")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(profile_text, reply_markup=reply_markup, parse_mode='HTML')

async def setup_executor_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Setup executor profile - choose categories."""
    query = update.callback_query
    user_id = query.from_user.id

    user = get_user(user_id)
    current_tags = set(user['executor_tags']) if user['executor_tags'] else set()
    is_working = user.get('is_working', True)
    missed_tasks = user.get('missed_tasks_count', 0)

    work_status_emoji = "🟢" if is_working else "🔴"
    work_status_text = "Працюю" if is_working else "Не працюю"

    text = f"""
⚙️ <b>Налаштування Профілю Виконавця</b>

<b>Статус роботи:</b> {work_status_emoji} {work_status_text}
{f"<b>Пропущено завдань:</b> {missed_tasks}" if missed_tasks > 0 else ""}

Оберіть категорії, в яких ви маєте експертизу:
    """

    keyboard = []

    # Work status buttons
    if is_working:
        keyboard.append([InlineKeyboardButton("🔴 Завершити роботу", callback_data="set_not_working")])
    else:
        keyboard.append([InlineKeyboardButton("🟢 Почати працювати", callback_data="set_working")])

    # Category selection - check if user has tags in this category
    user = get_user(user_id)
    user_category_tags = user.get('executor_tags', {}) if isinstance(user.get('executor_tags'), dict) else {}

    for category_key, category_data in CATEGORIES.items():
        has_category = category_key in user_category_tags and len(user_category_tags[category_key]) > 0

        emoji = "✅" if has_category else "⭕"
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {category_data['name']}", 
            callback_data=f"executor_category_{category_key}"
        )])

    keyboard.extend([
        [InlineKeyboardButton("💾 Зберегти та Завершити", callback_data="save_executor_profile")],
        [InlineKeyboardButton("🔙 Назад до Профілю", callback_data="my_profile")]
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def setup_executor_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Setup executor tags for specific category."""
    query = update.callback_query
    user_id = query.from_user.id
    category_key = query.data.split('_')[-1]

    if category_key not in CATEGORIES:
        await query.answer("❌ Невідома категорія")
        return

    user = get_user(user_id)
    user_tags = user['executor_tags'] if isinstance(user['executor_tags'], dict) else {}
    current_category_tags = set(user_tags.get(category_key, []))
    category_data = CATEGORIES[category_key]

    text = f"""
🎯 <b>{category_data['name']}</b>

Оберіть теги вашої експертизи:
    """

    keyboard = []
    for tag in category_data['tags']:
        emoji = "✅" if tag in current_category_tags else "⭕"
        # Format Ukrainian tags properly
        tag_display = tag.replace('-', ' ').replace('_', ' ')
        if tag_display.lower() in ['python', 'javascript', 'react', 'django', 'fastapi', 'postgresql', 'powerpoint', 'keynote']:
            tag_display = tag_display.upper() if len(tag_display) <= 4 else tag_display.title()
        else:
            tag_display = tag_display.title()

        keyboard.append([InlineKeyboardButton(
            f"{emoji} {tag_display}", 
            callback_data=f"toggle_tag_{tag}"
        )])

    keyboard.extend([
        [InlineKeyboardButton("🔙 Назад до Категорій", callback_data="setup_executor")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def toggle_executor_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle executor tag on/off."""
    query = update.callback_query
    user_id = query.from_user.id
    tag = query.data.split('_', 2)[-1]

    user = get_user(user_id)
    current_tags = user['executor_tags'] if isinstance(user['executor_tags'], dict) else {}

    # Find category for this tag
    category_key = None
    for cat_key, cat_data in CATEGORIES.items():
        if tag in cat_data['tags']:
            category_key = cat_key
            break

    if not category_key:
        await query.answer("❌ Невідомий тег")
        return

    # Toggle tag
    tag_was_present = False
    if category_key not in current_tags:
        current_tags[category_key] = []

    if tag in current_tags[category_key]:
        current_tags[category_key].remove(tag)
        tag_was_present = True
        # Remove category if empty
        if not current_tags[category_key]:
            del current_tags[category_key]
    else:
        current_tags[category_key].append(tag)

    # Update user tags in database
    update_user(user_id, executor_tags=current_tags)

    # Rebuild the category tags display with updated data
    user = get_user(user_id)  # Get fresh user data
    user_category_tags = user.get('executor_tags', {}) if isinstance(user.get('executor_tags'), dict) else {}
    current_category_tags = set(user_category_tags.get(category_key, []))
    category_data = CATEGORIES[category_key]

    text = f"""
🎯 <b>{category_data['name']}</b>

Оберіть теги вашої експертизи:
    """

    keyboard = []
    for tag_name in category_data['tags']:
        emoji = "✅" if tag_name in current_category_tags else "⭕"
        # Format Ukrainian tags properly
        tag_display = tag_name.replace('-', ' ').replace('_', ' ')
        if tag_display.lower() in ['python', 'javascript', 'react', 'django', 'fastapi', 'postgresql', 'powerpoint', 'keynote']:
            tag_display = tag_display.upper() if len(tag_display) <= 4 else tag_display.title()
        else:
            tag_display = tag_display.title()

        keyboard.append([InlineKeyboardButton(
            f"{emoji} {tag_display}", 
            callback_data=f"toggle_tag_{tag_name}"
        )])

    keyboard.extend([
        [InlineKeyboardButton("🔙 Назад до Категорій", callback_data="setup_executor")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        # Show confirmation without alert
        action_text = "видалено" if tag_was_present else "додано"
        await query.answer(f"✅ Тег '{tag}' {action_text}")
    except Exception as e:
        logger.error(f"Error updating message in toggle_executor_tag: {e}")
        # If message update fails, just answer with confirmation
        action_text = "видалено" if tag_was_present else "додано"
        await query.answer(f"✅ Тег '{tag}' {action_text}")

async def save_executor_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save executor profile and return to main profile."""
    query = update.callback_query
    user_id = query.from_user.id

    user = get_user(user_id)
    tags_count = len(user['executor_tags']) if user['executor_tags'] else 0

    if tags_count == 0:
        await query.answer("❌ Оберіть хоча б один тег експертизи", show_alert=True)
        return

    await query.answer(f"✅ Профіль збережено! Обрано {tags_count} тегів експертизи")

    # Return to profile - create new Update for profile view
    await show_profile(update, context)

async def show_detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed user statistics."""
    query = update.callback_query
    user_id = query.from_user.id

    customer_tasks = get_user_tasks(user_id, as_customer=True)
    executor_tasks = get_user_tasks(user_id, as_customer=False)

    # Calculate statistics
    stats = {
        'total_created': len(customer_tasks),
        'total_executed': len(executor_tasks),
        'created_completed': len([t for t in customer_tasks if t['status'] == 'completed']),
        'created_cancelled': len([t for t in customer_tasks if t['status'] == 'canceled']),
        'created_disputes': len([t for t in customer_tasks if t['status'] == 'dispute']),
        'executed_completed': len([t for t in executor_tasks if t['status'] == 'completed']),
        'executed_disputes': len([t for t in executor_tasks if t['status'] == 'dispute']),
        'active_as_customer': len([t for t in customer_tasks if t['status'] in ['searching', 'in_progress']]),
        'active_as_executor': len([t for t in executor_tasks if t['status'] in ['searching', 'in_progress']])
    }

    # Calculate earnings and spendings
    total_spent = sum(t['price'] for t in customer_tasks if t['status'] == 'completed')
    total_earned = sum(t['price'] * 0.95 for t in executor_tasks if t['status'] == 'completed')  # minus 5% commission

    stats_text = f"""
📊 <b>Детальна Статистика</b>

<b>💼 Як Замовник:</b>
• Всього створено: {stats['total_created']}
• Завершено: {stats['created_completed']}
• Скасовано: {stats['created_cancelled']}
• Активних: {stats['active_as_customer']}
• Спори: {stats['created_disputes']}
• Витрачено: {total_spent:.2f} грн

<b>🔧 Як Виконавець:</b>
• Всього виконано: {stats['total_executed']}
• Завершено: {stats['executed_completed']}
• Активних: {stats['active_as_executor']}
• Спори: {stats['executed_disputes']}
• Заробленено: {total_earned:.2f} грн

<b>📈 Ефективність:</b>
• Успішність як замовник: {(stats['created_completed']/max(stats['total_created'], 1)*100):.1f}%
• Успішність як виконавець: {(stats['executed_completed']/max(stats['total_executed'], 1)*100):.1f}%
    """

    keyboard = [[InlineKeyboardButton("🔙 Назад до Профілю", callback_data="my_profile")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_balance_operations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle balance add/withdraw operations."""
    query = update.callback_query
    operation = query.data

    if operation == "add_balance":
        text = """
💰 <b>Поповнення Балансу</b>

На даному етапі поповнення балансу здійснюється вручну через адміністратора.

Для поповнення:
1. Зверніться до адміністратора
2. Вкажіть ваш ID: {user_id}
3. Вкажіть суму для поповнення

Незабаром буде додана автоматична оплата!
        """.format(user_id=query.from_user.id)

    elif operation == "withdraw_balance":
        user = get_user(query.from_user.id)
        available_balance = user['balance']

        text = f"""
💸 <b>Виведення Коштів</b>

Доступно для виведення: {available_balance:.2f} грн

На даному етапі виведення коштів здійснюється вручну через адміністратора.

Для виведення:
1. Зверніться до адміністратора  
2. Вкажіть ваш ID: {query.from_user.id}
3. Вкажіть суму та реквізити

Мінімальна сума виведення: 50 грн
        """

    keyboard = [[InlineKeyboardButton("🔙 Назад до Профілю", callback_data="my_profile")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def set_work_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle work status change."""
    query = update.callback_query
    user_id = query.from_user.id

    from database import set_work_status, reset_missed_tasks

    if query.data == "set_working":
        success = set_work_status(user_id, True)
        if success:
            # Reset missed tasks counter when starting work
            reset_missed_tasks(user_id)
            await query.answer("✅ Статус змінено на 'Працюю'. Тепер ви будете отримувати завдання!")
        else:
            await query.answer("❌ Помилка при зміні статусу")
    elif query.data == "set_not_working":
        success = set_work_status(user_id, False)
        if success:
            await query.answer("✅ Статус змінено на 'Не працюю'. Завдання не будуть надходити.")
        else:
            await query.answer("❌ Помилка при зміні статусу")

    # Refresh the executor profile page
    await setup_executor_profile(update, context)

# Handler list for main.py
profile_handlers = [
    CallbackQueryHandler(show_profile, pattern="^my_profile$"),
    CallbackQueryHandler(setup_executor_profile, pattern="^setup_executor$"),
    CallbackQueryHandler(setup_executor_tags, pattern="^executor_category_"),
    CallbackQueryHandler(toggle_executor_tag, pattern="^toggle_tag_"),
    CallbackQueryHandler(save_executor_profile, pattern="^save_executor_profile$"),
    CallbackQueryHandler(show_detailed_stats, pattern="^detailed_stats$"),
    CallbackQueryHandler(handle_balance_operations, pattern="^(add_balance|withdraw_balance)$"),
    CallbackQueryHandler(set_work_status_handler, pattern="^(set_working|set_not_working)$"),
]