"""
Rozdum Bot Database Layer

Модуль для роботи з базою даних (SQLite):
- Ініціалізація та міграції
- CRUD для користувачів, завдань, чатів, файлів, транзакцій, відгуків, спорів
- Допоміжні функції для пошуку, фільтрації, логування

Всі шляхи та налаштування беруться з config.py та .env
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Any
import os
from datetime import datetime
import json

# Import DATABASE_PATH and DEFAULT_RATING from config
try:
    from config import DATABASE_PATH, DEFAULT_RATING
except ImportError:
    # Fallback if config is not available
    DATABASE_PATH = "rozdum.db"
    DEFAULT_RATING = 5.0

# Configure database logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def get_db_connection():
    """Get database connection with row factory."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize database with required tables."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                frozen_balance REAL DEFAULT 0.0,
                rating REAL DEFAULT 5.0,
                reviews_count INTEGER DEFAULT 0,
                executor_tags TEXT DEFAULT '[]',
                state INTEGER DEFAULT 0,
                temp_data TEXT DEFAULT '{}',
                is_admin BOOLEAN DEFAULT FALSE,
                admin_level INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Task offers table to track pending offers
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_offers (
                offer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                executor_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (task_id),
                FOREIGN KEY (executor_id) REFERENCES users (user_id)
            )
        ''')

        # Add missing columns to existing users table if they don't exist
        try:
            cursor.execute('ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE')
        except sqlite3.OperationalError:
            pass  # Column already exists

        try:
            cursor.execute('ALTER TABLE users ADD COLUMN admin_level INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists

        try:
            cursor.execute('ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE')
        except sqlite3.OperationalError:
            pass  # Column already exists

        try:
            cursor.execute('ALTER TABLE users ADD COLUMN is_working BOOLEAN DEFAULT TRUE')
        except sqlite3.OperationalError:
            pass  # Column already exists

        try:
            cursor.execute('ALTER TABLE users ADD COLUMN missed_tasks_count INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists

        try:
            cursor.execute('ALTER TABLE users ADD COLUMN earned_balance REAL DEFAULT 0.0')
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                executor_id INTEGER,
                category TEXT NOT NULL,
                tags TEXT NOT NULL,
                description TEXT NOT NULL,
                price REAL NOT NULL,
                is_vip BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'searching',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES users (user_id),
                FOREIGN KEY (executor_id) REFERENCES users (user_id)
            )
        ''')

        # Chats table for communication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                chat_code TEXT PRIMARY KEY,
                task_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                executor_id INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (task_id),
                FOREIGN KEY (customer_id) REFERENCES users (user_id),
                FOREIGN KEY (executor_id) REFERENCES users (user_id)
            )
        ''')

        # Create reviews table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                reviewer_id INTEGER NOT NULL,
                reviewed_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (task_id),
                FOREIGN KEY (reviewer_id) REFERENCES users (user_id),
                FOREIGN KEY (reviewed_id) REFERENCES users (user_id)
            )
        ''')

        # Disputes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS disputes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                executor_id INTEGER NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'open',
                resolution TEXT,
                resolved_by INTEGER,
                admin_decision TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (task_id),
                FOREIGN KEY (customer_id) REFERENCES users (user_id),
                FOREIGN KEY (executor_id) REFERENCES users (user_id)
            )
        ''')

        # Transactions table for financial operations
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                description TEXT,
                task_id INTEGER,
                payment_method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (task_id) REFERENCES tasks (task_id)
            )
        ''')

        # Chat messages table for storing chat history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_code TEXT NOT NULL,
                sender_id INTEGER NOT NULL,
                sender_role TEXT NOT NULL,
                message_text TEXT,
                message_type TEXT DEFAULT 'text',
                file_name TEXT,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users (user_id)
            )
        ''')

        # Chat files table for file tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_code TEXT NOT NULL,
                sender_id INTEGER NOT NULL,
                sender_role TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users (user_id)
            )
        ''')

        # Task files table for storing files attached to tasks
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_size INTEGER,
                file_path TEXT,
                file_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (task_id),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Create link_settings table for link verification management
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS link_settings (
                setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create trusted_domains table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trusted_domains (
                domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT UNIQUE NOT NULL,
                added_by INTEGER NOT NULL,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (added_by) REFERENCES users (user_id)
            )
        ''')

        # Create blocked_domains table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blocked_domains (
                domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT UNIQUE NOT NULL,
                reason TEXT,
                blocked_by INTEGER NOT NULL,
                blocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (blocked_by) REFERENCES users (user_id)
            )
        ''')

        # Create link_analysis_log table for tracking link checks
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS link_analysis_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_code TEXT,
                original_url TEXT NOT NULL,
                final_url TEXT,
                safety_score INTEGER,
                is_safe BOOLEAN,
                analysis_result TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Create user_temp_data table for storing temporary user data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_temp_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                data_key TEXT NOT NULL,
                data_value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, data_key),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Migration: Allow NULL task_id in task_files for temporary files
        try:
            # Check if task_id column allows NULL
            cursor.execute("PRAGMA table_info(task_files)")
            columns = cursor.fetchall()
            task_id_column = next((col for col in columns if col[1] == 'task_id'), None)

            if task_id_column and task_id_column[3] == 1:  # NOT NULL constraint exists
                logger.info("Migrating task_files table to allow NULL task_id...")

                # Create new table with correct schema
                cursor.execute('''
                    CREATE TABLE task_files_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id INTEGER,
                        user_id INTEGER NOT NULL,
                        file_name TEXT NOT NULL,
                        original_name TEXT NOT NULL,
                        file_size INTEGER,
                        file_path TEXT,
                        file_type TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (task_id) REFERENCES tasks (task_id),
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                ''')

                # Copy data from old table
                cursor.execute('''
                    INSERT INTO task_files_new 
                    SELECT * FROM task_files
                ''')

                # Drop old table and rename new one
                cursor.execute('DROP TABLE task_files')
                cursor.execute('ALTER TABLE task_files_new RENAME TO task_files')

                logger.info("✅ Successfully migrated task_files table")
        except Exception as e:
            logger.warning(f"Migration warning (can be ignored if table is new): {e}")

        # Insert default link settings
        cursor.execute('''
            INSERT OR IGNORE INTO link_settings (setting_key, setting_value) VALUES
            ('link_checking_enabled', 'true'),
            ('min_safety_score', '70'),
            ('block_unsafe_links', 'true'),
            ('log_all_links', 'true'),
            ('notify_admins_unsafe', 'true')
        ''')

        # Create task_search_queue table for tasks waiting for executors
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_search_queue (
                queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                tags TEXT NOT NULL,
                min_rating REAL DEFAULT 0.0,
                max_price REAL,
                priority INTEGER DEFAULT 0,
                attempts_count INTEGER DEFAULT 0,
                last_search_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'searching',
                FOREIGN KEY (task_id) REFERENCES tasks (task_id),
                FOREIGN KEY (customer_id) REFERENCES users (user_id)
            )
        ''')

        # Create executor_availability_log for tracking when executors come online
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS executor_availability_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                executor_id INTEGER NOT NULL,
                became_available_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                tags TEXT NOT NULL,
                rating REAL NOT NULL,
                is_working BOOLEAN DEFAULT 1,
                FOREIGN KEY (executor_id) REFERENCES users (user_id)
            )
        ''')

        # Insert default trusted domains
        default_trusted_domains = [
            'google.com', 'youtube.com', 'wikipedia.org', 'github.com',
            'stackoverflow.com', 'telegram.org', 'discord.com'
        ]

        for domain in default_trusted_domains:
            cursor.execute('''
                INSERT OR IGNORE INTO trusted_domains (domain, added_by) VALUES (?, 1)
            ''', (domain,))

        conn.commit()
        logger.info("Database initialized successfully")

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        conn.rollback()
    finally:
        conn.close()

# User operations
def create_user(user_id: int, username: str = None) -> bool:
    """Create a new user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, rating)
            VALUES (?, ?, ?)
        ''', (user_id, username or "", DEFAULT_RATING))

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error creating user {user_id}: {e}")
        return False
    finally:
        conn.close()

def get_user(user_id: int) -> Optional[Dict]:
    """Get user by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()

        if row:
            user = dict(row)
            user['executor_tags'] = json.loads(user['executor_tags'])
            user['temp_data'] = json.loads(user['temp_data'])
            return user
        return None
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return None
    finally:
        conn.close()

def set_admin_status(user_id: int, is_admin: bool = True, admin_level: int = 1) -> bool:
    """Set admin status for user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users 
            SET is_admin = ?, admin_level = ? 
            WHERE user_id = ?
        """, (is_admin, admin_level, user_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error setting admin status for {user_id}: {e}")
        return False
    finally:
        conn.close()

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    try:
        user = get_user(user_id)
        return user and user.get('is_admin', False)
    except Exception as e:
        logger.error(f"Error checking admin status for {user_id}: {e}")
        return False

def get_all_users(limit: int = None) -> List[Dict]:
    """Get all real users with optional limit."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if limit:
            cursor.execute("""
                SELECT * FROM users 
                WHERE user_id >= 100000 AND username IS NOT NULL AND username != ''
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
        else:
            cursor.execute("""
                SELECT * FROM users 
                WHERE user_id >= 100000 AND username IS NOT NULL AND username != ''
                ORDER BY created_at DESC
            """)
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []
    finally:
        conn.close()

def search_users(query: str) -> List[Dict]:
    """Search real users by username or ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Try to search by ID first (only real users)
        if query.isdigit():
            cursor.execute("""
                SELECT * FROM users 
                WHERE user_id = ? AND user_id >= 100000 
                AND username IS NOT NULL AND username != ''
            """, (int(query),))
            result = cursor.fetchone()
            if result:
                return [result]

        # Search by username (only real users)
        cursor.execute("""
            SELECT * FROM users 
            WHERE (username LIKE ? OR CAST(user_id AS TEXT) LIKE ?)
            AND user_id >= 100000 
            AND username IS NOT NULL AND username != ''
            ORDER BY created_at DESC
        """, (f"%{query}%", f"%{query}%"))

        return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return []
    finally:
        conn.close()

def update_user(user_id: int, **kwargs) -> bool:
    """Update user data."""
    if not kwargs:
        return False

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Handle JSON fields
        if 'executor_tags' in kwargs:
            kwargs['executor_tags'] = json.dumps(kwargs['executor_tags'])
        if 'temp_data' in kwargs:
            kwargs['temp_data'] = json.dumps(kwargs['temp_data'])

        # Add updated_at timestamp
        kwargs['updated_at'] = datetime.now().isoformat()

        # Build query
        set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]

        cursor.execute(f'''
            UPDATE users SET {set_clause} WHERE user_id = ?
        ''', values)

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        return False
    finally:
        conn.close()

def update_user_balance(user_id: int, balance_change: float, frozen_change: float = 0) -> bool:
    """Update user balance atomically."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE users 
            SET balance = balance + ?, 
                frozen_balance = frozen_balance + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (balance_change, frozen_change, user_id))

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating balance for user {user_id}: {e}")
        return False
    finally:
        conn.close()

# Task operations
def create_task(customer_id: int, category: str, tags: List[str], 
               description: str, price: float, is_vip: bool = False) -> Optional[int]:
    """Create a new task."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO tasks (customer_id, category, tags, description, price, is_vip)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (customer_id, category, json.dumps(tags), description, price, is_vip))

        task_id = cursor.lastrowid
        conn.commit()
        return task_id
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return None
    finally:
        conn.close()

def get_task(task_id: int) -> Optional[Dict]:
    """Get task by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM tasks WHERE task_id = ?', (task_id,))
        row = cursor.fetchone()

        if row:
            task = dict(row)
            task['tags'] = json.loads(task['tags'])
            return task
        return None
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {e}")
        return None
    finally:
        conn.close()

def update_task(task_id: int, **kwargs) -> bool:
    """Update task data."""
    if not kwargs:
        return False

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Handle JSON fields
        if 'tags' in kwargs:
            kwargs['tags'] = json.dumps(kwargs['tags'])

        # Build query
        set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
        values = list(kwargs.values()) + [task_id]

        cursor.execute(f'''
            UPDATE tasks SET {set_clause} WHERE task_id = ?
        ''', values)

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating task {task_id}: {e}")
        return False
    finally:
        conn.close()

def get_user_tasks(user_id: int, as_customer: bool = True) -> List[Dict]:
    """Get user's tasks as customer or executor."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if as_customer:
            cursor.execute('''
                SELECT * FROM tasks WHERE customer_id = ? 
                ORDER BY created_at DESC
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT * FROM tasks WHERE executor_id = ? 
                ORDER BY created_at DESC
            ''', (user_id,))

        rows = cursor.fetchall()
        tasks = []
        for row in rows:
            task = dict(row)
            task['tags'] = json.loads(task['tags'])
            tasks.append(task)

        return tasks
    except Exception as e:
        logger.error(f"Error getting tasks for user {user_id}: {e}")
        return []
    finally:
        conn.close()

def get_available_executors(category: str, tags: List[str], min_rating: float = 0) -> List[Dict]:
    """Get available executors for a task with language-aware tag matching."""
    from utils.tag_translator import find_matching_tags

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT user_id, username, executor_tags, rating, 
                   COALESCE(completed_tasks, 0) as completed_tasks, 
                   COALESCE(is_working, 1) as is_working, 
                   COALESCE(missed_tasks_count, 0) as missed_tasks_count,
                   (SELECT COUNT(*) FROM tasks WHERE executor_id = users.user_id AND status = 'in_progress') as active_tasks
            FROM users 
            WHERE rating >= ? AND executor_tags IS NOT NULL AND executor_tags != '' 
                  AND COALESCE(is_working, 1) = 1
                  AND COALESCE(is_blocked, 0) = 0
                  AND user_id >= 100000
                  AND username IS NOT NULL AND username != ''
                  AND user_id NOT IN (
                      SELECT executor_id FROM task_offers 
                      WHERE status = 'pending' AND expires_at > datetime('now')
                  )
        ''', (min_rating,))

        rows = cursor.fetchall()
        suitable_executors = []

        for row in rows:
            user = dict(row)
            try:
                user_tags = json.loads(user['executor_tags'])

                # Handle old format (list) - skip and log warning
                if isinstance(user_tags, list):
                    logger.warning(f"⚠️ Executor {user['user_id']} has old tag format (list): {user_tags}")
                    logger.warning(f"   Please run fix_remaining_users.py to convert to new format")
                    continue

                # Ensure it's a dictionary
                if not isinstance(user_tags, dict):
                    logger.warning(f"⚠️ Executor {user['user_id']} has invalid tag format: {type(user_tags)}")
                    continue

                # Check if executor has the required category and matching tags
                if category in user_tags:
                    executor_category_tags = user_tags[category]

                    # Use language-aware tag matching
                    matching_tags = find_matching_tags(tags, executor_category_tags)

                    # More flexible matching - require at least 70% of tags to match
                    required_tags_count = len(tags)
                    matching_count = len(matching_tags)
                    match_percentage = matching_count / required_tags_count if required_tags_count > 0 else 0

                    if match_percentage >= 0.7:  # At least 70% match
                        user['matching_tags_count'] = matching_count
                        user['match_percentage'] = match_percentage
                        user['category_tags'] = executor_category_tags
                        user['matching_tags'] = matching_tags
                        suitable_executors.append(user)


            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.error(f"Error parsing executor tags for user {user['user_id']}: {e}")
                continue

        # Sort by match percentage and rating
        suitable_executors.sort(key=lambda x: (x.get('match_percentage', 0), x.get('rating', 0)), reverse=True)

        return suitable_executors
    except Exception as e:
        logger.error(f"Error getting available executors: {e}")
        return []
    finally:
        conn.close()

# Review operations
def add_review(task_id: int, reviewer_id: int, reviewed_id: int, rating: int, comment: str = None) -> bool:
    """Add a review and update user rating."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Add review
        cursor.execute('''
            INSERT INTO reviews (task_id, reviewer_id, reviewed_id, rating, comment)
            VALUES (?, ?, ?, ?, ?)
        ''', (task_id, reviewer_id, reviewed_id, rating, comment or ""))

        # Update user rating
        cursor.execute('''
            UPDATE users SET 
                rating = (SELECT AVG(rating) FROM reviews WHERE reviewed_id = ?),
                reviews_count = (SELECT COUNT(*) FROM reviews WHERE reviewed_id = ?)
            WHERE user_id = ?
        ''', (reviewed_id, reviewed_id, reviewed_id))

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding review: {e}")
        return False
    finally:
        conn.close()

def get_user_reviews(user_id: int, as_reviewer: bool = False) -> List[Dict]:
    """Get reviews for a user or reviews written by a user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if as_reviewer:
            # Get reviews written by the user
            cursor.execute('''
                SELECT r.*, u.username as reviewed_username, t.category, t.description
                FROM reviews r
                JOIN users u ON r.reviewed_id = u.user_id
                JOIN tasks t ON r.task_id = t.task_id
                WHERE r.reviewer_id = ?
                ORDER BY r.created_at DESC
            ''', (user_id,))
        else:
            # Get reviews about the user
            cursor.execute('''
                SELECT r.*, u.username as reviewer_username, t.category, t.description
                FROM reviews r
                JOIN users u ON r.reviewer_id = u.user_id
                JOIN tasks t ON r.task_id = t.task_id
                WHERE r.reviewed_id = ?
                ORDER BY r.created_at DESC
            ''', (user_id,))

        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting reviews: {e}")
        return []
    finally:
        conn.close()

def get_user_rating_stats(user_id: int) -> Optional[Dict]:
    """Get user rating statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get overall stats
        cursor.execute('''
            SELECT 
                AVG(rating) as average_rating,
                COUNT(*) as total_reviews,
                MAX(rating) as max_rating,
                MIN(rating) as min_rating
            FROM reviews
            WHERE reviewed_id = ?
        ''', (user_id,))

        stats_row = cursor.fetchone()
        if not stats_row or stats_row[1] == 0:  # No reviews
            return None

        stats = dict(stats_row)

        # Get rating distribution
        cursor.execute('''
            SELECT rating, COUNT(*) as count
            FROM reviews
            WHERE reviewed_id = ?
            GROUP BY rating
        ''', (user_id,))

        for rating, count in cursor.fetchall():
            stats[f'rating_{rating}'] = count

        # Get completed tasks count
        cursor.execute('''
            SELECT COUNT(*) FROM tasks 
            WHERE executor_id = ? AND status IN ('completed', 'finished')
        ''', (user_id,))

        stats['completed_tasks'] = cursor.fetchone()[0]

        return stats
    except Exception as e:
        logger.error(f"Error getting user rating stats: {e}")
        return None
    finally:
        conn.close()

def get_user_rating_history(user_id: int) -> Dict:
    """Get detailed rating history for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get rating distribution
        cursor.execute('''
            SELECT rating, COUNT(*) as count
            FROM reviews
            WHERE reviewed_id = ?
            GROUP BY rating
            ORDER BY rating DESC
        ''', (user_id,))

        rating_distribution = dict(cursor.fetchall())

        # Get average rating by category
        cursor.execute('''
            SELECT t.category, AVG(r.rating) as avg_rating, COUNT(*) as count
            FROM reviews r
            JOIN tasks t ON r.task_id = t.task_id
            WHERE r.reviewed_id = ?
            GROUP BY t.category
            ORDER BY avg_rating DESC
        ''', (user_id,))

        category_ratings = [dict(row) for row in cursor.fetchall()]

        # Get recent reviews
        cursor.execute('''
            SELECT r.*, u.username as reviewer_username, t.category, t.description
            FROM reviews r
            JOIN users u ON r.reviewer_id = u.user_id
            JOIN tasks t ON r.task_id = t.task_id
            WHERE r.reviewed_id = ?
            ORDER BY r.created_at DESC
            LIMIT 10
        ''', (user_id,))

        recent_reviews = [dict(row) for row in cursor.fetchall()]

        # Get overall stats
        cursor.execute('''
            SELECT 
                AVG(rating) as avg_rating,
                COUNT(*) as total_reviews,
                MAX(rating) as max_rating,
                MIN(rating) as min_rating
            FROM reviews
            WHERE reviewed_id = ?
        ''', (user_id,))

        stats_row = cursor.fetchone()
        stats = dict(stats_row) if stats_row else {}

        return {
            'rating_distribution': rating_distribution,
            'category_ratings': category_ratings,
            'recent_reviews': recent_reviews,
            'stats': stats
        }
    except Exception as e:
        logger.error(f"Error getting rating history: {e}")
        return {}
    finally:
        conn.close()

# Task Search Queue Functions

def add_task_to_search_queue(task_id: int, customer_id: int, category: str, 
                           tags: List[str], min_rating: float = 0.0, 
                           priority: int = 0) -> bool:
    """Add task to search queue when no executor found immediately."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get task details for price limit
        task = get_task(task_id)
        if not task:
            return False

        cursor.execute("""
            INSERT INTO task_search_queue 
            (task_id, customer_id, category, tags, min_rating, max_price, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (task_id, customer_id, category, json.dumps(tags), 
              min_rating, task['price'], priority))

        conn.commit()
        logger.info(f"Task {task_id} added to search queue")
        return True

    except Exception as e:
        logger.error(f"Error adding task to search queue: {e}")
        return False
    finally:
        conn.close()

def remove_task_from_search_queue(task_id: int) -> bool:
    """Remove task from search queue when executor found or task cancelled."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            DELETE FROM task_search_queue WHERE task_id = ?
        """, (task_id,))

        conn.commit()
        logger.info(f"Task {task_id} removed from search queue")
        return True
    except Exception as e:
        logger.error(f"Error removing task from search queue: {e}")
        return False
    finally:
        conn.close()

def get_tasks_waiting_for_executors() -> List[Dict]:
    """Get all tasks currently waiting for executors."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT tsq.*, t.description, t.price, t.is_vip, u.username as customer_name
            FROM task_search_queue tsq
            JOIN tasks t ON tsq.task_id = t.task_id
            JOIN users u ON tsq.customer_id = u.user_id
            WHERE tsq.status = 'searching'
            ORDER BY tsq.priority DESC, tsq.created_at ASC
        """)

        return [dict(row) for row in cursor.fetchall()]

    except Exception as e:
        logger.error(f"Error getting waiting tasks: {e}")
        return []
    finally:
        conn.close()

def update_search_queue_attempt(task_id: int) -> bool:
    """Update search attempt count and timestamp."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE task_search_queue 
            SET attempts_count = attempts_count + 1,
                last_search_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
        """, (task_id,))

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"Error updating search attempt: {e}")
        return False
    finally:
        conn.close()

def log_executor_availability(executor_id: int, tags: List[str], rating: float, is_working: bool = True) -> bool:
    """Log when executor becomes available for instant matching."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO executor_availability_log 
            (executor_id, tags, rating, is_working)
            VALUES (?, ?, ?, ?)
        """, (executor_id, json.dumps(tags), rating, is_working))

        conn.commit()
        return True

    except Exception as e:
        logger.error(f"Error logging executor availability: {e}")
        return False
    finally:
        conn.close()

def find_matching_tasks_for_executor(executor_id: int, executor_tags: Dict[str, List[str]], 
                                   executor_rating: float) -> List[Dict]:
    """Find tasks in queue that match executor skills."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get tasks that this executor could potentially handle
        cursor.execute("""
            SELECT tsq.*, t.description, t.price, t.is_vip
            FROM task_search_queue tsq
            JOIN tasks t ON tsq.task_id = t.task_id
            WHERE tsq.status = 'searching' AND tsq.min_rating <= ?
            ORDER BY tsq.priority DESC, tsq.created_at ASC
        """, (executor_rating,))

        tasks = [dict(row) for row in cursor.fetchall()]
        matching_tasks = []

        for task in tasks:
            try:
                task_tags = json.loads(task['tags'])
                task_category = task['category']

                # Check if executor has the required category and tags
                if task_category in executor_tags:
                    executor_category_tags = set(executor_tags[task_category])
                    required_tags = set(task_tags)

                    # Check if executor has ALL required tags
                    if required_tags.issubset(executor_category_tags):
                        matching_tasks.append(task)

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Error parsing task tags: {e}")
                continue

        return matching_tasks

    except Exception as e:
        logger.error(f"Error finding matching tasks: {e}")
        return []
    finally:
        conn.close()

def create_dispute(task_id: int, customer_id: int, executor_id: int, reason: str) -> Optional[int]:
    """Create a new dispute."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO disputes (task_id, customer_id, executor_id, reason, status, created_at)
            VALUES (?, ?, ?, ?, 'open', datetime('now'))
        ''', (task_id, customer_id, executor_id, reason))

        dispute_id = cursor.lastrowid
        conn.commit()
        logger.info(f"Created dispute {dispute_id} for task {task_id}")
        return dispute_id
    except Exception as e:
        logger.error(f"Error creating dispute: {e}")
        return None
    finally:
        conn.close()

def get_dispute(dispute_id: int) -> Optional[Dict]:
    """Get dispute by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT d.*, t.description, t.price, t.category,
                   c.username as customer_username, e.username as executor_username
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            LEFT JOIN users c ON d.customer_id = c.user_id
            LEFT JOIN users e ON d.executor_id = e.user_id
            WHERE d.dispute_id = ?
        ''', (dispute_id,))

        result = cursor.fetchone()
        return dict(result) if result else None
    except Exception as e:
        logger.error(f"Error getting dispute: {e}")
        return None
    finally:
        conn.close()

def get_open_disputes() -> List[Dict]:
    """Get all open disputes."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT d.*, t.description, t.price, t.category,
                   c.username as customer_username, e.username as executor_username
            FROM disputes d
            JOIN tasks t ON d.task_id = t.task_id
            LEFT JOIN users c ON d.customer_id = c.user_id
            LEFT JOIN users e ON d.executor_id = e.user_id
            WHERE d.status = 'open'
            ORDER BY d.created_at DESC
        ''')

        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting open disputes: {e}")
        return []
    finally:
        conn.close()

def resolve_dispute(dispute_id: int, resolution: str, admin_id: int, admin_decision: str) -> bool:
    """Resolve a dispute."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE disputes 
            SET status = 'resolved', resolution = ?, admin_id = ?, admin_decision = ?, resolved_at = datetime('now')
            WHERE dispute_id = ?
        ''', (resolution, admin_id, admin_decision, dispute_id))

        conn.commit()
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Resolved dispute {dispute_id} with resolution: {resolution}")
        return success
    except Exception as e:
        logger.error(f"Error resolving dispute: {e}")
        return False
    finally:
        conn.close()

def get_user_temp_files(user_id: int) -> List[Dict]:
    """Get temporary files for user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT * FROM task_files 
            WHERE user_id = ? AND task_id IS NULL
            ORDER BY created_at DESC
        ''', (user_id,))

        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting temp files: {e}")
        return []
    finally:
        conn.close()

def update_temp_files_task_id(user_id: int, task_id: int) -> bool:
    """Update temporary files with task ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE task_files 
            SET task_id = ? 
            WHERE user_id = ? AND task_id IS NULL
        ''', (task_id, user_id))

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating temp files: {e}")
        return False
    finally:
        conn.close()

def delete_user_temp_files(user_id: int) -> bool:
    """Delete all temporary files for user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            DELETE FROM task_files 
            WHERE user_id = ? AND task_id IS NULL
        ''', (user_id,))

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting temp files: {e}")
        return False
    finally:
        conn.close()

def check_review_exists(task_id: int, reviewer_id: int, reviewed_id: int) -> bool:
    """Check if review already exists."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT COUNT(*) FROM reviews 
            WHERE task_id = ? AND reviewer_id = ? AND reviewed_id = ?
        ''', (task_id, reviewer_id, reviewed_id))

        count = cursor.fetchone()[0]
        return count > 0
    except Exception as e:
        logger.error(f"Error checking review existence: {e}")
        return False
    finally:
        conn.close()

def get_task_reviews(task_id: int) -> List[Dict]:
    """Get all reviews for a specific task."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT r.*, 
                   reviewer.username as reviewer_username,
                   reviewed.username as reviewed_username
            FROM reviews r
            JOIN users reviewer ON r.reviewer_id = reviewer.user_id
            JOIN users reviewed ON r.reviewed_id = reviewed.user_id
            WHERE r.task_id = ?
            ORDER BY r.created_at DESC
        ''', (task_id,))

        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting task reviews: {e}")
        return []
    finally:
        conn.close()

def cleanup_expired_offers() -> int:
    """Clean up expired task offers and reset task status."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # First, get tasks that have expired offers
        cursor.execute("""
            SELECT DISTINCT task_id FROM task_offers 
            WHERE status = 'pending' AND expires_at < datetime('now')
        """)

        expired_task_ids = [row[0] for row in cursor.fetchall()]

        # Delete expired offers
        cursor.execute("""
            DELETE FROM task_offers 
            WHERE status = 'pending' AND expires_at < datetime('now')
        """)

        deleted_count = cursor.rowcount

        # Reset task status to searching for tasks with expired offers
        # but only if they don't have other pending offers
        for task_id in expired_task_ids:
            cursor.execute("""
                SELECT COUNT(*) FROM task_offers 
                WHERE task_id = ? AND status = 'pending'
            """, (task_id,))

            remaining_offers = cursor.fetchone()[0]

            if remaining_offers == 0:
                # No more pending offers, reset to searching
                cursor.execute("""
                    UPDATE tasks 
                    SET status = 'searching', executor_id = NULL 
                    WHERE task_id = ? AND status = 'offered'
                """, (task_id,))

                logger.info(f"Reset task {task_id} status to searching after expired offers")

        conn.commit()

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired task offers")

        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up expired offers: {e}")
        return 0
    finally:
        conn.close()

def create_task_offer(task_id: int, executor_id: int, expires_in_minutes: int = 30) -> bool:
    """Create a task offer for an executor."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # First check if offer already exists
        cursor.execute("""
            SELECT COUNT(*) FROM task_offers 
            WHERE task_id = ? AND executor_id = ? AND status = 'pending'
        """, (task_id, executor_id))

        if cursor.fetchone()[0] > 0:
            logger.info(f"Task offer already exists for task {task_id} and executor {executor_id}")
            return False

        # Create new offer
        cursor.execute("""
            INSERT INTO task_offers (task_id, executor_id, status, expires_at)
            VALUES (?, ?, 'pending', datetime('now', '+{} minutes'))
        """.format(expires_in_minutes), (task_id, executor_id))

        conn.commit()
        logger.info(f"Created task offer for task {task_id} to executor {executor_id}")
        return True
    except Exception as e:
        logger.error(f"Error creating task offer: {e}")
        return False
    finally:
        conn.close()

def get_task_offer(task_id: int, executor_id: int) -> Optional[Dict]:
    """Get task offer for specific task and executor."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT * FROM task_offers 
            WHERE task_id = ? AND executor_id = ? AND status = 'pending'
            AND expires_at > datetime('now')
        """, (task_id, executor_id))

        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error getting task offer: {e}")
        return None
    finally:
        conn.close()

def accept_task_offer(task_id: int, executor_id: int) -> bool:
    """Accept a task offer."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Update offer status
        cursor.execute("""
            UPDATE task_offers 
            SET status = 'accepted' 
            WHERE task_id = ? AND executor_id = ? AND status = 'pending'
        """, (task_id, executor_id))

        if cursor.rowcount == 0:
            logger.warning(f"No pending offer found for task {task_id} and executor {executor_id}")
            return False

        # Update task with executor
        cursor.execute("""
            UPDATE tasks 
            SET executor_id = ?, status = 'in_progress'
            WHERE task_id = ? AND status = 'searching'
        """, (executor_id, task_id))

        # Cancel other pending offers for this task
        cursor.execute("""
            UPDATE task_offers 
            SET status = 'cancelled' 
            WHERE task_id = ? AND executor_id != ? AND status = 'pending'
        """, (task_id, executor_id))

        conn.commit()
        logger.info(f"Task offer accepted for task {task_id} by executor {executor_id}")
        return True
    except Exception as e:
        logger.error(f"Error accepting task offer: {e}")
        return False
    finally:
        conn.close()

def reject_task_offer(task_id: int, executor_id: int) -> bool:
    """Reject a task offer."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE task_offers 
            SET status = 'rejected' 
            WHERE task_id = ? AND executor_id = ? AND status = 'pending'
        """, (task_id, executor_id))

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error rejecting task offer: {e}")
        return False
    finally:
        conn.close()

def get_declined_executors_for_task(task_id: int) -> list:
    """Get list of executor IDs who declined this specific task."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT DISTINCT executor_id 
            FROM task_offers 
            WHERE task_id = ? AND status = 'rejected'
        """, (task_id,))

        result = cursor.fetchall()
        return [row[0] for row in result]
    except Exception as e:
        logger.error(f"Error getting declined executors for task {task_id}: {e}")
        return []
    finally:
        conn.close()

def update_task_offer_status(task_id: int, executor_id: int, status: str) -> bool:
    """Update task offer status."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE task_offers 
            SET status = ? 
            WHERE task_id = ? AND executor_id = ?
        """, (status, task_id, executor_id))

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating task offer status: {e}")
        return False
    finally:
        conn.close()

def increment_missed_tasks(user_id: int) -> int:
    """Increment missed tasks counter and return new count."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users 
            SET missed_tasks_count = COALESCE(missed_tasks_count, 0) + 1
            WHERE user_id = ?
        """, (user_id,))

        # Get the new count
        cursor.execute("""
            SELECT COALESCE(missed_tasks_count, 0) FROM users WHERE user_id = ?
        """, (user_id,))

        result = cursor.fetchone()
        missed_count = result[0] if result else 0

        conn.commit()
        logger.info(f"Incremented missed tasks for user {user_id}, new count: {missed_count}")
        return missed_count
    except Exception as e:
        logger.error(f"Error incrementing missed tasks for user {user_id}: {e}")
        return 0
    finally:
        conn.close()

def reset_missed_tasks(user_id: int) -> bool:
    """Reset missed tasks counter to 0."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users 
            SET missed_tasks_count = 0
            WHERE user_id = ?
        """, (user_id,))

        conn.commit()
        logger.info(f"Reset missed tasks counter for user {user_id}")
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error resetting missed tasks for user {user_id}: {e}")
        return False
    finally:
        conn.close()

def set_work_status(user_id: int, is_working: bool) -> bool:
    """Set user work status."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users 
            SET is_working = ?
            WHERE user_id = ?
        """, (is_working, user_id))

        conn.commit()
        logger.info(f"Set work status for user {user_id} to {is_working}")
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error setting work status for user {user_id}: {e}")
        return False
    finally:
        conn.close()

def update_task_offer_status(task_id: int, executor_id: int, status: str) -> bool:
    """Update task offer status."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE task_offers 
            SET status = ?
            WHERE task_id = ? AND executor_id = ?
        """, (status, task_id, executor_id))

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating task offer status: {e}")
        return False
    finally:
        conn.close()

def save_temp_task_file(user_id: int, file_name: str, original_name: str, 
                       file_size: int, file_path: str, file_type: str) -> Optional[int]:
    """Save temporary task file during task creation."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO task_files 
            (task_id, user_id, file_name, original_name, file_size, file_path, file_type)
            VALUES (NULL, ?, ?, ?, ?, ?, ?)
        """, (user_id, file_name, original_name, file_size, file_path, file_type))

        file_id = cursor.lastrowid
        conn.commit()
        logger.info(f"✅ Saved temp file {original_name} for user {user_id}")
        return file_id
    except Exception as e:
        logger.error(f"❌ Error saving temp file: {e}")
        return None
    finally:
        conn.close()

def save_task_file(task_id: int, user_id: int, file_name: str, original_name: str, 
                  file_size: int, file_path: str, file_type: str) -> Optional[int]:
    """Save task file."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO task_files 
            (task_id, user_id, file_name, original_name, file_size, file_path, file_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (task_id, user_id, file_name, original_name, file_size, file_path, file_type))

        file_id = cursor.lastrowid
        conn.commit()
        logger.info(f"✅ Saved task file {original_name} for task {task_id}")
        return file_id
    except Exception as e:
        logger.error(f"❌ Error saving task file: {e}")
        return None
    finally:
        conn.close()

def get_task_files(task_id: int) -> List[Dict]:
    """Get files attached to a task."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT tf.*, u.username
            FROM task_files tf 
            LEFT JOIN users u ON tf.user_id = u.user_id
            WHERE tf.task_id = ? 
            ORDER BY tf.created_at
        """, (task_id,))

        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting task files: {e}")
        return []
    finally:
        conn.close()

def get_chat_files(chat_code: str) -> List[Dict]:
    """Get files shared in a chat."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT * FROM chat_files 
            WHERE chat_code = ? 
            ORDER BY created_at
        """, (chat_code,))

        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting chat files: {e}")
        return []
    finally:
        conn.close()

def get_user_temp_data(user_id: int, data_key: str) -> Optional[str]:
    """Get temporary user data by key."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT data_value FROM user_temp_data 
            WHERE user_id = ? AND data_key = ?
        """, (user_id, data_key))

        result = cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting user temp data: {e}")
        return None
    finally:
        conn.close()

def set_user_temp_data(user_id: int, data_key: str, data_value: str) -> bool:
    """Set temporary user data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO user_temp_data (user_id, data_key, data_value)
            VALUES (?, ?, ?)
        """, (user_id, data_key, data_value))

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting user temp data: {e}")
        return False
    finally:
        conn.close()

def delete_user_temp_data(user_id: int, data_key: str) -> bool:
    """Delete temporary user data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            DELETE FROM user_temp_data 
            WHERE user_id = ? AND data_key = ?
        """, (user_id, data_key))

        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting user temp data: {e}")
        return False
    finally:
        conn.close()

# The following function has been modified to reduce logging verbosity.
def get_available_executors(category: str, tags: List[str], min_rating: float = 0) -> List[Dict]:
    """Get available executors for a task with language-aware tag matching."""
    from utils.tag_translator import find_matching_tags

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT user_id, username, executor_tags, rating, 
                   COALESCE(completed_tasks, 0) as completed_tasks, 
                   COALESCE(is_working, 1) as is_working, 
                   COALESCE(missed_tasks_count, 0) as missed_tasks_count,
                   (SELECT COUNT(*) FROM tasks WHERE executor_id = users.user_id AND status = 'in_progress') as active_tasks
            FROM users 
            WHERE rating >= ? AND executor_tags IS NOT NULL AND executor_tags != '' 
                  AND COALESCE(is_working, 1) = 1
                  AND COALESCE(is_blocked, 0) = 0
                  AND user_id >= 100000
                  AND username IS NOT NULL AND username != ''
                  AND user_id NOT IN (
                      SELECT executor_id FROM task_offers 
                      WHERE status = 'pending' AND expires_at > datetime('now')
                  )
        ''', (min_rating,))

        rows = cursor.fetchall()
        suitable_executors = []

        for row in rows:
            user = dict(row)
            try:
                user_tags = json.loads(user['executor_tags'])

                # Handle old format (list) - skip and log warning
                if isinstance(user_tags, list):
                    logger.warning(f"⚠️ Executor {user['user_id']} has old tag format (list): {user_tags}")
                    logger.warning(f"   Please run fix_remaining_users.py to convert to new format")
                    continue

                # Ensure it's a dictionary
                if not isinstance(user_tags, dict):
                    logger.warning(f"⚠️ Executor {user['user_id']} has invalid tag format: {type(user_tags)}")
                    continue

                # Check if executor has the required category and matching tags
                if category in user_tags:
                    executor_category_tags = user_tags[category]

                    # Use language-aware tag matching
                    matching_tags = find_matching_tags(tags, executor_category_tags)

                    # More flexible matching - require at least 70% of tags to match
                    required_tags_count = len(tags)
                    matching_count = len(matching_tags)
                    match_percentage = matching_count / required_tags_count if required_tags_count > 0 else 0

                    if match_percentage >= 0.7:  # At least 70% match
                        user['matching_tags_count'] = matching_count
                        user['match_percentage'] = match_percentage
                        user['category_tags'] = executor_category_tags
                        user['matching_tags'] = matching_tags
                        suitable_executors.append(user)


            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.error(f"Error parsing executor tags for user {user['user_id']}: {e}")
                continue

        # Sort by match percentage and rating
        suitable_executors.sort(key=lambda x: (x.get('match_percentage', 0), x.get('rating', 0)), reverse=True)

        return suitable_executors
    except Exception as e:
        logger.error(f"Error getting available executors: {e}")
        return []
    finally:
        conn.close()

def find_suitable_executors(category: str, required_tags: list) -> list:
    """Find executors that match the task requirements."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Find executors in the same category
        cursor.execute("""
            SELECT user_id, username, executor_tags, rating, reviews_count, is_vip_executor
            FROM users 
            WHERE is_executor = 1 
            AND executor_tags IS NOT NULL 
            AND executor_tags != ''
            AND executor_tags != '{}'
            ORDER BY rating DESC, reviews_count DESC
        """)

        potential_executors = cursor.fetchall()
        conn.close()

        suitable_executors = []

        for executor in potential_executors:
            try:
                # Parse executor tags
                executor_tags_raw = executor['executor_tags']
                if isinstance(executor_tags_raw, str):
                    executor_tags = json.loads(executor_tags_raw)
                else:
                    executor_tags = executor_tags_raw or {}

                # Check if executor has the required category
                if category in executor_tags:
                    executor_category_tags = executor_tags[category]

                    # Check if the executor has ALL required tags
                    if all(tag in executor_category_tags for tag in required_tags):
                        suitable_executors.append(executor)

            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error parsing executor tags: {e}")
                continue

        return suitable_executors
    except Exception as e:
        logger.error(f"Error finding suitable executors: {e}")
        return []

# Link management functions for admin bot
def get_link_analysis_stats() -> Dict:
    """Get link analysis statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                COUNT(*) as total_analyzed,
                SUM(CASE WHEN is_safe = 1 THEN 1 ELSE 0 END) as safe_links,
                SUM(CASE WHEN is_safe = 0 THEN 1 ELSE 0 END) as unsafe_links
            FROM link_analysis_log
        """)

        result = cursor.fetchone()
        if result:
            return {
                'total_analyzed': result[0] or 0,
                'safe_links': result[1] or 0,
                'unsafe_links': result[2] or 0
            }
        return {'total_analyzed': 0, 'safe_links': 0, 'unsafe_links': 0}
    except Exception as e:
        logger.error(f"Error getting link analysis stats: {e}")
        return {'total_analyzed': 0, 'safe_links': 0, 'unsafe_links': 0}
    finally:
        conn.close()

def get_blocked_domains() -> List[Dict]:
    """Get list of blocked domains."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT domain, reason, blocked_at, blocked_by
            FROM blocked_domains 
            WHERE is_active = 1
            ORDER BY blocked_at DESC
        """)

        return [{'domain': row[0], 'reason': row[1], 'blocked_at': row[2], 'blocked_by': row[3]} 
                for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting blocked domains: {e}")
        return []
    finally:
        conn.close()

def get_trusted_domains() -> List[str]:
    """Get list of trusted domains."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT domain FROM trusted_domains 
            WHERE is_active = 1
            ORDER BY domain
        """)

        return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error getting trusted domains: {e}")
        return []
    finally:
        conn.close()


def log_link_analysis(user_id: int, event_type: str, original_url: str, final_url: str, 
                     safety_score: int, is_safe: bool, analysis_result: str, chat_code: str = None) -> None:
    """Log link analysis result."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO link_analysis_log 
            (user_id, chat_code, original_url, final_url, safety_score, is_safe, analysis_result, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (user_id, chat_code, original_url, final_url, safety_score, is_safe, analysis_result))

        conn.commit()
    except Exception as e:
        logger.error(f"Error logging link analysis: {e}")
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict]:
    """Get user by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT user_id, username, balance, rating, is_admin, admin_level, created_at
            FROM users WHERE user_id = ?
        """, (user_id,))

        result = cursor.fetchone()
        if result:
            return dict(result)
        return None
    except Exception as e:
        logger.error(f"Error getting user by ID: {e}")
        return None
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[Dict]:
    """Get user by username."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT user_id, username, balance, rating, is_admin, admin_level, created_at
            FROM users WHERE username = ?
        """, (username,))

        result = cursor.fetchone()
        if result:
            return dict(result)
        return None
    except Exception as e:
        logger.error(f"Error getting user by username: {e}")
        return None
    finally:
        conn.close()

def get_link_setting(setting_key: str) -> Optional[str]:
    """Get link setting value by key."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT setting_value FROM link_settings 
            WHERE setting_key = ?
        """, (setting_key,))

        result = cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting link setting: {e}")
        return None
    finally:
        conn.close()

def set_link_setting(setting_key: str, setting_value: str) -> bool:
    """Set link setting value."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO link_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (setting_key, setting_value))

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting link setting: {e}")
        return False
    finally:
        conn.close()

def block_domain(domain: str, reason: str, blocked_by: int = 1) -> bool:
    """Block a domain."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO blocked_domains (domain, reason, blocked_by, is_active)
            VALUES (?, ?, ?, 1)
        """, (domain, reason, blocked_by))

        conn.commit()
        logger.info(f"Blocked domain: {domain}")
        return True
    except Exception as e:
        logger.error(f"Error blocking domain: {e}")
        return False
    finally:
        conn.close()

def unblock_domain(domain: str) -> bool:
    """Unblock a domain."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE blocked_domains 
            SET is_active = 0
            WHERE domain = ?
        """, (domain,))

        conn.commit()
        logger.info(f"Unblocked domain: {domain}")
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error unblocking domain: {e}")
        return False
    finally:
        conn.close()

def add_trusted_domain(domain: str, added_by: int = 1) -> bool:
    """Add a trusted domain."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR IGNORE INTO trusted_domains (domain, added_by, is_active)
            VALUES (?, ?, 1)
        """, (domain, added_by))

        conn.commit()
        logger.info(f"Added trusted domain: {domain}")
        return True
    except Exception as e:
        logger.error(f"Error adding trusted domain: {e}")
        return False
    finally:
        conn.close()

def remove_trusted_domain(domain: str) -> bool:
    """Remove a trusted domain."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trusted_domains 
            SET is_active = 0
            WHERE domain = ?
        """, (domain,))

        conn.commit()
        logger.info(f"Removed trusted domain: {domain}")
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing trusted domain: {e}")
        return False
    finally:
        conn.close()

def log_link_analysis(user_id: int, chat_code: str, original_url: str, 
                     final_url: str, safety_score: int, is_safe: bool, 
                     analysis_result: str) -> bool:
    """Log link analysis result."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO link_analysis_log 
            (user_id, chat_code, original_url, final_url, safety_score, is_safe, analysis_result)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, chat_code, original_url, final_url, safety_score, is_safe, analysis_result))

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error logging link analysis: {e}")
        return False
    finally:
        conn.close()

def clear_link_analysis_log() -> int:
    """Clear all link analysis logs."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM link_analysis_log")
        deleted_count = cursor.rowcount
        conn.commit()
        logger.info(f"Cleared {deleted_count} link analysis log entries")
        return deleted_count
    except Exception as e:
        logger.error(f"Error clearing link analysis log: {e}")
        return 0
    finally:
        conn.close()

init_database()