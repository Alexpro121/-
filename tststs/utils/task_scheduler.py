"""
Task Scheduler for automatic task processing
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime, timedelta

from database import get_tasks_waiting_for_executors

logger = logging.getLogger(__name__)

class TaskScheduler:
    def __init__(self):
        self.is_running = False
        self.task = None
        self._loop = None

    async def start(self, bot) -> bool:
        """Start the task scheduler."""
        if self.is_running:
            logger.warning("Task scheduler is already running")
            return False

        try:
            # Ensure we have a valid bot instance
            if not bot:
                logger.error("Bot instance is None")
                return False

            # Use the current running event loop
            self._loop = asyncio.get_running_loop()
            self.is_running = True
            self.task = asyncio.create_task(self._scheduler_loop(bot))
            logger.info("✅ Task scheduler started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start task scheduler: {e}")
            self.is_running = False
            return False

    async def stop(self):
        """Stop the task scheduler."""
        if not self.is_running:
            return

        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Task scheduler stopped")

    async def _scheduler_loop(self, bot):
        """Main scheduler loop."""
        while self.is_running:
            try:
                await self._process_waiting_tasks(bot)
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(5)  # Wait a bit before retrying

    async def _process_waiting_tasks(self, bot):
        """Process tasks waiting for executors."""
        try:
            # First, clean up expired offers
            from database import cleanup_expired_offers
            expired_count = cleanup_expired_offers()
            if expired_count > 0:
                logger.info(f"🧹 Cleaned up {expired_count} expired task offers")

            waiting_tasks = get_tasks_waiting_for_executors()

            if not waiting_tasks:
                return

            logger.info(f"📋 Обробляю {len(waiting_tasks)} завдань у пошуку")

            success_count = 0
            for task_data in waiting_tasks:
                try:
                    from utils.taxi_system import find_and_notify_executor
                    success = await find_and_notify_executor(task_data['task_id'], bot)

                    if success:
                        success_count += 1

                    # Small delay between tasks
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(f"❌ Помилка обробки завдання {task_data['task_id']}: {e}")

            if success_count > 0:
                logger.info(f"✅ Успішно оброблено {success_count}/{len(waiting_tasks)} завдань")

        except Exception as e:
            logger.error(f"Error getting waiting tasks: {e}")

    def start_in_background(self, bot):
        """Start scheduler in background (for non-async contexts)."""
        if self.is_running:
            return

        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is already running, schedule the coroutine
                asyncio.create_task(self.start(bot))
            else:
                # If no loop is running, run it
                loop.run_until_complete(self.start(bot))
        except RuntimeError:
            # No event loop exists, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.start(bot))

# Global scheduler instance
scheduler = TaskScheduler()

def add_task_to_scheduler(task_id: int, bot) -> bool:
    """Add a task to the scheduler for processing"""
    try:
        # This is a simplified version - in practice, the scheduler processes
        # tasks automatically, so we'll just trigger the taxi system directly
        from utils.taxi_system import find_and_notify_executor

        # Schedule the task processing
        if asyncio.get_event_loop().is_running():
            asyncio.create_task(find_and_notify_executor(task_id, bot))
        else:
            # If no event loop is running, try to create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(find_and_notify_executor(task_id, bot))

        logger.info(f"✅ Added task {task_id} to scheduler")
        return True

    except Exception as e:
        logger.error(f"Failed to add task {task_id} to scheduler: {e}")
        return False

def start_task_scheduler():
    """Start the task scheduler."""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(task_scheduler())
        logger.info("Task scheduler started successfully")
    except RuntimeError as e:
        if "no running event loop" in str(e):
            logger.error("Failed to start task scheduler: no running event loop")
            # Try to start in a new thread
            import threading
            def run_scheduler():
                asyncio.run(task_scheduler())
            thread = threading.Thread(target=run_scheduler, daemon=True)
            thread.start()
            logger.info("Task scheduler started in background thread")
        else:
            logger.error(f"Failed to start task scheduler: {e}")
    except Exception as e:
        logger.error(f"Failed to start task scheduler: {e}")

def manual_search_executors():
    """Manual search for executors - for admin interface."""
    try:
        from utils.taxi_system import find_and_notify_executor
        from database import get_tasks_waiting_for_executors
        import json

        waiting_tasks = get_tasks_waiting_for_executors()
        results = []

        for task in waiting_tasks:
            try:
                task_tags = json.loads(task['tags'])
                found = find_and_notify_executor(
                    task['task_id'], 
                    task['customer_id'], 
                    task['category'], 
                    task_tags, 
                    task['price']
                )
                results.append({
                    'task_id': task['task_id'],
                    'found': found,
                    'status': 'success'
                })
            except Exception as e:
                results.append({
                    'task_id': task['task_id'],
                    'found': False,
                    'status': 'error',
                    'error': str(e)
                })

        return results
    except Exception as e:
        logger.error(f"Error in manual search: {e}")
        return []

def get_scheduler_status():
    """Get current scheduler status."""
    return {
        'active': True,
        'waiting_tasks_count': len(get_tasks_waiting_for_executors()) if 'get_tasks_waiting_for_executors' in globals() else 0,
        'last_run': datetime.now().isoformat()
    }