"""
Task timer system for automatic task acceptance timeout
"""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
from database import get_task, update_task
from utils.taxi_system import find_and_notify_executor

logger = logging.getLogger(__name__)

# Active task timers
active_timers: Dict[int, asyncio.Task] = {}

class TaskTimer:
    """Manages task acceptance timeouts"""

    ACCEPTANCE_TIMEOUT_MINUTES = 10

    @classmethod
    async def start_acceptance_timer(cls, task_id: int, executor_id: int, bot) -> None:
        """Start 10-minute timer for task acceptance"""
        if task_id in active_timers:
            # Cancel existing timer
            active_timers[task_id].cancel()

        # Create new timer
        timer_task = asyncio.create_task(
            cls._acceptance_timeout_handler(task_id, executor_id, bot)
        )
        active_timers[task_id] = timer_task

        logger.info(f"Started {cls.ACCEPTANCE_TIMEOUT_MINUTES}-minute timer for task {task_id}, executor {executor_id}")

    @classmethod
    async def cancel_timer(cls, task_id: int) -> None:
        """Cancel timer when task is accepted or completed"""
        if task_id in active_timers:
            active_timers[task_id].cancel()
            del active_timers[task_id]
            logger.info(f"Cancelled timer for task {task_id}")

    @classmethod
    async def _acceptance_timeout_handler(cls, task_id: int, executor_id: int, bot) -> None:
        """Handle task acceptance timeout"""
        try:
            # Wait for timeout period
            await asyncio.sleep(cls.ACCEPTANCE_TIMEOUT_MINUTES * 60)

            # Check if task is still pending with this executor
            task = get_task(task_id)
            if not task or task['status'] != 'offered' or task['executor_id'] != executor_id:
                logger.info(f"Task {task_id} status changed, timer no longer needed")
                return

            logger.info(f"Task {task_id} acceptance timeout for executor {executor_id}")

            # Track missed task and update offer status - only for timeout, not manual decline
            from database import increment_missed_tasks, set_work_status, update_task_offer_status
            update_task_offer_status(task_id, executor_id, 'expired')
            missed_count = increment_missed_tasks(executor_id)

            # Prepare timeout message with warning if needed
            timeout_message = "⏰ <b>Час на прийняття завдання вичерпано</b>\n\nЗавдання буде запропоновано іншому виконавцю."

            if missed_count >= 2:
                if missed_count == 2:
                    timeout_message += "\n\n⚠️ <b>Попередження!</b>\nПісля ще одного пропуску ваш статус буде змінено на \"Не працюю\"."
                elif missed_count >= 3:
                    set_work_status(executor_id, False)
                    timeout_message += "\n\n❌ <b>Ваш статус змінено на \"Не працюю\"</b>\nЧерез пропуск 3 завдань. Увімкніть статус в профілі для отримання нових завдань."

            # Notify executor about timeout with appropriate warning
            try:
                await bot.send_message(
                    chat_id=executor_id,
                    text=timeout_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f"Failed to notify executor {executor_id} about timeout: {e}")

            # Reset task status to searching
            update_task(task_id, status='searching', executor_id=None)

            # Find next executor
            await find_and_notify_executor(task_id, bot, exclude_executor=executor_id)

            # Remove from active timers
            if task_id in active_timers:
                del active_timers[task_id]

        except asyncio.CancelledError:
            logger.info(f"Timer for task {task_id} was cancelled")
        except Exception as e:
            logger.error(f"Error in acceptance timeout handler for task {task_id}: {e}")

class TaskNotifications:
    """Handle push notifications for important events"""

    @staticmethod
    async def notify_task_accepted(customer_id: int, executor_id: int, task_id: int, bot) -> None:
        """Notify customer that task was accepted"""
        try:
            task = get_task(task_id)
            if not task:
                return

            await bot.send_message(
                chat_id=customer_id,
                text=f"✅ <b>Ваше завдання прийнято!</b>\n\n"
                     f"<b>Завдання:</b> {task['description'][:100]}...\n"
                     f"<b>Ціна:</b> {task['price']} грн\n\n"
                     f"Виконавець зв'яжеться з вами через анонімний чат.",
                parse_mode='HTML'
            )
            logger.info(f"Notified customer {customer_id} about task {task_id} acceptance")
        except Exception as e:
            logger.error(f"Failed to notify customer about task acceptance: {e}")

    @staticmethod
    async def notify_task_completed(customer_id: int, task_id: int, bot) -> None:
        """Notify customer that task is completed"""
        try:
            task = get_task(task_id)
            if not task:
                return

            await bot.send_message(
                chat_id=customer_id,
                text=f"🎯 <b>Завдання завершено виконавцем!</b>\n\n"
                     f"<b>Завдання:</b> {task['description'][:100]}...\n\n"
                     f"Перевірте результат та підтвердьте виконання або відкрийте спір через анонімний чат.",
                parse_mode='HTML'
            )
            logger.info(f"Notified customer {customer_id} about task {task_id} completion")
        except Exception as e:
            logger.error(f"Failed to notify customer about task completion: {e}")

    @staticmethod
    async def notify_dispute_opened(admin_chat_id: int, task_id: int, customer_id: int, executor_id: int, bot) -> None:
        """Notify admins about dispute"""
        try:
            task = get_task(task_id)
            if not task:
                return

            await bot.send_message(
                chat_id=admin_chat_id,
                text=f"⚠️ <b>НОВИЙ СПІР</b>\n\n"
                     f"<b>Завдання ID:</b> {task_id}\n"
                     f"<b>Замовник ID:</b> {customer_id}\n"
                     f"<b>Виконавець ID:</b> {executor_id}\n"
                     f"<b>Ціна:</b> {task['price']} грн\n\n"
                     f"<b>Опис:</b> {task['description'][:200]}...\n\n"
                     f"Потребує втручання адміністратора.",
                parse_mode='HTML'
            )
            logger.info(f"Notified admin about dispute for task {task_id}")
        except Exception as e:
            logger.error(f"Failed to notify admin about dispute: {e}")

def get_active_timers_count() -> int:
    """Get count of active timers"""
    return len(active_timers)

def get_active_timers_info() -> Dict[int, str]:
    """Get info about active timers"""
    return {task_id: "running" for task_id in active_timers.keys()}