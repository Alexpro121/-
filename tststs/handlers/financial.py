"""
Financial operations handlers for Rozdum Bot
Handles balance top-ups, withdrawals, transaction history
"""

import logging
from typing import Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import get_db_connection, get_user, update_user_balance
from utils.financial_system import (
    PaymentMethods, process_automatic_deposit, process_withdrawal,
    get_user_transactions, get_transaction_stats, format_transaction_history
)
from utils.helpers import format_currency, MessageBuilder
from config import UserStates

logger = logging.getLogger(__name__)

async def show_balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show balance management menu"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Користувач не знайдений")
        return
    
    # Get transaction stats
    stats = get_transaction_stats(user_id)
    
    earned_balance = user.get('earned_balance', 0.0)
    deposited_balance = user['balance'] - earned_balance
    
    text = f"""
💰 <b>Фінансовий центр</b>

💳 <b>Загальний баланс:</b> {format_currency(user['balance'])}
💰 <b>Заробленого:</b> {format_currency(earned_balance)}
💸 <b>Внесено:</b> {format_currency(deposited_balance)}
🔒 <b>Заморожено:</b> {format_currency(user['frozen_balance'])}

ℹ️ <i>До виведення доступно лише заробленого: {format_currency(earned_balance)}</i>

📊 <b>Статистика:</b>
• Всього поповнено: {format_currency(stats.get('total_deposits', 0))}
• Всього виведено: {format_currency(stats.get('total_withdrawals', 0))}
• Всього заробив: {format_currency(stats.get('total_earnings', 0))}
• Всього витрачено: {format_currency(stats.get('total_spent', 0))}
    """
    
    keyboard = [
        [
            InlineKeyboardButton("💳 Поповнити", callback_data="add_balance"),
            InlineKeyboardButton("💸 Вивести", callback_data="withdraw_balance")
        ],
        [
            InlineKeyboardButton("📊 Історія операцій", callback_data="transaction_history")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="profile")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_deposit_methods(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available deposit methods"""
    query = update.callback_query
    
    text = """
💳 <b>Поповнення балансу</b>

Оберіть зручний спосіб поповнення:

• 💳 <b>Банківська картка</b> - миттєво, комісія 2%
• 🏦 <b>Банківський переказ</b> - до 2 годин, без комісії
• ₿ <b>Криптовалюта</b> - до 30 хвилин, комісія 1%
• 🌐 <b>PayPal</b> - миттєво, комісія 3%

Мінімальна сума поповнення: 50 грн
    """
    
    keyboard = [
        [
            InlineKeyboardButton("💳 Картка", callback_data=f"deposit_{PaymentMethods.CARD}"),
            InlineKeyboardButton("🏦 Переказ", callback_data=f"deposit_{PaymentMethods.BANK_TRANSFER}")
        ],
        [
            InlineKeyboardButton("₿ Криптовалюта", callback_data=f"deposit_{PaymentMethods.CRYPTO}"),
            InlineKeyboardButton("🌐 PayPal", callback_data=f"deposit_{PaymentMethods.PAYPAL}")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="balance_menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_deposit_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle deposit method selection"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    method = query.data.split('_')[1]
    method_names = {
        PaymentMethods.CARD: "банківської картки",
        PaymentMethods.BANK_TRANSFER: "банківського переказу", 
        PaymentMethods.CRYPTO: "криптовалюти",
        PaymentMethods.PAYPAL: "PayPal"
    }
    
    text = f"""
💳 <b>Поповнення через {method_names.get(method, method)}</b>

Введіть суму для поповнення (мінімум 50 грн):
    """
    
    # Store selected method in context
    context.user_data['deposit_method'] = method
    context.user_data['user_state'] = UserStates.ADDING_BALANCE
    
    await query.edit_message_text(text, parse_mode='HTML')

async def process_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process deposit amount input"""
    user_id = update.effective_user.id
    amount_text = update.message.text
    
    try:
        amount = float(amount_text.replace(',', '.'))
        
        if amount < 50:
            await update.message.reply_text("❌ Мінімальна сума поповнення: 50 грн")
            return
        
        if amount > 50000:
            await update.message.reply_text("❌ Максимальна сума поповнення: 50,000 грн")
            return
        
        method = context.user_data.get('deposit_method', PaymentMethods.CARD)
        
        # Start deposit processing
        await update.message.reply_text(
            f"🔄 Обробка платежу {format_currency(amount)}...\n\n"
            f"Це може зайняти кілька хвилин."
        )
        
        # Simulate payment data (in real system would collect from user)
        payment_data = {
            'amount': amount,
            'currency': 'UAH',
            'method': method
        }
        
        # Process automatic deposit
        success = await process_automatic_deposit(user_id, amount, method, payment_data, context.bot)
        
        if success:
            await update.message.reply_text(
                f"✅ Баланс успішно поповнено на {format_currency(amount)}!"
            )
        else:
            await update.message.reply_text(
                f"❌ Помилка обробки платежу. Спробуйте пізніше або зверніться до підтримки."
            )
        
        # Clear state
        context.user_data['user_state'] = UserStates.NONE
        context.user_data.pop('deposit_method', None)
        
    except ValueError:
        await update.message.reply_text("❌ Некоректна сума. Введіть число (наприклад: 100 або 100.50)")

async def show_withdrawal_methods(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show withdrawal methods"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    user = get_user(user_id)
    earned_balance = user.get('earned_balance', 0.0) if user else 0.0
    
    if not user or earned_balance < 100:
        await query.edit_message_text(
            f"❌ Недостатньо заробленого для виведення.\n\n"
            f"Заробленого: {format_currency(earned_balance)}\n"
            f"Мінімальна сума: 100 грн\n\n"
            f"ℹ️ Можна виводити лише зароблені кошти від виконання завдань.",
            parse_mode='HTML'
        )
        return
    
    text = f"""
💸 <b>Виведення коштів</b>

💰 <b>Заробленого (доступно):</b> {format_currency(earned_balance)}
💳 <b>Загальний баланс:</b> {format_currency(user['balance'])}

ℹ️ <i>До виведення доступно лише зароблено від завдань</i>

Оберіть спосіб виведення:

• 💳 <b>На картку</b> - до 24 годин, комісія 15 грн
• 🏦 <b>Банківський переказ</b> - до 3 днів, комісія 10 грн
• ₿ <b>Криптовалюта</b> - до 2 годин, комісія 2%

Мінімальна сума виведення: 100 грн
    """
    
    keyboard = [
        [
            InlineKeyboardButton("💳 На картку", callback_data=f"withdraw_{PaymentMethods.CARD}"),
            InlineKeyboardButton("🏦 Переказ", callback_data=f"withdraw_{PaymentMethods.BANK_TRANSFER}")
        ],
        [
            InlineKeyboardButton("₿ Криптовалюта", callback_data=f"withdraw_{PaymentMethods.CRYPTO}")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="balance_menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_withdrawal_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle withdrawal method selection"""
    query = update.callback_query
    
    method = query.data.split('_')[1]
    method_names = {
        PaymentMethods.CARD: "картку",
        PaymentMethods.BANK_TRANSFER: "банківський переказ",
        PaymentMethods.CRYPTO: "криптогаманець"
    }
    
    text = f"""
💸 <b>Виведення на {method_names.get(method, method)}</b>

Введіть суму для виведення (мінімум 100 грн):
    """
    
    # Store selected method in context
    context.user_data['withdrawal_method'] = method
    context.user_data['user_state'] = UserStates.WITHDRAWING_BALANCE
    
    await query.edit_message_text(text, parse_mode='HTML')

async def process_withdrawal_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process withdrawal amount input"""
    user_id = update.effective_user.id
    amount_text = update.message.text
    
    try:
        amount = float(amount_text.replace(',', '.'))
        
        user = get_user(user_id)
        if not user:
            await update.message.reply_text("❌ Помилка отримання даних користувача")
            return
        
        earned_balance = user.get('earned_balance', 0.0)
        
        if amount < 100:
            await update.message.reply_text("❌ Мінімальна сума виведення: 100 грн")
            return
        
        if amount > earned_balance:
            await update.message.reply_text(
                f"❌ Недостатньо зароблених коштів. Доступно: {format_currency(earned_balance)}\n\n"
                f"ℹ️ Можна виводити лише зароблені кошти від виконання завдань."
            )
            return
        
        method = context.user_data.get('withdrawal_method', PaymentMethods.CARD)
        
        # Start withdrawal processing
        await update.message.reply_text(
            f"🔄 Обробка виведення {format_currency(amount)}...\n\n"
            f"Кошти будуть надіслані протягом зазначеного терміну."
        )
        
        # Simulate withdrawal data (in real system would collect details)
        withdrawal_data = {
            'amount': amount,
            'currency': 'UAH',
            'method': method
        }
        
        # Process withdrawal
        success = await process_withdrawal(user_id, amount, method, withdrawal_data, context.bot)
        
        if not success:
            await update.message.reply_text(
                f"❌ Помилка обробки виведення. Спробуйте пізніше."
            )
        
        # Clear state
        context.user_data['user_state'] = UserStates.NONE
        context.user_data.pop('withdrawal_method', None)
        
    except ValueError:
        await update.message.reply_text("❌ Некоректна сума. Введіть число (наприклад: 100 або 100.50)")

async def show_transaction_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user transaction history"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    transactions = get_user_transactions(user_id, limit=20)
    history_text = format_transaction_history(transactions)
    
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="balance_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(history_text, reply_markup=reply_markup, parse_mode='HTML')

# Callback handlers mapping
FINANCIAL_CALLBACKS = {
    'balance_menu': show_balance_menu,
    'add_balance': show_deposit_methods,
    'withdraw_balance': show_withdrawal_methods,
    'transaction_history': show_transaction_history
}

def register_financial_callback(callback_data: str, query, context):
    """Register financial callback handler"""
    if callback_data in FINANCIAL_CALLBACKS:
        return FINANCIAL_CALLBACKS[callback_data]
    elif callback_data.startswith('deposit_'):
        return handle_deposit_method
    elif callback_data.startswith('withdraw_'):
        return handle_withdrawal_method
    return None