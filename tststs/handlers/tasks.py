"""
Task management handlers for Rozdum Bot
"""

import logging
import os
import asyncio
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

from database import (
    get_user, update_user, create_task, get_task, update_task, 
    get_user_tasks, update_user_balance,
    get_user_temp_files, update_temp_files_task_id, delete_user_temp_files,
    get_db_connection
)
from config import (
    UserStates, CATEGORIES, MINIMUM_TASK_PRICE, VIP_TASK_PRICE_LOW, 
    VIP_TASK_PRICE_HIGH, VIP_TASK_THRESHOLD, PLATFORM_COMMISSION_RATE, 
    VIP_EXECUTOR_MIN_RATING
)
from utils.taxi_system import find_and_notify_executor
from utils.helpers import get_category_emoji
from utils.file_handler import handle_task_file_upload, cleanup_temp_files, format_file_size, get_file_icon

# Configure task handlers logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Constants
MIN_DESCRIPTION_LENGTH = 20
MAX_DESCRIPTION_PREVIEW = 200
STATUS_EMOJIS = {
    'searching': '🔍',
    'in_progress': '⚙️', 
    'completed': '✅',
    'dispute': '⚠️',
    'canceled': '❌'
}

class TaskCreationSteps:
    """Constants for task creation step messages"""

    CATEGORY_TEXT = """
📝 <b>Крок 1/6: Категорія</b>

Оберіть категорію вашого завдання:
    """

    TAGS_TEXT = """
📝 <b>Крок 2/6: Теги</b>

Категорія: {category_name}

Оберіть теги, що описують ваше завдання:
    """

    DESCRIPTION_TEXT = """
📝 <b>Крок 3/6: Опис завдання</b>

Категорія: {category_name}
Теги: {tags_text}

Надішліть детальний опис вашого завдання:
• Що потрібно зробити?
• Які вимоги до результату?
• Які матеріали ви надасте?
• Коли потрібно завершити?

Чим детальніше опис, тим краще!
    """

    FILES_TEXT = """
📝 <b>Крок 4/6: Файли завдання</b>

📎 Додайте файли до завдання (необов'язково):

📋 <b>Ви можете прикріпити:</b>
• Документи (PDF, DOC, TXT тощо)
• Зображення (JPG, PNG, GIF тощо)
• Архіви (ZIP, RAR тощо)
• Презентації (PPT, PPTX тощо)
• Інші файли до 150 МБ

📄 <b>Поточні файли:</b>
{files_list}

Надішліть файли або натисніть "Далі" для продовження.
    """

    PRICE_TEXT = """
📝 <b>Крок 5/6: Ціна</b>

Вкажіть ціну, яку ви готові заплатити за виконання завдання (в гривнях):

💡 Пам'ятайте:
• Комісія платформи: 10% (сплачує виконавець)
• Мінімальна ціна: 25 грн
• Якість роботи залежить від справедливої ціни
    """

def format_tags_text(tags: List[str]) -> str:
    """Format tags list for display with proper Ukrainian formatting"""
    formatted_tags = []
    for tag in tags:
        # Format Ukrainian tags properly
        tag_display = tag.replace('-', ' ').replace('_', ' ')
        if tag_display.lower() in ['python', 'javascript', 'react', 'django', 'fastapi', 'postgresql', 'powerpoint', 'keynote']:
            tag_display = tag_display.upper() if len(tag_display) <= 4 else tag_display.title()
        else:
            tag_display = tag_display.title()
        formatted_tags.append(tag_display)
    return ", ".join(formatted_tags)

def calculate_total_cost(price: float, is_vip: bool) -> float:
    """Calculate total cost including VIP fee"""
    vip_cost = 0
    if is_vip:
        vip_cost = VIP_TASK_PRICE_LOW if price <= VIP_TASK_THRESHOLD else VIP_TASK_PRICE_HIGH
    return price + vip_cost

def get_vip_cost(price: float) -> float:
    """Get VIP cost based on task price"""
    return VIP_TASK_PRICE_LOW if price <= VIP_TASK_THRESHOLD else VIP_TASK_PRICE_HIGH

def build_category_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for category selection"""
    keyboard = []
    for category_key, category_data in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(
            category_data['name'], 
            callback_data=f"task_category_{category_key}"
        )])

    keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def build_tags_keyboard(category_key: str, selected_tags: set) -> InlineKeyboardMarkup:
    """Build keyboard for tag selection"""
    keyboard = []
    category_data = CATEGORIES[category_key]

    for tag in category_data['tags']:
        emoji = "✅" if tag in selected_tags else "⭕"
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {tag.replace('_', ' ').title()}", 
            callback_data=f"task_tag_{tag}"
        )])

    keyboard.extend([
        [InlineKeyboardButton("➡️ Далі", callback_data="task_tags_next")],
        [InlineKeyboardButton("🔙 Назад", callback_data="create_task")]
    ])

    return InlineKeyboardMarkup(keyboard)

async def start_task_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start task creation process."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Reset user state and temp data
        update_user(user_id, state=UserStates.CREATING_TASK_CATEGORY, temp_data={})

        reply_markup = build_category_keyboard()
        await query.edit_message_text(
            TaskCreationSteps.CATEGORY_TEXT, 
            reply_markup=reply_markup, 
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error starting task creation for user {user_id}: {e}")
        await query.answer("❌ Помилка при створенні завдання")

async def select_task_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task category selection."""
    query = update.callback_query
    user_id = query.from_user.id
    category_key = query.data.split('_')[-1]

    if category_key not in CATEGORIES:
        await query.answer("❌ Невідома категорія")
        return

    try:
        user = get_user(user_id)

        # Create user if doesn't exist
        if not user:
            from database import create_user
            create_user(user_id, query.from_user.username)
            user = get_user(user_id)

        if not user:
            logger.error(f"Failed to create/get user {user_id}")
            await query.answer("❌ Помилка користувача")
            return

        temp_data = user['temp_data'].copy()
        temp_data['category'] = category_key

        update_user(user_id, state=UserStates.CREATING_TASK_TAGS, temp_data=temp_data)

        category_data = CATEGORIES[category_key]
        text = TaskCreationSteps.TAGS_TEXT.format(category_name=category_data['name'])

        reply_markup = build_tags_keyboard(category_key, set())
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error selecting category for user {user_id}: {e}")
        await query.answer("❌ Помилка вибору категорії")

async def toggle_task_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle task tag selection."""
    query = update.callback_query
    user_id = query.from_user.id
    tag = query.data.split('_', 2)[-1]

    try:
        user = get_user(user_id)
        temp_data = user['temp_data'].copy()
        selected_tags = set(temp_data.get('tags', []))

        if tag in selected_tags:
            selected_tags.remove(tag)
        else:
            selected_tags.add(tag)

        temp_data['tags'] = list(selected_tags)
        update_user(user_id, temp_data=temp_data)

        # Refresh the display
        category_key = temp_data['category']
        category_data = CATEGORIES[category_key]

        text = TaskCreationSteps.TAGS_TEXT.format(category_name=category_data['name'])
        reply_markup = build_tags_keyboard(category_key, selected_tags)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error toggling tag for user {user_id}: {e}")
        await query.answer("❌ Помилка обробки тегу")

async def task_tags_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proceed to task description step."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)
        temp_data = user['temp_data']
        selected_tags = temp_data.get('tags', [])

        if not selected_tags:
            await query.answer("❌ Оберіть хоча б один тег", show_alert=True)
            return

        update_user(user_id, state=UserStates.CREATING_TASK_DESCRIPTION)

        category_name = CATEGORIES[temp_data['category']]['name']
        tags_text = format_tags_text(selected_tags)

        text = TaskCreationSteps.DESCRIPTION_TEXT.format(
            category_name=category_name,
            tags_text=tags_text
        )

        keyboard = [[InlineKeyboardButton("🔙 Назад до тегів", callback_data="task_select_tags")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error proceeding to description for user {user_id}: {e}")
        await query.answer("❌ Помилка переходу до опису")

async def handle_task_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task description input."""
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user['state'] != UserStates.CREATING_TASK_DESCRIPTION:
        return

    description = update.message.text
    if len(description) < MIN_DESCRIPTION_LENGTH:
        await update.message.reply_text(f"❌ Опис надто короткий. Мінімум {MIN_DESCRIPTION_LENGTH} символів.")
        return

    try:
        temp_data = user['temp_data'].copy()
        temp_data['description'] = description

        update_user(user_id, state=UserStates.CREATING_TASK_FILES, temp_data=temp_data)

        await show_files_step(update, user_id)

    except Exception as e:
        logger.error(f"Error handling description for user {user_id}: {e}")
        await update.message.reply_text("❌ Помилка обробки опису")

async def show_files_step(update: Update, user_id: int, edit_message: bool = False, message_to_edit=None) -> None:
    """Show the files upload step with single updatable message."""
    try:
        user = get_user(user_id)
        temp_data = user['temp_data']

        # Get current uploaded files
        current_files = get_user_temp_files(user_id)

        # Format files list with individual delete buttons
        if current_files:
            files_list = "\n".join([
                f"{get_file_icon(file['file_type'])} {file['original_name']} ({format_file_size(file['file_size'])})"
                for file in current_files
            ])
        else:
            files_list = "📁 Файли ще не додано"

        # Build keyboard with individual delete buttons for each file
        keyboard = []

        # Add individual delete buttons for each file
        if current_files:
            for i, file in enumerate(current_files):
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑️ Видалити {file['original_name'][:20]}{'...' if len(file['original_name']) > 20 else ''}", 
                        callback_data=f"delete_temp_file_{file['id']}"
                    )
                ])

        # Navigation buttons
        keyboard.extend([
            [InlineKeyboardButton("➡️ Далі", callback_data="task_files_next")],
            [InlineKeyboardButton("🔙 Назад до опису", callback_data="task_files_back")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="confirm_main_menu_exit")]
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Create comprehensive text
        text = f"""📝 <b>Крок 4/6: Файли завдання</b>

📎 <b>Додайте файли до завдання (необов'язково):</b>

📋 <b>Ви можете прикріпити:</b>
• Документи (PDF, DOC, TXT тощо)
• Зображення (JPG, PNG, GIF тощо)
• Архіви (ZIP, RAR тощо)
• Презентації (PPT, PPTX тощо)
• Інші файли до 150 МБ

📄 <b>Поточні файли:</b>
{files_list}

<i>Надішліть файли або натисніть "Далі" для продовження.</i>"""

        # Send or edit the message
        if edit_message and message_to_edit:
            await message_to_edit.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        elif hasattr(update, 'message') and update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.effective_chat.send_message(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing files step for user {user_id}: {e}")
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text("❌ Помилка відображення кроку файлів")

async def handle_task_file_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle file upload during task creation."""
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user['state'] != UserStates.CREATING_TASK_FILES:
        return

    try:
        # Handle file upload using the utility function
        file_info = await handle_task_file_upload(update, context)

        if file_info:
            # React to file message to show success
            try:
                await update.message.set_reaction("✅")
            except:
                pass  # Ignore if reaction fails

            # Send only a simple confirmation message
            await update.message.reply_text(
                f"✅ Файл завантажено: {file_info['original_name']}\n"
                f"📁 Розмір: {format_file_size(file_info['file_size'])}"
            )

    except Exception as e:
        logger.error(f"Error handling task file upload for user {user_id}: {e}")
        await update.message.reply_text("❌ Помилка завантаження файлу")

async def handle_task_files_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle proceeding from files step to price step."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)

        if user['state'] != UserStates.CREATING_TASK_FILES:
            await query.answer("❌ Неправильний стан")
            return

        # Move to price step
        update_user(user_id, state=UserStates.CREATING_TASK_PRICE)

        await query.edit_message_text(TaskCreationSteps.PRICE_TEXT, parse_mode='HTML')
        await query.answer("➡️ Перехід до ціни")

    except Exception as e:
        logger.error(f"Error proceeding from files to price for user {user_id}: {e}")
        await query.answer("❌ Помилка переходу")

async def handle_task_files_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle going back from files step to description step."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)
        temp_data = user['temp_data']

        # Go back to description step
        update_user(user_id, state=UserStates.CREATING_TASK_DESCRIPTION)

        category_name = CATEGORIES[temp_data['category']]['name']
        tags_text = format_tags_text(temp_data['tags'])

        text = TaskCreationSteps.DESCRIPTION_TEXT.format(
            category_name=category_name,
            tags_text=tags_text
        )

        await query.edit_message_text(text, parse_mode='HTML')
        await query.answer("🔙 Повернення до опису")

    except Exception as e:
        logger.error(f"Error going back from files to description for user {user_id}: {e}")
        await query.answer("❌ Помилка повернення")

async def handle_task_files_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle clearing all uploaded files."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Clean up temp files
        cleanup_temp_files(user_id)

        # Refresh the files step display
        fake_update = type('FakeUpdate', (), {'callback_query': query})()
        await show_files_step(fake_update, user_id, edit_message=True, message_to_edit=query.message)
        await query.answer("🗑️ Файли видалено")

    except Exception as e:
        logger.error(f"Error clearing files for user {user_id}: {e}")
        await query.answer("❌ Помилка видалення файлів")

async def handle_delete_temp_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle deleting individual temp file."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Extract file ID from callback data
        file_id = int(query.data.split("_")[-1])

        # Delete the specific file from database
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get file info first
        cursor.execute("SELECT file_path, original_name FROM task_files WHERE id = ? AND user_id = ?", 
                      (file_id, user_id))
        file_info = cursor.fetchone()

        if file_info:
            file_path, original_name = file_info

            # Delete file from filesystem
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

            # Delete from database
            cursor.execute("DELETE FROM task_files WHERE id = ? AND user_id = ?", (file_id, user_id))
            conn.commit()

        conn.close()

        # Update the files step display
        await show_files_step(query, user_id, edit_message=True, message_to_edit=query.message)
        await query.answer(f"🗑️ Файл видалено")

    except Exception as e:
        logger.error(f"Error deleting temp file for user {user_id}: {e}")
        await query.answer("❌ Помилка видалення файлу")

async def handle_task_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task price input."""
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user['state'] != UserStates.CREATING_TASK_PRICE:
        return

    try:
        price = float(update.message.text.replace(',', '.'))
        if price < MINIMUM_TASK_PRICE:
            await update.message.reply_text(f"❌ Мінімальна ціна: {MINIMUM_TASK_PRICE} грн")
            return
    except ValueError:
        await update.message.reply_text("❌ Введіть коректну ціну (число)")
        return

    try:
        temp_data = user['temp_data'].copy()
        temp_data['price'] = price

        update_user(user_id, state=UserStates.CREATING_TASK_VIP, temp_data=temp_data)

        await show_vip_selection(update, temp_data, price)

    except Exception as e:
        logger.error(f"Error handling price for user {user_id}: {e}")
        await update.message.reply_text("❌ Помилка обробки ціни")

async def show_vip_selection(update: Update, temp_data: Dict, price: float) -> None:
    """Show VIP selection interface"""
    vip_price = get_vip_cost(price)

    text = f"""
🎯 <b>VIP-статус завдання</b>

Бажаєте зробити ваше завдання VIP? 

✨ <b>Переваги VIP:</b>
• Пріоритетний показ топ-виконавцям (рейтинг 4.0+)
• Швидше знаходження виконавця  
• Вища якість виконання

💰 <b>Вартість VIP-статусу:</b>
• До 100 грн: 10 грн
• Понад 100 грн: 15 грн
• Ваша доплата: {vip_price} грн

📊 <b>Поточна інформація:</b>
• Категорія: {temp_data.get('category', 'Не вказано')}
• Теги: {', '.join(temp_data.get('tags', []))}
• Ціна завдання: {price} грн
• VIP-доплата: {vip_price} грн

⚠️ <b>УВАГА:</b> При поверненні в головне меню всі дані завдання буде втрачено!
    """

    keyboard = [
        [InlineKeyboardButton("⭐ VIP Пропозиція", callback_data="task_vip_yes")],
        [InlineKeyboardButton("📋 Звичайна пропозиція", callback_data="task_vip_no")],
        [InlineKeyboardButton("🔙 Змінити ціну", callback_data="task_change_price")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_task_vip_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle VIP choice and show final confirmation."""
    query = update.callback_query
    user_id = query.from_user.id
    is_vip = query.data == "task_vip_yes"

    try:
        user = get_user(user_id)
        temp_data = user['temp_data'].copy()
        temp_data['is_vip'] = is_vip

        update_user(user_id, state=UserStates.CREATING_TASK_CONFIRM, temp_data=temp_data)

        await show_task_confirmation(query, user, temp_data)

    except Exception as e:
        logger.error(f"Error handling VIP choice for user {user_id}: {e}")
        await query.answer("❌ Помилка обробки VIP вибору")

async def show_task_confirmation(query, user: Dict, temp_data: Dict) -> None:
    """Show final task confirmation"""
    price = temp_data['price']
    is_vip = temp_data['is_vip']
    vip_cost = get_vip_cost(price) if is_vip else 0
    total_cost = calculate_total_cost(price, is_vip)

    # Build confirmation text
    category_name = CATEGORIES[temp_data['category']]['name']
    tags_text = format_tags_text(temp_data['tags'])
    category_emoji = get_category_emoji(temp_data['category'])

    description_preview = temp_data['description']
    if len(description_preview) > MAX_DESCRIPTION_PREVIEW:
        description_preview = description_preview[:MAX_DESCRIPTION_PREVIEW] + "..."

    text = f"""
🧾 <b>ЧЕК РОЗРАХУНКУ</b>
{'═' * 25}

📋 <b>Деталі завдання:</b>
Категорія: {category_emoji} {category_name}  
Теги: {tags_text}

💡 <b>Опис:</b>
{description_preview}

{'═' * 25}
💰 <b>РОЗРАХУНОК:</b>

Ціна за роботу: {price:.2f} грн
{"VIP доплата: " + f"{vip_cost:.2f} грн" if is_vip else ""}
{'─' * 25}
<b>ВСЬОГО ДО СПЛАТИ: {total_cost:.2f} грн</b>
{'═' * 25}

💳 Ваш баланс: {user['balance']:.2f} грн

{'🌟 VIP завдання - тільки топ-виконавці!' if is_vip else '📢 Стандартне завдання - всі виконавці'}
    """

    if user['balance'] < total_cost:
        keyboard = [
            [InlineKeyboardButton("💳 СПЛАТИТИ", callback_data="add_balance")],
            [InlineKeyboardButton("🔙 Повернутися до перегляду", callback_data="task_review_back")],
            [InlineKeyboardButton("🔄 Змінити завдання", callback_data="create_task")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("✅ Підтвердити та Створити", callback_data="task_create_final")],
            [InlineKeyboardButton("🔙 Повернутися до перегляду", callback_data="task_review_back")],
            [InlineKeyboardButton("🔄 Змінити завдання", callback_data="create_task")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def create_task_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create the task and start executor search."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)
        temp_data = user['temp_data']

        price = temp_data['price']
        is_vip = temp_data['is_vip']
        total_cost = calculate_total_cost(price, is_vip)

        # Check balance again
        if user['balance'] < total_cost:
            await query.answer("❌ Недостатньо коштів на балансі", show_alert=True)
            return

        # Freeze funds
        success = update_user_balance(user_id, -total_cost, total_cost)
        if not success:
            await query.answer("❌ Помилка списання коштів", show_alert=True)
            return

        # Create task
        task_id = create_task(
            customer_id=user_id,
            category=temp_data['category'],
            tags=temp_data['tags'],
            description=temp_data['description'],
            price=price,
            is_vip=is_vip
        )

        if not task_id:
            # Rollback balance change
            update_user_balance(user_id, total_cost, -total_cost)
            await query.answer("❌ Помилка створення завдання", show_alert=True)
            return

        # Move temporary files to the created task
        try:
            update_temp_files_task_id(user_id, task_id)
            logger.info(f"Moved temp files to task {task_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Error moving temp files for task {task_id}: {e}")

        # Reset user state
        update_user(user_id, state=UserStates.NONE, temp_data={})

        # Start executor search
        executor_found = await find_and_notify_executor(task_id, context.bot)

        # If no executor found immediately, add to search queue
        if not executor_found:
            try:
                from utils.task_scheduler import add_task_to_scheduler
                await add_task_to_scheduler(task_id)
                logger.info(f"Task {task_id} added to automatic search queue")
            except Exception as e:
                logger.error(f"Failed to add task {task_id} to scheduler: {e}")

        status_text = ("🔍 Завдання створено! Шукаємо виконавця..." if executor_found 
                      else "⏳ Завдання створено! Підходящих виконавців зараз немає, але автоматичний пошук продовжується.")

        await show_task_created_message(query, task_id, total_cost, status_text)

    except Exception as e:
        logger.error(f"Error creating final task for user {user_id}: {e}")
        await query.answer("❌ Помилка створення завдання")

async def show_task_created_message(query, task_id: int, total_cost: float, status_text: str) -> None:
    """Show task created confirmation message"""
    text = f"""
✅ <b>Завдання успішно створено!</b>

🆔 ID завдання: #{task_id}
💰 Списано з балансу: {total_cost:.2f} грн

{status_text}

Ви отримаєте повідомлення, коли виконавець прийме завдання.
    """

    keyboard = [
        [InlineKeyboardButton("📋 Мої завдання", callback_data="my_tasks")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's tasks."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        customer_tasks = get_user_tasks(user_id, as_customer=True)
        executor_tasks = get_user_tasks(user_id, as_customer=False)

        text = build_my_tasks_text(customer_tasks, executor_tasks)

        # Check if user has searching tasks for manual search button
        has_searching_tasks = any(task['status'] == 'searching' for task in customer_tasks)

        keyboard = [
            [InlineKeyboardButton("🔍 Активні завдання", callback_data="active_tasks")],
            [InlineKeyboardButton("📝 Створити завдання", callback_data="create_task")]
        ]

        if has_searching_tasks:
            keyboard.append([InlineKeyboardButton("🔎 Почати пошук виконавців", callback_data="manual_search_executors")])

        keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing tasks for user {user_id}: {e}")
        await query.answer("❌ Помилка завантаження завдань")

def build_my_tasks_text(customer_tasks: List[Dict], executor_tasks: List[Dict]) -> str:
    """Build text for my tasks display"""
    text = "📋 <b>Мої Завдання</b>\n\n"

    if customer_tasks:
        text += "<b>🛒 Як замовник:</b>\n"
        for task in customer_tasks[:5]:  # Show last 5
            emoji = STATUS_EMOJIS.get(task['status'], '❓')
            text += f"{emoji} #{task['task_id']} - {task['price']:.0f} грн ({task['status']})\n"

    if executor_tasks:
        text += "\n<b>🔧 Як виконавець:</b>\n"
        for task in executor_tasks[:5]:  # Show last 5
            emoji = STATUS_EMOJIS.get(task['status'], '❓')
            text += f"{emoji} #{task['task_id']} - {task['price']:.0f} грн ({task['status']})\n"

    if not customer_tasks and not executor_tasks:
        text += "Завдань поки немає.\n\nСтворіть своє перше завдання або налаштуйте профіль виконавця!"

    return text

async def show_active_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show active tasks with action buttons."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        active_statuses = ['searching', 'in_progress']
        customer_tasks = [t for t in get_user_tasks(user_id, as_customer=True) 
                         if t['status'] in active_statuses]
        executor_tasks = [t for t in get_user_tasks(user_id, as_customer=False) 
                         if t['status'] in active_statuses]

        text, keyboard = build_active_tasks_display(customer_tasks, executor_tasks)

        keyboard.append([InlineKeyboardButton("🔙 Всі завдання", callback_data="my_tasks")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing active tasks for user {user_id}: {e}")
        await query.answer("❌ Помилка завантаження активних завдань")

def build_active_tasks_display(customer_tasks: List[Dict], executor_tasks: List[Dict]) -> tuple:
    """Build display for active tasks"""
    text = "🔍 <b>Активні Завдання</b>\n\n"
    keyboard = []

    if customer_tasks:
        text += "<b>🛒 Ваші замовлення:</b>\n"
        for task in customer_tasks:
            status_text = "Пошук виконавця" if task['status'] == 'searching' else "Виконується"
            text += f"#{task['task_id']} - {task['price']:.0f} грн ({status_text})\n"

            if task['status'] == 'searching':
                keyboard.append([InlineKeyboardButton(
                    f"❌ Скасувати #{task['task_id']}", 
                    callback_data=f"cancel_task_{task['task_id']}"
                )])

    if executor_tasks:
        text += "\n<b>🔧 Виконуєте:</b>\n"
        for task in executor_tasks:
            text += f"#{task['task_id']} - {task['price']:.0f} грн\n"
            keyboard.append([InlineKeyboardButton(
                f"✅ Завершити #{task['task_id']}", 
                callback_data=f"complete_task_{task['task_id']}"
            )])

    if not customer_tasks and not executor_tasks:
        text += "Активних завдань немає."

    return text, keyboard

# Navigation handlers
async def task_select_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to tag selection step."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)
        temp_data = user['temp_data']

        if 'category' not in temp_data:
            await start_task_creation(update, context)
            return

        # Simulate category selection to return to tags
        query.data = f"task_category_{temp_data['category']}"
        await select_task_category(update, context)

    except Exception as e:
        logger.error(f"Error returning to tags for user {user_id}: {e}")
        await start_task_creation(update, context)

async def task_change_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to price input step.""" 
    query = update.callback_query
    user_id = query.from_user.id

    try:
        update_user(user_id, state=UserStates.CREATING_TASK_PRICE)
        await query.edit_message_text(TaskCreationSteps.PRICE_TEXT, parse_mode='HTML')
        await query.answer()

    except Exception as e:
        logger.error(f"Error changing price for user {user_id}: {e}")
        await query.answer("❌ Помилка зміни ціни")

async def task_review_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to VIP choice step from confirmation."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)
        temp_data = user['temp_data']

        if not temp_data or 'price' not in temp_data:
            await start_task_creation(update, context)
            return

        # Set state back to VIP choice
        update_user(user_id, state=UserStates.CREATING_TASK_VIP)

        price = temp_data['price']
        vip_price = get_vip_cost(price)

        text = f"""
🎯 <b>VIP-статус завдання</b>

Бажаєте зробити ваше завдання VIP? 

✨ <b>Переваги VIP:</b>
• Пріоритетний показ топ-виконавцям (рейтинг 4.0+)
• Швидше знаходження виконавця  
• Вища якість виконання

💰 <b>Вартість VIP-статусу:</b>
• До 100 грн: 10 грн
• Понад 100 грн: 15 грн
• Ваша доплата: {vip_price} грн

📊 <b>Поточна інформація:</b>
• Категорія: {temp_data.get('category', 'Не вказано')}
• Теги: {', '.join(temp_data.get('tags', []))}
• Ціна: {price} грн
• VIP-доплата: {vip_price} грн

💳 <b>Загальна сума до списання:</b> {price + vip_price} грн
        """

        keyboard = [
            [InlineKeyboardButton("⭐ VIP Пропозиція", callback_data="task_vip_yes")],
            [InlineKeyboardButton("📋 Звичайна пропозиція", callback_data="task_vip_no")],
            [InlineKeyboardButton("🔙 Змінити ціну", callback_data="task_change_price")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error reviewing task for user {user_id}: {e}")
        await start_task_creation(update, context)

async def confirm_main_menu_exit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show confirmation dialog when user wants to return to main menu during task creation."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)

        # Create user if doesn't exist
        if not user:
            from database import create_user
            create_user(user_id, query.from_user.username)
            user = get_user(user_id)

        if not user:
            logger.error(f"Failed to create/get user {user_id}")
            from handlers.start import start_command
            await start_command(update, context)
            return

        # Check if user is in task creation process
        task_creation_states = [
            UserStates.CREATING_TASK_CATEGORY, UserStates.CREATING_TASK_TAGS, 
            UserStates.CREATING_TASK_DESCRIPTION, UserStates.CREATING_TASK_PRICE, 
            UserStates.CREATING_TASK_VIP, UserStates.CREATING_TASK_CONFIRM
        ]

        if user['state'] in task_creation_states:
            text = """
⚠️ <b>УВАГА!</b>

Якщо ви повернетеся до головного меню, усі введені дані буде втрачено. Завдання не збережеться автоматично.

Ви впевнені, що хочете вийти?
            """

            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data="stay_in_task")],
                [InlineKeyboardButton("🏠 В меню", callback_data="confirm_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            # If not in task creation, go directly to main menu
            from handlers.start import start_command
            await start_command(update, context)

    except Exception as e:
        logger.error(f"Error confirming main menu exit for user {user_id}: {e}")
        from handlers.start import start_command
        await start_command(update, context)

async def stay_in_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return user back to their current task creation step."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        user = get_user(user_id)
        state = user['state']

        if state == UserStates.CREATING_TASK_CATEGORY:
            await start_task_creation(update, context)
        elif state == UserStates.CREATING_TASK_TAGS:
            temp_data = user['temp_data']
            if 'category' in temp_data:
                query.data = f"task_category_{temp_data['category']}"
                await select_task_category(update, context)
            else:
                await start_task_creation(update, context)
        elif state == UserStates.CREATING_TASK_VIP:
            await task_review_back(update, context)
        elif state == UserStates.CREATING_TASK_CONFIRM:
            # Return to confirmation step
            temp_data = user['temp_data']
            if temp_data.get('is_vip') is not None:
                query.data = "task_vip_yes" if temp_data['is_vip'] else "task_vip_no"
                await handle_task_vip_choice(update, context)
            else:
                await task_review_back(update, context)
        else:
            await start_task_creation(update, context)

    except Exception as e:
        logger.error(f"Error staying in task for user {user_id}: {e}")
        await start_task_creation(update, context)

async def confirm_main_menu_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear task data and go to main menu."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Clear user state and temp data
        update_user(user_id, state=UserStates.NONE, temp_data={})

        # Go to main menu
        from handlers.start import start_command
        await start_command(update, context)

    except Exception as e:
        logger.error(f"Error confirming final main menu for user {user_id}: {e}")
        from handlers.start import start_command
        await start_command(update, context)

async def manual_search_executors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually trigger executor search for user's tasks."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Get user's searching tasks
        customer_tasks = get_user_tasks(user_id, as_customer=True)
        searching_tasks = [task for task in customer_tasks if task['status'] == 'searching']

        if not searching_tasks:
            await query.answer("❌ У вас немає завдань, що шукають виконавців", show_alert=True)
            return

        # Show progress message
        await query.edit_message_text(
            f"🔍 <b>Запуск пошуку виконавців...</b>\n\n"
            f"Обробляємо {len(searching_tasks)} завдань.\n"
            f"Будь ласка, зачекайте...",
            parse_mode='HTML'
        )

        # Search for executors
        found_count = 0
        from utils.taxi_system import find_and_notify_executor

        for task in searching_tasks:
            try:
                executor_found = await find_and_notify_executor(task['task_id'], context.bot)
                if executor_found:
                    found_count += 1
                await asyncio.sleep(0.5)  # Small delay between searches
            except Exception as e:
                logger.error(f"Error searching for task {task['task_id']}: {e}")

        # Show results
        if found_count > 0:
            result_text = f"✅ <b>Пошук завершено!</b>\n\n" \
                         f"Знайдено виконавців: {found_count} з {len(searching_tasks)}\n" \
                         f"Ви отримаєте повідомлення коли виконавці приймуть завдання."
        else:
            result_text = f"⏳ <b>Пошук завершено</b>\n\n" \
                         f"Наразі немає доступних виконавців для ваших завдань.\n" \
                         f"Автоматичний пошук продовжується у фоновому режимі."

        keyboard = [
            [InlineKeyboardButton("🔄 Повторити пошук", callback_data="manual_search_executors")],
            [InlineKeyboardButton("📋 Мої завдання", callback_data="my_tasks")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error in manual executor search for user {user_id}: {e}")
        await query.answer("❌ Помилка пошуку виконавців")

async def show_search_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current search queue status (admin only)."""
    query = update.callback_query
    user_id = query.from_user.id

    # Check if user is admin
    user = get_user(user_id)
    if not user or user.get('admin_level', 0) < 3:
        await query.answer("❌ Доступ заборонений")
        return

    try:
        from utils.task_scheduler import get_scheduler_status
        from database import get_tasks_waiting_for_executors

        status = get_scheduler_status()
        waiting_tasks = get_tasks_waiting_for_executors()

        text = f"📊 <b>Статус системи пошуку</b>\n\n"
        text += f"🔄 Система працює: {'✅ Так' if status['is_running'] else '❌ Ні'}\n"
        text += f"⏱️ Інтервал пошуку: {status['search_interval']} сек\n"
        text += f"📋 Завдань в черзі: {status['waiting_tasks_count']}\n"
        text += f"🔍 Активних пошуків: {status['active_searches_count']}\n\n"

        if waiting_tasks:
            text += "<b>Завдання в черзі:</b>\n"
            for task in waiting_tasks[:5]:  # Show first 5
                text += f"• #{task['task_id']} - {task['category']} ({task['attempts_count']} спроб)\n"
            if len(waiting_tasks) > 5:
                text += f"... та ще {len(waiting_tasks) - 5} завдань\n"
        else:
            text += "Черга пуста ✨"

        keyboard = [
            [InlineKeyboardButton("🔄 Оновити", callback_data="search_status")],
            [InlineKeyboardButton("🔍 Запустити пошук", callback_data="admin_manual_search")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing search status: {e}")
        await query.answer("❌ Помилка отримання статусу")

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route text input based on user state."""
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        return

    try:
        if user['state'] == UserStates.CREATING_TASK_DESCRIPTION:
            await handle_task_description(update, context)
        elif user['state'] == UserStates.CREATING_TASK_FILES:
            # Handle file uploads in the files step
            await handle_task_file_message(update, context)
        elif user['state'] == UserStates.CREATING_TASK_PRICE:
            await handle_task_price(update, context)
        else:
            # For profile handlers or other text input
            from handlers.profile import handle_balance_operations
            if user['state'] in [UserStates.ADDING_BALANCE, UserStates.WITHDRAWING_BALANCE]:
                await handle_balance_operations(update, context)

    except Exception as e:
        logger.error(f"Error handling text input for user {user_id}: {e}")

async def handle_add_interest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle adding suggested tag to user interests."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Parse callback data: add_interest_taskid_category_tag
        parts = query.data.split('_')
        if len(parts) < 5:
            await query.answer("❌ Помилка обробки запиту")
            return

        task_id = int(parts[2])
        category = parts[3]
        suggested_tag = parts[4]

        # Get user's current executor tags
        user = get_user(user_id)
        if not user:
            await query.answer("❌ Користувач не знайдений")
            return

        executor_tags = user.get('executor_tags', {})

        # Add the suggested tag to user's interests
        if category not in executor_tags:
            executor_tags[category] = []

        if suggested_tag not in executor_tags[category]:
            executor_tags[category].append(suggested_tag)

        # Update user's executor tags
        update_user(user_id, executor_tags=executor_tags)

        # Send thank you message
        await query.edit_message_text(
            "✅ <b>Дякуємо за відгук!</b>\n\nТег додано до ваших інтересів. Тепер ви отримуватимете більше підходящих завдань!",
            parse_mode='HTML'
        )

        # Schedule message deletion and task reassignment
        asyncio.create_task(cleanup_suggestion_and_reassign(query.message.chat_id, query.message.message_id, task_id, context.bot))

        logger.info(f"Added suggested tag '{suggested_tag}' to user {user_id} in category '{category}'")

    except Exception as e:
        logger.error(f"Error handling add interest: {e}")
        await query.answer("❌ Помилка обробки запиту")

async def handle_skip_interest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle skipping suggested tag."""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # Parse callback data: skip_interest_taskid
        parts = query.data.split('_')
        if len(parts) < 3:
            await query.answer("❌ Помилка обробки запиту")
            return

        task_id = int(parts[2])

        # Send thank you message
        await query.edit_message_text(
            "✅ <b>Дякуємо за відгук!</b>\n\nПошук виконавця продовжується з поточними налаштуваннями.",
            parse_mode='HTML'
        )

        # Schedule message deletion and task reassignment
        asyncio.create_task(cleanup_suggestion_and_reassign(query.message.chat_id, query.message.message_id, task_id, context.bot))

        logger.info(f"User {user_id} skipped suggested tag for task {task_id}")

    except Exception as e:
        logger.error(f"Error handling skip interest: {e}")
        await query.answer("❌ Помилка обробки запиту")

async def cleanup_suggestion_and_reassign(chat_id: int, message_id: int, task_id: int, bot):
    """Clean up suggestion message and reassign task after 15 seconds."""
    try:
        # Wait 15 seconds
        await asyncio.sleep(15)

        # Delete the message
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.warning(f"Could not delete suggestion message: {e}")

        # Reassign the task with updated user preferences
        from utils.taxi_system import find_and_notify_executor
        await find_and_notify_executor(task_id, bot)

        logger.info(f"Cleaned up suggestion message and reassigned task {task_id}")

    except Exception as e:
        logger.error(f"Error in cleanup and reassign: {e}")

async def handle_tag_suggestion_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user response to tag suggestions."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data.startswith("add_tag_"):
        # User wants to add the suggested tag
        parts = data.split("_", 3)
        if len(parts) >= 4:
            category = parts[2]
            tag = parts[3]

            # Add tag to user interests
            user = get_user(user_id)
            if user:
                current_tags = user.get('executor_tags', {})
                if isinstance(current_tags, str):
                    try:
                        current_tags = json.loads(current_tags)
                    except:
                        current_tags = {}

                if category not in current_tags:
                    current_tags[category] = []

                if tag not in current_tags[category]:
                    current_tags[category].append(tag)
                    update_user(user_id, executor_tags=current_tags)

                    logger.info(f"✅ Додавання тегу — успішно: користувач {user_id}, тег '{tag}'")
                    logger.info(f"💬 Відповідь користувача — цікаво: тег '{tag}'")
                else:
                    logger.info(f"⚠️ Додавання тегу — пропущено: тег '{tag}' вже існує")

        # Send thank you message and schedule deletion
        thank_you_msg = await query.edit_message_text("Дякуємо за відгук!")

        # Schedule deletion of both messages after 15 seconds
        async def delete_messages():
            await asyncio.sleep(15)
            try:
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=thank_you_msg.message_id
                )
            except:
                pass

        asyncio.create_task(delete_messages())

    elif data.startswith("skip_tag_"):
        # User doesn't want the suggested tag
        parts = data.split("_", 3)
        if len(parts) >= 4:
            tag = parts[3]
            logger.info(f"💬 Відповідь користувача — не цікаво: тег '{tag}'")

        # Send thank you message and schedule deletion
        thank_you_msg = await query.edit_message_text("Дякуємо за відгук!")

        # Schedule deletion after 15 seconds
        async def delete_messages():
            await asyncio.sleep(15)
            try:
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=thank_you_msg.message_id
                )
            except:
                pass

        asyncio.create_task(delete_messages())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for task management."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # Handle tag suggestion responses
    if data.startswith("add_tag_") or data.startswith("skip_tag_"):
        await handle_tag_suggestion_response(update, context)
        return

# Handler exports
task_handlers = [
    CallbackQueryHandler(start_task_creation, pattern="^create_task$"),
    CallbackQueryHandler(select_task_category, pattern="^task_category_"),
    CallbackQueryHandler(toggle_task_tag, pattern="^task_tag_"),
    CallbackQueryHandler(task_tags_next, pattern="^task_tags_next$"),
    CallbackQueryHandler(task_select_tags, pattern="^task_select_tags$"),
    CallbackQueryHandler(handle_task_files_next, pattern="^task_files_next$"),
    CallbackQueryHandler(handle_task_files_back, pattern="^task_files_back$"),
    CallbackQueryHandler(handle_task_files_clear, pattern="^task_files_clear$"),
    CallbackQueryHandler(handle_task_vip_choice, pattern="^task_vip_(yes|no)$"),
    CallbackQueryHandler(task_change_price, pattern="^task_change_price$"), 
    CallbackQueryHandler(task_review_back, pattern="^task_review_back$"),
    CallbackQueryHandler(create_task_final, pattern="^task_create_final$"),
    CallbackQueryHandler(show_my_tasks, pattern="^my_tasks$"),
    CallbackQueryHandler(show_active_tasks, pattern="^active_tasks$"),
    CallbackQueryHandler(manual_search_executors, pattern="^manual_search_executors$"),
    CallbackQueryHandler(show_search_status, pattern="^search_status$"),
    CallbackQueryHandler(confirm_main_menu_exit, pattern="^main_menu$"),
    CallbackQueryHandler(stay_in_task, pattern="^stay_in_task$"),
    CallbackQueryHandler(confirm_main_menu_final, pattern="^confirm_main_menu$"),
    CallbackQueryHandler(handle_add_interest, pattern="^add_interest_"),
    CallbackQueryHandler(handle_skip_interest, pattern="^skip_interest_"),
    CallbackQueryHandler(handle_callback)
]

task_message_handlers = [
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
    MessageHandler(filters.Document.ALL, handle_task_file_message),
    MessageHandler(filters.PHOTO, handle_task_file_message),
    MessageHandler(filters.VIDEO, handle_task_file_message),
    MessageHandler(filters.AUDIO, handle_task_file_message),
    MessageHandler(filters.VOICE, handle_task_file_message),
]