
"""
Dispute handling system for admin bot
"""

import logging
import os
import sys
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Add parent directory to path for database access
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import (get_open_disputes, get_dispute, resolve_dispute, update_task, 
                      update_user_balance, get_task, get_user, init_database, get_db_connection)

logger = logging.getLogger(__name__)

async def show_active_disputes_list(query, context) -> None:
    """Show list of active disputes"""
    try:
        # Ensure database is initialized
        init_database()
        disputes = get_open_disputes()
        
        if not disputes:
            text = "✅ <b>Активних спорів немає</b>\n\nВсі спори вирішено!"
            keyboard = [[InlineKeyboardButton("🔙 Головне меню", callback_data="back_to_main")]]
        else:
            text = f"⚠️ <b>АКТИВНІ СПОРИ ({len(disputes)})</b>\n\n"
            keyboard = []
            
            for dispute in disputes[:10]:  # Show first 10
                text += f"🆔 Спір #{dispute['dispute_id']}\n"
                text += f"📋 Завдання: #{dispute['task_id']}\n"
                text += f"💰 Сума: {dispute['price']:.2f} грн\n"
                text += f"📅 Дата: {dispute['created_at'][:10]}\n\n"
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"📋 Розглянути спір #{dispute['dispute_id']}", 
                        callback_data=f"view_dispute_{dispute['dispute_id']}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔄 Оновити", callback_data="active_disputes")])
            keyboard.append([InlineKeyboardButton("🔙 Головне меню", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error showing disputes list: {e}")
        await query.answer("❌ Помилка завантаження спорів")

async def show_dispute_details(query, dispute_id: int, context) -> None:
    """Show detailed dispute information"""
    try:
        dispute = get_dispute(dispute_id)
        
        if not dispute:
            await query.edit_message_text("❌ Спір не знайдено")
            return
        
        customer_name = dispute.get('customer_username') or f"ID:{dispute['customer_id']}"
        executor_name = dispute.get('executor_username') or f"ID:{dispute['executor_id']}"
        
        text = f"""
⚠️ <b>ДЕТАЛІ СПОРУ #{dispute_id}</b>

📋 <b>Завдання:</b> #{dispute['task_id']}
💰 <b>Сума:</b> {dispute['price']:.2f} грн
📅 <b>Дата створення:</b> {dispute['created_at'][:16]}
📂 <b>Категорія:</b> {dispute['category']}

👥 <b>Учасники спору:</b>
🛒 <b>Замовник:</b> {customer_name}
⚡ <b>Виконавець:</b> {executor_name}

💬 <b>Причина спору:</b>
{dispute['reason']}

📝 <b>Опис завдання:</b>
{dispute['description'][:300]}{'...' if len(dispute['description']) > 300 else ''}

🔧 <b>Рішення адміністратора:</b>
        """
        
        keyboard = [
            [
                InlineKeyboardButton("✅ На користь замовника", callback_data=f"resolve_dispute_{dispute_id}_customer"),
                InlineKeyboardButton("🔧 На користь виконавця", callback_data=f"resolve_dispute_{dispute_id}_executor")
            ],
            [
                InlineKeyboardButton("📄 Історія чату", callback_data=f"view_chat_history_{dispute['task_id']}")
            ],
            [
                InlineKeyboardButton("👤 Інфо замовника", callback_data=f"user_info_{dispute['customer_id']}"),
                InlineKeyboardButton("🔧 Інфо виконавця", callback_data=f"user_info_{dispute['executor_id']}")
            ],
            [
                InlineKeyboardButton("🔙 До списку спорів", callback_data="active_disputes")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error showing dispute details: {e}")
        await query.answer("❌ Помилка завантаження деталей спору")

async def resolve_dispute_handler(query, dispute_id: int, resolution: str, context) -> None:
    """Handle dispute resolution"""
    try:
        admin_id = query.from_user.id
        
        # Get dispute details
        dispute = get_dispute(dispute_id)
        if not dispute:
            await query.answer("❌ Спір не знайдено")
            return
        
        task = get_task(dispute['task_id'])
        if not task:
            await query.answer("❌ Завдання не знайдено")
            return
        
        # Resolve dispute in database
        admin_decision = f"Рішення адміністратора: на користь {'замовника' if resolution == 'customer' else 'виконавця'}"
        success = resolve_dispute(dispute_id, resolution, admin_id, admin_decision)
        
        if not success:
            await query.answer("❌ Помилка вирішення спору")
            return
        
        # Handle money transfers
        if resolution == "customer":
            # Return money to customer: unfreeze and add to balance
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET frozen_balance = frozen_balance - ?, balance = balance + ?
                WHERE user_id = ?
            """, (task['price'], task['price'], dispute['customer_id']))
            conn.commit()
            conn.close()
            update_task(dispute['task_id'], status='cancelled')
            
            result_text = f"""
✅ <b>СПІР ВИРІШЕНО НА КОРИСТЬ ЗАМОВНИКА</b>

🆔 Спір #{dispute_id}
📋 Завдання #{dispute['task_id']}
💰 Повернено замовнику: {task['price']:.2f} грн

📝 Завдання скасовано.
            """
            
        elif resolution == "executor":
            # Pay executor
            executor_payment = task['price'] * 0.9  # 10% commission
            conn = get_db_connection()
            cursor = conn.cursor()
            # Unfreeze customer money and pay executor
            cursor.execute("""
                UPDATE users SET frozen_balance = frozen_balance - ?
                WHERE user_id = ?
            """, (task['price'], dispute['customer_id']))
            cursor.execute("""
                UPDATE users SET balance = balance + ?, earned_balance = earned_balance + ?
                WHERE user_id = ?
            """, (executor_payment, executor_payment, dispute['executor_id']))
            conn.commit()
            conn.close()
            update_task(dispute['task_id'], status='completed')
            
            result_text = f"""
✅ <b>СПІР ВИРІШЕНО НА КОРИСТЬ ВИКОНАВЦЯ</b>

🆔 Спір #{dispute_id}
📋 Завдання #{dispute['task_id']}
💰 Виплачено виконавцю: {executor_payment:.2f} грн
💳 Комісія платформи: {task['price'] * 0.1:.2f} грн

📝 Завдання завершено.
            """
        
        # Notify participants
        try:
            # Notify customer
            customer_message = f"""
{'✅' if resolution == 'customer' else '❌'} <b>СПІР ВИРІШЕНО</b>

🆔 Спір #{dispute_id}
📋 Завдання #{dispute['task_id']}

{'🎉 Рішення на вашу користь!' if resolution == 'customer' else '😔 Рішення на користь виконавця'}

{f'💰 Повернено: {task["price"]:.2f} грн' if resolution == 'customer' else '💰 Кошти передано виконавцю'}

📞 Підтримка: @Admin_fartobot
            """
            
            await context.bot.send_message(
                chat_id=dispute['customer_id'],
                text=customer_message,
                parse_mode='HTML'
            )
            
            # Notify executor
            executor_message = f"""
{'❌' if resolution == 'customer' else '✅'} <b>СПІР ВИРІШЕНО</b>

🆔 Спір #{dispute_id}
📋 Завдання #{dispute['task_id']}

{'😔 Рішення на користь замовника' if resolution == 'customer' else '🎉 Рішення на вашу користь!'}

{f'💰 Отримано: {task["price"] * 0.9:.2f} грн' if resolution == 'executor' else '💰 Кошти повернено замовнику'}

📞 Підтримка: @Admin_fartobot
            """
            
            await context.bot.send_message(
                chat_id=dispute['executor_id'],
                text=executor_message,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Error notifying participants: {e}")
        
        # Show result to admin
        keyboard = [
            [InlineKeyboardButton("⚠️ Інші спори", callback_data="active_disputes")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode='HTML')
        
        logger.info(f"Dispute {dispute_id} resolved in favor of {resolution} by admin {admin_id}")
        
    except Exception as e:
        logger.error(f"Error resolving dispute: {e}")
        await query.answer("❌ Помилка вирішення спору")

# Export dispute handlers
dispute_handlers = {
    'show_active_disputes_list': show_active_disputes_list,
    'show_dispute_details': show_dispute_details,
    'resolve_dispute_handler': resolve_dispute_handler,
}
