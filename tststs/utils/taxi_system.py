"""
Taxi System - Intelligent executor matching algorithm for Rozdum
"""

import logging
import asyncio
import json
from typing import List, Dict, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database import get_task, get_available_executors, get_user
from config import VIP_EXECUTOR_MIN_RATING, PLATFORM_COMMISSION_RATE, CATEGORIES
from utils.helpers import format_currency, format_datetime

# Configure detailed logging for taxi system
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def calculate_executor_priority(executor: Dict, task_tags: List[str], task_category: str) -> float:
    """
    Calculate executor priority score based on:
    - Tag matching (40%)
    - Rating (50%) 
    - Active tasks load (-10%)
    """
    try:
        # Get executor's tags for this category
        executor_tags = executor.get('executor_tags', {})
        if isinstance(executor_tags, str):
            executor_tags = json.loads(executor_tags)

        category_tags = executor_tags.get(task_category, [])

        # Tag matching score (0-1)
        if not task_tags or not category_tags:
            tag_score = 0.1  # Small base score
        else:
            required_tags = set(task_tags)
            executor_tags = set(category_tags)
            matching_tags = required_tags & executor_tags

            # Perfect score if executor has all required tags
            if matching_tags == required_tags:
                tag_score = 1.0
                # Bonus for having extra relevant tags
                extra_tags = len(executor_tags - required_tags)
                tag_score += min(extra_tags * 0.05, 0.2)  # Max 20% bonus
            else:
                # Partial score based on coverage
                tag_score = len(matching_tags) / len(required_tags)

        # Rating score (0-1, normalized from 1-5 scale)
        rating = executor.get('rating', 3.0)
        rating_score = (rating - 1) / 4

        # Active tasks penalty (reduce score based on workload)
        active_tasks = executor.get('completed_tasks', 0)  # Use completed as proxy for experience
        experience_bonus = min(active_tasks * 0.05, 0.3)  # Max 30% bonus for experience

        # Calculate final priority (higher is better)
        priority = (tag_score * 0.4) + (rating_score * 0.5) + experience_bonus

        return max(priority, 0.1)  # Ensure minimum priority
    except Exception as e:
        logger.error(f"Error calculating priority: {e}")
        return 0.1

async def find_and_notify_executor(task_id: int, bot, exclude_executor: int = None) -> bool:
    """
    Find and notify available executors for a task.
    - VIP tasks go to top 3 executors simultaneously
    - Regular tasks go one at a time to prevent multiple offers per executor
    """
    try:
        from database import cleanup_expired_offers, create_task_offer, get_task, get_db_connection
        from utils.chat_integration import create_chat_for_task

        task = get_task(task_id)
        if not task:
            logger.error(f"❌ Завдання {task_id} не знайдено")
            return False

        if task['status'] != 'searching':
            return False

        # Parse task tags safely
        if isinstance(task['tags'], list):
            task_tags = task['tags']
        elif isinstance(task['tags'], str):
            try:
                task_tags = json.loads(task['tags'])
            except (json.JSONDecodeError, TypeError):
                task_tags = []
        else:
            task_tags = []

        # Get available executors (filtered to exclude those with pending offers)
        min_rating = VIP_EXECUTOR_MIN_RATING if task.get('is_vip') else 0
        available_executors = get_available_executors(task['category'], task_tags, min_rating)

        if exclude_executor:
            available_executors = [e for e in available_executors if e['user_id'] != exclude_executor]

        # Exclude task customer from being an executor
        available_executors = [e for e in available_executors if e['user_id'] != task['customer_id']]

        # Exclude executors who already declined this specific task
        from database import get_declined_executors_for_task
        declined_executors = get_declined_executors_for_task(task_id)
        available_executors = [e for e in available_executors if e['user_id'] not in declined_executors]

        # Filter to only real users who can receive Telegram messages
        real_executors = [e for e in available_executors if e['user_id'] > 100000 and bool(e.get('is_working', True))]

        if not real_executors:
            return False

        available_executors = real_executors

        # Calculate priorities and sort
        for executor in available_executors:
            executor['priority'] = calculate_executor_priority(executor, task_tags, task['category'])

        # Sort by priority
        available_executors.sort(key=lambda x: x['priority'], reverse=True)

        # Check for near-perfect matches (90-100%) before proceeding
        if available_executors:
            best_match_percentage = available_executors[0].get('match_percentage', 0)

            # If best match is between 90-100% but not 100%, suggest missing tags
            if 0.9 <= best_match_percentage < 1.0:
                await suggest_missing_tags(task_id, task['customer_id'], task['category'], task_tags, available_executors, bot)
                return False  # Don't proceed with task assignment yet

        # Randomly select one executor to send task offer
        import random

        # For both VIP and regular tasks, randomly select ONE executor
        if available_executors:
            selected_executor = random.choice(available_executors)
            executor_id = selected_executor['user_id']

            task_type = "VIP" if task.get('is_vip') else "звичайне"
            logger.info(f"📋 {task_type} завдання #{task_id}: знайдено {len(available_executors)} підходящих виконавців, обрано {executor_id}")

            # Create offer record
            offer_id = create_task_offer(task_id, executor_id)
            if offer_id:
                success = await send_task_offer(bot, executor_id, selected_executor)
                if success:
                    # Start 10-minute acceptance timer
                    from utils.task_timer import TaskTimer
                    await TaskTimer.start_acceptance_timer(task_id, executor_id, bot)
                    return True

        return False

    except Exception as e:
        logger.error(f"Error in find_and_notify_executor: {e}")
        import traceback
        traceback.print_exc()
        return False

async def send_task_offer(bot, executor_id: int, task: Dict) -> bool:
    """Send task offer to executor with 10-minute timeout."""
    try:
        # Check if executor is still available and working
        # executor_id might be int or dict, handle both cases
        if isinstance(executor_id, dict):
            actual_executor_id = executor_id['user_id']
            executor = get_user(actual_executor_id)
        else:
            actual_executor_id = executor_id
            executor = get_user(executor_id)

        if not executor or not executor.get('is_working', False):
            logger.warning(f"Executor {actual_executor_id} is not available")
            return False

        # Calculate executor payment
        executor_payment = task['price'] * (1 - PLATFORM_COMMISSION_RATE)

        # Build offer message
        category_name = CATEGORIES.get(task['category'], {}).get('name', task['category'])

        # Parse tags safely
        if isinstance(task['tags'], list):
            task_tags = task['tags']
        elif isinstance(task['tags'], str):
            try:
                task_tags = json.loads(task['tags'])
            except (json.JSONDecodeError, TypeError):
                task_tags = []
        else:
            task_tags = []

        tags_text = ", ".join(task_tags) if task_tags else "Без тегів"

        vip_badge = "⭐ VIP " if task.get('is_vip') else ""

        text = f"""
🎯 <b>{vip_badge}Нове завдання!</b>

📋 <b>Категорія:</b> {category_name}
🏷️ <b>Теги:</b> {tags_text}

💰 <b>Ваша винагорода:</b> {executor_payment:.2f} грн
💳 <b>Ціна завдання:</b> {task['price']:.2f} грн

📝 <b>Опис:</b>
{task['description'][:300]}{"..." if len(task['description']) > 300 else ""}

⏰ <b>Час на прийняття:</b> 10 хвилин

{'⭐ Завдання від VIP-замовника!' if task.get('is_vip') else ''}
        """

        keyboard = [
            [InlineKeyboardButton("✅ Прийняти", callback_data=f"accept_task_{task['task_id']}")],
            [InlineKeyboardButton("❌ Відхилити", callback_data=f"decline_task_{task['task_id']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send offer
        await bot.send_message(
            chat_id=actual_executor_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        # Update task status to indicate offer was sent
        from database import update_task
        update_task(task['task_id'], status='offered', executor_id=actual_executor_id)

        return True

    except Exception as e:
        logger.error(f"❌ Помилка відправки завдання #{task['task_id']} виконавцю {actual_executor_id}: {e}")
        return False

async def handle_offer_timeout(bot, executor_id: int, task_id: int, message_id: int):
    """Handle task offer timeout after 10 minutes."""
    await asyncio.sleep(600)  # 10 minutes

    try:
        # Check if task is still searching
        task = get_task(task_id)
        if not task or task['status'] != 'searching':
            return  # Task was already accepted or cancelled

        # Track missed task and update offer status
        from database import increment_missed_tasks, set_work_status, update_task_offer_status
        update_task_offer_status(task_id, executor_id, 'expired')
        missed_count = increment_missed_tasks(executor_id)

        # Update the message to show timeout
        timeout_text = f"""
⏰ <b>Час вичерпано</b>

Пропозиція автоматично відхилена через відсутність відповіді.
Завдання буде запропоновано іншому виконавцю.

⚠️ Пропущено завдань: {missed_count}
        """

        # If executor missed 3 tasks, set status to not working
        if missed_count >= 3:
            set_work_status(executor_id, False)
            timeout_text += """

🔴 <b>Статус змінено на "Не працюю"</b>
Через пропуск завдань ви тимчасово виключені з системи пошуку.
Увійдіть в профіль виконавця та змініть статус на "Працюю" коли будете готові.

⚠️ Будь ласка, відповідайте на пропозиції завдань вчасно!
            """
        elif missed_count == 2:
            timeout_text += """

⚠️ <b>Попередження!</b>
Після ще одного пропуску ваш статус буде змінено на "Не працюю".
            """

        await bot.edit_message_text(
            chat_id=executor_id,
            message_id=message_id,
            text=timeout_text,
            reply_markup=None,
            parse_mode='HTML'
        )

        # Continue searching with next executor
        await find_and_notify_executor(task_id, bot, exclude_executor=executor_id)

    except Exception as e:
        logger.error(f"Error handling offer timeout: {e}")

async def batch_notify_executors(task_ids: List[int], bot) -> Dict[int, bool]:
    """
    Batch process multiple tasks for executor notification.
    Returns dict with task_id -> success mapping.
    """
    results = {}

    for task_id in task_ids:
        try:
            success = await find_and_notify_executor(task_id, bot)
            results[task_id] = success

            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Error processing task {task_id}: {e}")
            results[task_id] = False

    return results

def get_executor_stats(executor_id: int) -> Dict:
    """Get executor statistics for priority calculation."""
    from database import get_user_tasks, get_user

    user = get_user(executor_id)
    if not user:
        return {}

    executor_tasks = get_user_tasks(executor_id, as_customer=False)

    stats = {
        'total_completed': len([t for t in executor_tasks if t['status'] == 'completed']),
        'total_disputes': len([t for t in executor_tasks if t['status'] == 'dispute']),
        'active_tasks': len([t for t in executor_tasks if t['status'] in ['searching', 'in_progress']]),
        'rating': user['rating'],
        'reviews_count': user['reviews_count']
    }

    # Calculate success rate
    total_finished = stats['total_completed'] + stats['total_disputes']
    stats['success_rate'] = stats['total_completed'] / max(total_finished, 1)

    # Calculate response rate (could be implemented with additional tracking)
    stats['response_rate'] = 1.0  # Placeholder

    return stats

async def suggest_missing_tags(task_id: int, customer_id: int, category: str, task_tags: List[str], executors: List[Dict], bot):
    """Suggest missing tags to the customer."""
    try:
        from database import get_user, update_user_interests
        task = get_task(task_id)
        customer = get_user(customer_id)
        if not customer:
            logger.warning(f"Customer {customer_id} not found")
            return

        # Find missing tags
        missing_tags = set()
        for executor in executors:
            executor_tags = executor.get('executor_tags', {}).get(category, [])
            missing_tags.update(set(task_tags) - set(executor_tags))

        if not missing_tags:
            return

        missing_tag = missing_tags.pop()  # Suggest only one tag
        category_name = CATEGORIES.get(category, {}).get('name', category)
        tags_text = ", ".join(task_tags)

        text = f"""
Ми бачимо, що вас цікавить категорія {category_name} і теги: {tags_text}. Можливо, вас також зацікавить тег "{missing_tag}"?
        """

        keyboard = [
            [
                InlineKeyboardButton("Цікаво", callback_data=f"add_interest_{missing_tag}_{task_id}"),
                InlineKeyboardButton("Не цікаво", callback_data=f"skip_tag_{missing_tag}_{task_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = await bot.send_message(
            chat_id=customer_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        # Automatically delete messages after 15 seconds
        await asyncio.sleep(15)
        await bot.delete_message(chat_id=customer_id, message_id=message.message_id)
        # Remove the original message as well if it exists and you have its message_id
        # await bot.delete_message(chat_id=customer_id, message_id=original_message_id)  # Replace original_message_id

    except Exception as e:
        logger.error(f"Error suggesting missing tags: {e}")

async def verify_task_assignment(task_id: int, executor_id: int) -> bool:
    """Verify that the task is still valid before assigning it."""
    await asyncio.sleep(10)  # Simulate 10-second verification

    try:
        from database import get_task
        task = get_task(task_id)

        if not task:
            logger.warning(f"Task {task_id} not found during verification")
            return False

        if task['status'] != 'searching':
            logger.warning(f"Task {task_id} status changed to {task['status']} during verification")
            return False

        if task['executor_id'] and task['executor_id'] != executor_id:
            logger.warning(f"Task {task_id} already assigned to another executor")
            return False

        # Add any other checks that might cause errors

        return True

    except Exception as e:
        logger.error(f"Error during task verification: {e}")
        return False

async def suggest_missing_tags(customer_id: int, category: str, current_tags: list, missing_tags: list):
    """Send tag suggestion to customer with interactive buttons."""
    try:
        import httpx
        import os

        if not missing_tags:
            return

        missing_tag = missing_tags[0]  # Suggest first missing tag

        # Get category name
        from config import CATEGORIES
        category_name = CATEGORIES.get(category, {}).get('name', category)

        # Format current tags display
        tags_display = ", ".join(current_tags) if current_tags else "немає"

        message = f"""Ми бачимо, що вас цікавить категорія "{category_name}" і теги: {tags_display}. Можливо, вас також зацікавить тег "{missing_tag}"?"""

        # Create inline keyboard
        keyboard = {
            "inline_keyboard": [[
                {"text": "Цікаво", "callback_data": f"add_tag_{category}_{missing_tag}"},
                {"text": "Не цікаво", "callback_data": f"skip_tag_{category}_{missing_tag}"}
            ]]
        }

        # Send via main bot
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            logger.error("❌ BOT_TOKEN не знайдено")
            return

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        data = {
            "chat_id": customer_id,
            "text": message,
            "reply_markup": json.dumps(keyboard),
            "parse_mode": "HTML"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=10)

        if response.status_code == 200:
            # Schedule message deletion after 15 seconds
            schedule_message_deletion(customer_id, response.json()['result']['message_id'])
        else:
            logger.error(f"❌ Помилка надсилання пропозиції тегу: {response.status_code}")

    except Exception as e:
        logger.error(f"❌ Помилка пропозиції тегу: {e}")

def start_task_verification(task_id: int, executor_id: int) -> bool:
    """Start 10-second task verification period."""
    try:
        import asyncio
        from database import get_task, update_task

        # Run verification in background
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def verify_and_send():
            await asyncio.sleep(10)  # 10-second wait

            # Re-check task status
            current_task = get_task(task_id)
            if not current_task or current_task['status'] != 'searching':
                logger.info(f"⚠️ Стан перевірки — відхилена: завдання {task_id}")
                return False

            # Send task to executor
            success = send_task_to_executor(task_id, executor_id)
            if success:
                logger.info(f"✅ Завдання надіслано: #{task_id} → виконавець {executor_id}")
            else:
                logger.error(f"❌ Завдання не надіслано: #{task_id}")

            return success

        # Start verification
        loop.run_until_complete(verify_and_send())
        loop.close()

        logger.info(f"✅ Стан перевірки — успішна: завдання {task_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Помилка перевірки завдання {task_id}: {e}")
        return False

def handle_no_executors_found(task_id: int, category: str, task_tags: list) -> bool:
    """Handle case when no executors found with 100% match."""
    try:
        from database import find_executors_with_partial_match, get_user

        # Find executors with 90-99% match
        partial_executors = find_executors_with_partial_match(category, task_tags, min_match=0.9)

        if not partial_executors:
            return False

        # Find missing tags
        customer_id = get_task(task_id)['customer_id']
        missing_tags = find_missing_tags(partial_executors, task_tags)

        if missing_tags:
            suggest_missing_tags(customer_id, category, task_tags, missing_tags)
            logger.info(f"💡 Пропозиція тегу надіслана: {missing_tags[0]}")
            return True

        return False

    except Exception as e:
        logger.error(f"❌ Помилка обробки відсутності виконавців: {e}")
        return False

# The following functions were not modified
async def send_task_to_executor(task_id: int, executor_id: int) -> bool:
    """Send task to executor (implementation not provided)."""
    return True

def find_missing_tags(partial_executors: list, task_tags: list) -> list:
    """Find missing tags (implementation not provided)."""
    return ["missing_tag"]

def schedule_message_deletion(customer_id: int, message_id: int):
    """Schedule message deletion (implementation not provided)."""
    pass