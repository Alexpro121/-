"""
Executor-specific handlers for Rozdum Bot
"""

import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database import (
    get_user, get_task, update_task, update_user_balance, 
    add_review, create_dispute, get_task_offer, accept_task_offer,
    reject_task_offer, increment_missed_tasks
)
from config import PLATFORM_COMMISSION_RATE, ADMIN_ID

# Configure executor handlers logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def handle_task_offer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle executor's response to task offer."""
    query = update.callback_query
    user_id = query.from_user.id
    try:
        parts = query.data.split('_')
        action = parts[0]  # "accept" or "decline"
        task_id = int(parts[2])  # from "accept_task_123" or "decline_task_123"
    except (ValueError, IndexError):
        await query.answer("❌ Помилка: невірний ID завдання")
        return

    # Check if task exists
    task = get_task(task_id)
    if not task:
        await query.answer("❌ Завдання не знайдено")
        return

    # Check if task is still available (searching or offered)
    if task['status'] not in ['searching', 'offered']:
        await query.answer("❌ Завдання вже недоступне")
        return

    # Check if there's a valid pending offer for this executor
    offer = get_task_offer(task_id, user_id)
    if not offer:
        await query.answer("❌ Завдання вже недоступне")
        return

    if action == "accept":
        # Accept the task offer
        success = accept_task_offer(task_id, user_id)
        if success:
            # Cancel acceptance timer
            from utils.task_timer import TaskTimer
            await TaskTimer.cancel_timer(task_id)

            # Update offer status and reset missed tasks counter
            from database import reset_missed_tasks, update_task_offer_status
            update_task_offer_status(task_id, user_id, 'accepted')
            reset_missed_tasks(user_id)
            # Notify customer
            customer_text = f"""
✅ <b>Виконавець знайдений!</b>

Завдання #{task_id} прийнято до виконання.
Виконавець зв'яжется з вами найближчим часом.

Для спілкування використовуйте чат-бот (буде додано пізніше).
            """

            try:
                await context.bot.send_message(
                    chat_id=task['customer_id'],
                    text=customer_text,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Failed to notify customer {task['customer_id']}: {e}")

            # Confirm to executor
            executor_text = f"""
✅ <b>Завдання прийнято!</b>

ID: #{task_id}
Винагорода: {task['price'] * (1 - PLATFORM_COMMISSION_RATE):.2f} грн

<b>Опис:</b>
{task['description']}

Зв'яжіться з замовником та приступайте до роботи!
            """

            keyboard = [[InlineKeyboardButton("📋 Мої завдання", callback_data="my_tasks")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(executor_text, reply_markup=reply_markup, parse_mode='HTML')

            # Create chat session for anonymous communication
            try:
                import asyncio
                from utils.chat_integration import send_chat_invitations
                chat_data = send_chat_invitations(task_id, task['customer_id'], user_id, context.bot)
                if chat_data and 'chat_code' in chat_data:
                    # Send invitations asynchronously
                    asyncio.create_task(context.bot.send_message(
                        chat_id=chat_data['customer_id'],
                        text=chat_data['customer_message'],
                        parse_mode='HTML'
                    ))
                    asyncio.create_task(context.bot.send_message(
                        chat_id=chat_data['executor_id'], 
                        text=chat_data['executor_message'],
                        parse_mode='HTML'
                    ))
                    logger.info(f"Chat session created for task {task_id} with code {chat_data['chat_code']}")
                else:
                    logger.warning(f"Failed to create chat session for task {task_id}")
            except Exception as e:
                logger.warning(f"Chat integration error: {e}")

        else:
            await query.answer("❌ Не вдалося прийняти завдання")

    elif action == "decline":
        # Cancel acceptance timer
        from utils.task_timer import TaskTimer
        await TaskTimer.cancel_timer(task_id)

        # Reject the task offer
        success = reject_task_offer(task_id, user_id)

        if success:
            # Increment missed tasks counter (same as timeout)
            missed_count = increment_missed_tasks(user_id)

            # Reset task status to searching if no other pending offers
            from database import update_task
            update_task(task_id, status='searching', executor_id=None)

        # Prepare decline message with warning if needed
        decline_message = "❌ Ви відхилили пропозицію.\n\nЗавдання буде запропоновано іншому виконавцю."

        await query.edit_message_text(decline_message, reply_markup=None, parse_mode='HTML')

        # Continue searching with next executor (exclude this executor)
        from utils.taxi_system import find_and_notify_executor
        await find_and_notify_executor(task_id, context.bot, exclude_executor=user_id)

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task completion by executor."""
    query = update.callback_query
    user_id = query.from_user.id
    task_id = int(query.data.split('_')[-1])

    task = get_task(task_id)
    if not task:
        await query.answer("❌ Завдання не знайдено")
        return

    if task['executor_id'] != user_id:
        await query.answer("❌ Це не ваше завдання")
        return

    if task['status'] != 'in_progress':
        await query.answer("❌ Завдання не можна завершити")
        return

    # Mark as pending customer approval
    update_task(task_id, status='pending_approval')

    # Notify customer
    customer_text = f"""
🎯 <b>Завдання готове!</b>

Виконавець позначив завдання #{task_id} як завершене.

Будь ласка, перевірте роботу та підтвердіть виконання або повідомте про проблеми.
    """

    keyboard = [
        [InlineKeyboardButton("👍 Все гаразд, оплатити", callback_data=f"approve_task_{task_id}")],
        [InlineKeyboardButton("⛔ Проблема, відкрити спір", callback_data=f"dispute_task_{task_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=task['customer_id'],
            text=customer_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        await query.edit_message_text(
            "✅ Замовник повідомлений про завершення роботи.\nОчікуйте підтвердження.",
            reply_markup=None
        )

    except Exception as e:
        logger.error(f"Failed to notify customer about completion: {e}")
        await query.answer("❌ Помилка сповіщення замовника")

async def approve_task_completion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task approval by customer."""
    query = update.callback_query
    user_id = query.from_user.id
    task_id = int(query.data.split('_')[-1])

    task = get_task(task_id)
    if not task:
        await query.answer("❌ Завдання не знайдено")
        return

    if task['customer_id'] != user_id:
        await query.answer("❌ Це не ваше завдання")
        return

    if task['status'] != 'pending_approval':
        await query.answer("❌ Завдання не очікує підтвердження")
        return

    # Calculate payment amounts
    executor_payment = task['price'] * (1 - PLATFORM_COMMISSION_RATE)

    # Transfer money to executor
    success = update_user_balance(task['executor_id'], executor_payment)

    # Release frozen funds from customer
    customer = get_user(task['customer_id'])
    frozen_amount = task['price']
    if task.get('is_vip'):
        from config import VIP_TASK_PRICE_LOW, VIP_TASK_PRICE_HIGH, VIP_TASK_THRESHOLD
        vip_cost = VIP_TASK_PRICE_LOW if task['price'] <= VIP_TASK_THRESHOLD else VIP_TASK_PRICE_HIGH
        frozen_amount += vip_cost

    update_user_balance(task['customer_id'], 0, -frozen_amount)

    if success:
        # Mark task as completed
        update_task(task_id, status='completed', completed_at='CURRENT_TIMESTAMP')

        # Notify executor
        executor_text = f"""
🎉 <b>Оплата отримана!</b>

Завдання #{task_id} успішно завершено!
Зараховано: {executor_payment:.2f} грн

Дякуємо за якісну роботу!
        """

        try:
            await context.bot.send_message(
                chat_id=task['executor_id'],
                text=executor_text,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Failed to notify executor about payment: {e}")

        # Show rating interface to customer
        await show_rating_interface(query, task_id, 'customer', context)

    else:
        await query.answer("❌ Помилка переказу коштів")

async def dispute_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle dispute creation by customer."""
    query = update.callback_query
    user_id = query.from_user.id
    task_id = int(query.data.split('_')[-1])

    try:
        task = get_task(task_id)
        if not task:
            await query.answer("❌ Завдання не знайдено")
            return

        if task['customer_id'] != user_id:
            await query.answer("❌ Це не ваше завдання")
            return

        if task['status'] not in ['completed', 'in_progress']:
            await query.answer("❌ Спір можна відкрити тільки для завершених або активних завдань")
            return

        # Create dispute
        dispute_id = create_dispute(
            task_id=task_id,
            customer_id=task['customer_id'],
            executor_id=task['executor_id'],
            reason="Замовник оспорив виконання завдання"
        )

        if dispute_id:
            # Update task status
            update_task(task_id, status='dispute')

            # Get user info for better notifications
            customer = get_user(task['customer_id'])
            executor = get_user(task['executor_id'])

            # Notify admin bot
            admin_text = f"""
🚨 <b>НОВИЙ СПІР!</b>

🆔 <b>Спір:</b> #{dispute_id}
📋 <b>Завдання:</b> #{task_id}
💰 <b>Ціна:</b> {task['price']} грн
📅 <b>Створено:</b> {task['created_at']}

👥 <b>Учасники спору:</b>
🛒 <b>Замовник:</b> {f"@{customer.get('username')}" if customer and customer.get('username') else f"ID: {task['customer_id']}"}
⚡ <b>Виконавець:</b> {f"@{executor.get('username')}" if executor and executor.get('username') else f"ID: {task['executor_id']}"}

💬 <b>Причина спору:</b>
Замовник оспорив виконання завдання

📝 <b>Опис завдання:</b>
{task['description'][:300]}{'...' if len(task['description']) > 300 else ''}

🔧 <b>Необхідні дії:</b>
• Перейдіть до адмін-бота (@Admin_fartobot)
• Перевірте деталі спору
• Перегляньте історію чату
• Прийміть рішення
            """

            # Try to notify admin bot
            try:
                import httpx
                admin_bot_token = os.getenv("ADMIN_BOT_TOKEN")
                admin_user_id = os.getenv("ADMIN_ID", "5857065034")

                if admin_bot_token:
                    url = f"https://api.telegram.org/bot{admin_bot_token}/sendMessage"
                    data = {
                        "chat_id": admin_user_id,
                        "text": admin_text,
                        "parse_mode": "HTML"
                    }

                    async with httpx.AsyncClient() as client:
                        response = await client.post(url, data=data)

                    if response.status_code == 200:
                        logger.info(f"Admin notified about dispute {dispute_id}")
                    else:
                        logger.warning(f"Failed to notify admin: {response.status_code}")
                else:
                    logger.warning("Admin bot token not configured")

            except Exception as e:
                logger.error(f"Failed to notify admin about dispute: {e}")

            # Notify both parties
            dispute_text = f"""
⚠️ <b>Відкрито спір</b>

По завданню #{task_id} відкрито спір.
Адміністратор розгляне ситуацію та прийме рішення.

🆔 <b>Спір ID:</b> #{dispute_id}
💰 <b>Кошти заморожені до вирішення спору</b>

📞 <b>Підтримка:</b> @Admin_fartobot
            """

            await query.edit_message_text(dispute_text, reply_markup=None, parse_mode='HTML')

            # Notify executor
            try:
                await context.bot.send_message(
                    chat_id=task['executor_id'],
                    text=dispute_text,
                    parse_mode='HTML'
                )
                logger.info(f"Executor {task['executor_id']} notified about dispute {dispute_id}")
            except Exception as e:
                logger.error(f"Failed to notify executor about dispute: {e}")

        else:
            await query.answer("❌ Помилка створення спору")
            return

    except Exception as e:
        logger.error(f"Error in dispute_task: {e}")
        await query.answer("❌ Помилка створення спору")

async def show_dispute_interface(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show dispute interface for customer."""
    query = update.callback_query
    user_id = query.from_user.id
    task_id = int(query.data.split('_')[-1])

    try:
        task = get_task(task_id)
        if not task:
            await query.answer("❌ Завдання не знайдено")
            return

        if task['customer_id'] != user_id:
            await query.answer("❌ Це не ваше завдання")
            return

        text = f"""
⚠️ <b>Відкриття спору</b>

📋 <b>Завдання:</b> #{task_id}
💰 <b>Ціна:</b> {task['price']} грн

❓ <b>Коли відкривати спір:</b>
• Виконавець не виконав роботу
• Якість роботи не відповідає вимогам
• Виконавець не відповідає на повідомлення
• Інші порушення угоди

⚠️ <b>УВАГА:</b>
Після відкриття спору кошти будуть заморожені до вирішення адміністратором.

Ви впевнені, що хочете відкрити спір?
        """

        keyboard = [
            [InlineKeyboardButton("⚠️ Відкрити спір", callback_data=f"confirm_dispute_{task_id}")],
            [InlineKeyboardButton("❌ Скасувати", callback_data=f"task_details_{task_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error showing dispute interface: {e}")
        await query.answer("❌ Помилка відображення інтерфейсу спору")

async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task cancellation by customer."""
    query = update.callback_query
    user_id = query.from_user.id
    task_id = int(query.data.split('_')[-1])

    task = get_task(task_id)
    if not task:
        await query.answer("❌ Завдання не знайдено")
        return

    if task['customer_id'] != user_id:
        await query.answer("❌ Це не ваше завдання")
        return

    if task['status'] != 'searching':
        await query.answer("❌ Можна скасувати лише завдання в пошуку виконавця")
        return

    # Cancel task and refund money
    update_task(task_id, status='canceled')

    # Calculate refund amount
    refund_amount = task['price']
    if task.get('is_vip'):
        from config import VIP_TASK_PRICE_LOW, VIP_TASK_PRICE_HIGH, VIP_TASK_THRESHOLD
        vip_cost = VIP_TASK_PRICE_LOW if task['price'] <= VIP_TASK_THRESHOLD else VIP_TASK_PRICE_HIGH
        refund_amount += vip_cost

    # Refund money
    update_user_balance(user_id, refund_amount, -refund_amount)

    text = f"""
❌ <b>Завдання скасовано</b>

Завдання #{task_id} успішно скасовано.
Повернено на баланс: {refund_amount:.2f} грн
    """

    keyboard = [[InlineKeyboardButton("📋 Мої завдання", callback_data="my_tasks")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_rating_interface(query, task_id: int, user_type: str, context) -> None:
    """Show rating interface after task completion."""
    text = f"""
⭐ <b>Оцініть роботу</b>

Завдання #{task_id} завершено!

Будь ласка, оцініть {'виконавця' if user_type == 'customer' else 'замовника'} за 5-бальною шкалою:
    """

    keyboard = []
    for rating in range(1, 6):
        stars = "⭐" * rating
        keyboard.append([InlineKeyboardButton(
            f"{stars} {rating}", 
            callback_data=f"rate_{task_id}_{user_type}_{rating}"
        )])

    keyboard.append([InlineKeyboardButton("⏭️ Пропустити", callback_data="skip_rating")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle rating submission."""
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "skip_rating":
        await query.edit_message_text("Дякуємо за використання ROZDUM 2.0!", reply_markup=None)
        return

    try:
        _, task_id, user_type, rating = query.data.split('_')
        task_id = int(task_id)
        rating = int(rating)
    except ValueError:
        await query.answer("❌ Помилка обробки рейтингу")
        return

    task = get_task(task_id)
    if not task:
        await query.answer("❌ Завдання не знайдено")
        return

    # Determine who rates whom
    if user_type == 'customer':
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

    # Add review
    success = add_review(task_id, reviewer_id, reviewed_id, rating)

    if success:
        text = f"""
✅ <b>Дякуємо за оцінку!</b>

Ви оцінили {reviewed_role} на {rating} {'зірку' if rating == 1 else 'зірки' if rating < 5 else 'зірок'}.

Ваша оцінка допомагає покращити якість платформи!
        """

        # Check if both parties have rated - then show final message
        from database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM reviews WHERE task_id = ?', 
            (task_id,)
        )
        review_count = cursor.fetchone()[0]
        conn.close()

        if review_count >= 2:
            text += "\n\n🎉 Завдання повністю завершено!"

        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    else:
        await query.answer("❌ Помилка збереження оцінки")

# Handler list for main.py
executor_handlers = [
    CallbackQueryHandler(handle_task_offer, pattern="^(accept|decline)_task_"),
    CallbackQueryHandler(complete_task, pattern="^complete_task_"),
    CallbackQueryHandler(approve_task_completion, pattern="^approve_task_"),
    CallbackQueryHandler(show_dispute_interface, pattern="^dispute_task_"),
    CallbackQueryHandler(dispute_task, pattern="^confirm_dispute_"),
    CallbackQueryHandler(cancel_task, pattern="^cancel_task_"),
    CallbackQueryHandler(handle_rating, pattern="^(rate_|skip_rating)"),
]

async def send_task_offer_to_executor(bot, executor: dict, task: dict, chat_code: str) -> bool:
    """Send task offer to executor."""
    try:
        logger.info(f"📤 Надсилання пропозиції виконавцю @{executor.get('username', 'None')} (ID: {executor['user_id']}) для завдання #{task['task_id']}")

        # Calculate commission and net earning
        from config import PLATFORM_COMMISSION_RATE
        commission = task['price'] * PLATFORM_COMMISSION_RATE
        net_earning = task['price'] - commission

        # Format task tags
        tags_text = ""
        if task.get('tags'):
            if isinstance(task['tags'], str):
                import json
                try:
                    tags = json.loads(task['tags'])
                except:
                    tags = []
            else:
                tags = task['tags'] or []

            if tags:
                # Translate tags to Ukrainian
                from utils.tag_translator import translate_tags_to_ukrainian
                ukrainian_tags = translate_tags_to_ukrainian(tags)
                tags_text = f"\n🏷️ Теги: {', '.join(ukrainian_tags)}"

        # Check for files
        files_text = ""
        try:
            from utils.file_handler import get_task_files_info
            files_info = get_task_files_info(task['task_id'])
            if files_info:
                files_text = f"\n📎 Файли: {len(files_info)} прикріплено"
        except:
            pass

        message = f"""
🚖 <b>Нове завдання для вас!</b>

📋 <b>Категорія:</b> {task['category']}
{tags_text}
💰 <b>Ціна:</b> {format_price(task['price'])}
💵 <b>Ваш заробіток:</b> {format_price(net_earning)} (після комісії {PLATFORM_COMMISSION_RATE*100}%)
{'⭐ VIP завдання' if task.get('is_vip') else ''}

📝 <b>Опис:</b>
{task['description'][:500]}{'...' if len(task['description']) > 500 else ''}
{files_text}

💬 <b>Код чату:</b> <code>{chat_code}</code>

У вас є 10 хвилин, щоб прийняти це завдання.
        """

        keyboard = [
            [
                InlineKeyboardButton("✅ Прийняти", callback_data=f"accept_task_{task['task_id']}"),
                InlineKeyboardButton("❌ Відхилити", callback_data=f"decline_task_{task['task_id']}")
            ],
            [InlineKeyboardButton("💬 Написати замовнику", url=f"https://t.me/Rozdum_ChatBot?start={chat_code}")]
        ]

        await bot.send_message(
            chat_id=executor['user_id'],
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

        logger.info(f"✅ Пропозицію надіслано виконавцю @{executor.get('username', 'None')} для завдання #{task['task_id']}")
        return True

    except Exception as e:
        logger.error(f"❌ Помилка надсилання пропозиції виконавцю {executor['user_id']} для завдання #{task['task_id']}: {e}")
        return False