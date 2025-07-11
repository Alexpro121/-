"""
Financial operations system for Rozdum Bot
Handles payments, withdrawals, refunds and transaction history
"""

import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from database import get_db_connection, get_user, update_user_balance, get_task

logger = logging.getLogger(__name__)

class PaymentMethods:
    """Available payment methods"""
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    CRYPTO = "crypto"
    PAYPAL = "paypal"

class TransactionTypes:
    """Transaction types"""
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    PAYMENT = "payment"
    REFUND = "refund"
    COMMISSION = "commission"
    ESCROW_FREEZE = "escrow_freeze"
    ESCROW_RELEASE = "escrow_release"

class TransactionStatus:
    """Transaction statuses"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

def create_transaction(user_id: int, amount: float, transaction_type: str, 
                      status: str = TransactionStatus.PENDING, 
                      description: str = None, task_id: int = None,
                      payment_method: str = None) -> Optional[int]:
    """Create new transaction record"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO transactions 
            (user_id, amount, type, status, description, task_id, payment_method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, amount, transaction_type, status, description, task_id, 
              payment_method, datetime.now().isoformat()))
        
        transaction_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Created transaction {transaction_id} for user {user_id}: {amount} ({transaction_type})")
        return transaction_id
        
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return None

def get_user_transactions(user_id: int, limit: int = 50) -> List[Dict]:
    """Get user transaction history"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM transactions 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (user_id, limit))
        
        transactions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return transactions
        
    except Exception as e:
        logger.error(f"Failed to get transactions for user {user_id}: {e}")
        return []

def get_transaction_stats(user_id: int) -> Dict:
    """Get user transaction statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Total deposits
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = ? AND type = ? AND status = ?
        """, (user_id, TransactionTypes.DEPOSIT, TransactionStatus.COMPLETED))
        total_deposits = cursor.fetchone()[0]
        
        # Total withdrawals
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = ? AND type = ? AND status = ?
        """, (user_id, TransactionTypes.WITHDRAWAL, TransactionStatus.COMPLETED))
        total_withdrawals = cursor.fetchone()[0]
        
        # Total earnings (payments received)
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = ? AND type = ? AND status = ?
        """, (user_id, TransactionTypes.PAYMENT, TransactionStatus.COMPLETED))
        total_earnings = cursor.fetchone()[0]
        
        # Total spent (payments made)
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions 
            WHERE user_id = ? AND type = ? AND status = ?
        """, (user_id, TransactionTypes.PAYMENT, TransactionStatus.COMPLETED))
        total_spent = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_deposits': total_deposits,
            'total_withdrawals': total_withdrawals,
            'total_earnings': total_earnings,
            'total_spent': total_spent,
            'net_balance': total_deposits + total_earnings - total_withdrawals - total_spent
        }
        
    except Exception as e:
        logger.error(f"Failed to get transaction stats for user {user_id}: {e}")
        return {}

async def process_automatic_deposit(user_id: int, amount: float, payment_method: str, 
                                   payment_data: Dict, bot) -> bool:
    """Process automatic balance top-up"""
    try:
        # Create pending transaction
        transaction_id = create_transaction(
            user_id, amount, TransactionTypes.DEPOSIT, 
            TransactionStatus.PENDING, 
            f"Поповнення балансу через {payment_method}",
            payment_method=payment_method
        )
        
        if not transaction_id:
            return False
        
        # Simulate payment processing (in real system would integrate with payment gateway)
        await asyncio.sleep(2)  # Simulate processing delay
        
        # In real system, here would be actual payment gateway integration
        payment_success = await simulate_payment_processing(payment_method, amount, payment_data)
        
        if payment_success:
            # Update user balance
            success = update_user_balance(user_id, amount, 0)
            
            if success:
                # Update transaction status
                update_transaction_status(transaction_id, TransactionStatus.COMPLETED)
                
                # Notify user
                user = get_user(user_id)
                await bot.send_message(
                    chat_id=user_id,
                    text=f"✅ <b>Баланс поповнено!</b>\n\n"
                         f"💰 Сума: {amount:.2f} грн\n"
                         f"💳 Спосіб: {get_payment_method_name(payment_method)}\n"
                         f"📊 Новий баланс: {user['balance'] + amount:.2f} грн",
                    parse_mode='HTML'
                )
                
                logger.info(f"Successful deposit: {amount} for user {user_id}")
                return True
            else:
                update_transaction_status(transaction_id, TransactionStatus.FAILED)
        else:
            update_transaction_status(transaction_id, TransactionStatus.FAILED)
            
            # Notify user about failure
            await bot.send_message(
                chat_id=user_id,
                text=f"❌ <b>Помилка поповнення</b>\n\n"
                     f"Не вдалося обробити платіж. Спробуйте пізніше або оберіть інший спосіб оплати.",
                parse_mode='HTML'
            )
        
        return False
        
    except Exception as e:
        logger.error(f"Error processing automatic deposit: {e}")
        return False

async def process_withdrawal(user_id: int, amount: float, withdrawal_method: str,
                           withdrawal_data: Dict, bot) -> bool:
    """Process balance withdrawal (only earned money)"""
    try:
        user = get_user(user_id)
        earned_balance = user.get('earned_balance', 0.0) if user else 0.0
        
        if not user or earned_balance < amount:
            await bot.send_message(
                chat_id=user_id,
                text=f"❌ Недостатньо зароблених коштів для виведення\n\n"
                     f"Заробленого: {earned_balance:.2f} грн\n"
                     f"ℹ️ Можна виводити лише зароблені кошти від завдань",
                parse_mode='HTML'
            )
            return False
        
        # Create pending transaction
        transaction_id = create_transaction(
            user_id, -amount, TransactionTypes.WITHDRAWAL,
            TransactionStatus.PENDING,
            f"Виведення зароблених коштів через {withdrawal_method}",
            payment_method=withdrawal_method
        )
        
        if not transaction_id:
            return False
        
        # Deduct from both general balance and earned balance
        success = update_user_balance(user_id, -amount, 0)
        if success:
            # Also reduce earned balance
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET earned_balance = earned_balance - ? WHERE user_id = ?
            """, (amount, user_id))
            conn.commit()
            conn.close()
        
        if not success:
            update_transaction_status(transaction_id, TransactionStatus.FAILED)
            return False
        
        # Simulate withdrawal processing
        await asyncio.sleep(3)
        withdrawal_success = await simulate_withdrawal_processing(withdrawal_method, amount, withdrawal_data)
        
        if withdrawal_success:
            update_transaction_status(transaction_id, TransactionStatus.COMPLETED)
            
            await bot.send_message(
                chat_id=user_id,
                text=f"✅ <b>Кошти виведено!</b>\n\n"
                     f"💰 Сума: {amount:.2f} грн\n"
                     f"💳 Спосіб: {get_payment_method_name(withdrawal_method)}\n"
                     f"⏰ Час обробки: до 24 годин",
                parse_mode='HTML'
            )
            
            logger.info(f"Successful withdrawal: {amount} for user {user_id}")
            return True
        else:
            # Return funds on failure (both general and earned balance)
            update_user_balance(user_id, amount, 0)
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET earned_balance = earned_balance + ? WHERE user_id = ?
            """, (amount, user_id))
            conn.commit()
            conn.close()
            
            update_transaction_status(transaction_id, TransactionStatus.FAILED)
            
            await bot.send_message(
                chat_id=user_id,
                text=f"❌ <b>Помилка виведення</b>\n\n"
                     f"Кошти повернено на баланс. Спробуйте пізніше.",
                parse_mode='HTML'
            )
        
        return False
        
    except Exception as e:
        logger.error(f"Error processing withdrawal: {e}")
        return False

async def process_task_refund(task_id: int, reason: str, bot) -> bool:
    """Process automatic refund when task is cancelled"""
    try:
        task = get_task(task_id)
        if not task or task['status'] not in ['cancelled', 'disputed']:
            return False
        
        customer_id = task['customer_id']
        refund_amount = task['price']
        
        # Create refund transaction
        transaction_id = create_transaction(
            customer_id, refund_amount, TransactionTypes.REFUND,
            TransactionStatus.COMPLETED,
            f"Повернення коштів за завдання #{task_id}: {reason}",
            task_id=task_id
        )
        
        # Return funds to customer
        success = update_user_balance(customer_id, refund_amount, -refund_amount)
        
        if success:
            await bot.send_message(
                chat_id=customer_id,
                text=f"💰 <b>Кошти повернено</b>\n\n"
                     f"Завдання #{task_id}\n"
                     f"Сума: {refund_amount:.2f} грн\n"
                     f"Причина: {reason}",
                parse_mode='HTML'
            )
            
            logger.info(f"Processed refund for task {task_id}: {refund_amount}")
            return True
        else:
            update_transaction_status(transaction_id, TransactionStatus.FAILED)
        
        return False
        
    except Exception as e:
        logger.error(f"Error processing refund for task {task_id}: {e}")
        return False

def update_transaction_status(transaction_id: int, status: str) -> bool:
    """Update transaction status"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE transactions 
            SET status = ?, updated_at = ?
            WHERE id = ?
        """, (status, datetime.now().isoformat(), transaction_id))
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to update transaction status: {e}")
        return False

async def simulate_payment_processing(payment_method: str, amount: float, payment_data: Dict) -> bool:
    """Simulate payment gateway processing (replace with real integration)"""
    # In real system, integrate with Stripe, PayPal, etc.
    await asyncio.sleep(1)
    return True  # Always succeed for demo

async def simulate_withdrawal_processing(withdrawal_method: str, amount: float, withdrawal_data: Dict) -> bool:
    """Simulate withdrawal processing (replace with real integration)"""
    # In real system, integrate with banking APIs
    await asyncio.sleep(2)
    return True  # Always succeed for demo

def get_payment_method_name(method: str) -> str:
    """Get localized payment method name"""
    names = {
        PaymentMethods.CARD: "Банківська картка",
        PaymentMethods.BANK_TRANSFER: "Банківський переказ",
        PaymentMethods.CRYPTO: "Криптовалюта",
        PaymentMethods.PAYPAL: "PayPal"
    }
    return names.get(method, method)

def format_transaction_history(transactions: List[Dict]) -> str:
    """Format transaction history for display"""
    if not transactions:
        return "📝 Історія операцій порожня"
    
    lines = ["📊 <b>Історія операцій</b>\n"]
    
    for tx in transactions[:10]:  # Show last 10
        amount = tx['amount']
        tx_type = tx['type']
        status = tx['status']
        created_at = tx['created_at']
        
        # Format amount with sign
        if tx_type in [TransactionTypes.DEPOSIT, TransactionTypes.PAYMENT, TransactionTypes.REFUND]:
            amount_str = f"+{amount:.2f} грн"
            emoji = "💰"
        else:
            amount_str = f"-{abs(amount):.2f} грн"
            emoji = "💸"
        
        # Status emoji
        status_emoji = "✅" if status == TransactionStatus.COMPLETED else "⏳" if status == TransactionStatus.PENDING else "❌"
        
        # Format date
        try:
            dt = datetime.fromisoformat(created_at)
            date_str = dt.strftime("%d.%m %H:%M")
        except:
            date_str = "—"
        
        lines.append(f"{emoji} {amount_str} {status_emoji}")
        lines.append(f"   {get_transaction_type_name(tx_type)} • {date_str}")
        
        if tx.get('description'):
            lines.append(f"   {tx['description'][:50]}...")
        
        lines.append("")
    
    return "\n".join(lines)

def get_transaction_type_name(tx_type: str) -> str:
    """Get localized transaction type name"""
    names = {
        TransactionTypes.DEPOSIT: "Поповнення",
        TransactionTypes.WITHDRAWAL: "Виведення",
        TransactionTypes.PAYMENT: "Платіж",
        TransactionTypes.REFUND: "Повернення",
        TransactionTypes.COMMISSION: "Комісія",
        TransactionTypes.ESCROW_FREEZE: "Заморозка",
        TransactionTypes.ESCROW_RELEASE: "Розморозка"
    }
    return names.get(tx_type, tx_type)