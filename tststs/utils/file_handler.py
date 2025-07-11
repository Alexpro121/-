"""
File handling utilities for Rozdum Bot
"""

import os
import logging
import uuid
from typing import Optional, Dict, List
from telegram import Update, File
from telegram.ext import ContextTypes

try:
    from config import MAX_FILE_SIZE, ALLOWED_FILE_TYPES
except ImportError:
    # Fallback values when imported from chat_bot
    MAX_FILE_SIZE = 150 * 1024 * 1024  # 150 MB
    ALLOWED_FILE_TYPES = {
        'document': ['pdf', 'doc', 'docx', 'txt', 'rtf', 'odt', 'xls', 'xlsx', 'ppt', 'pptx'],
        'image': ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'],
        'video': ['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'],
        'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'],
        'archive': ['zip', 'rar', '7z', 'tar', 'gz']
    }
try:
    # Import from parent directory for main bot
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from database import save_temp_task_file, save_task_file, get_task_files, get_chat_files
except ImportError:
    try:
        # Import for chat bot running from chat_bot directory
        import sys
        import os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from database import save_temp_task_file, save_task_file, get_task_files, get_chat_files
    except ImportError:
        # Define fallback functions if database import fails
        def save_temp_task_file(*args, **kwargs):
            logger.warning("Database save_temp_task_file not available")
            return 1  # Return dummy ID
        def save_task_file(*args, **kwargs):
            logger.warning("Database save_task_file not available")
            return 1  # Return dummy ID
        def get_task_files(*args, **kwargs):
            logger.warning("Database get_task_files not available")
            return []
        def get_chat_files(*args, **kwargs):
            logger.warning("Database get_chat_files not available")
            return []

logger = logging.getLogger(__name__)

# Create files directory if it doesn't exist
FILES_DIR = "uploaded_files"
TASK_FILES_DIR = os.path.join(FILES_DIR, "tasks")
CHAT_FILES_DIR = os.path.join(FILES_DIR, "chats")

for directory in [FILES_DIR, TASK_FILES_DIR, CHAT_FILES_DIR]:
    os.makedirs(directory, exist_ok=True)

def get_file_extension(filename: str) -> str:
    """Get file extension from filename."""
    return os.path.splitext(filename.lower())[1]

def is_allowed_file_type(filename: str) -> bool:
    """Check if file type is allowed."""
    extension = get_file_extension(filename)
    return extension in ALLOWED_FILE_TYPES

def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes/(1024**2):.1f} MB"
    else:
        return f"{size_bytes/(1024**3):.1f} GB"

def generate_unique_filename(original_name: str) -> str:
    """Generate unique filename to prevent conflicts."""
    extension = get_file_extension(original_name)
    unique_id = str(uuid.uuid4())[:8]
    return f"{unique_id}_{original_name}"

async def download_telegram_file(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                file_obj: File, save_path: str) -> bool:
    """Download file from Telegram and save to local path."""
    try:
        await file_obj.download_to_drive(save_path)
        logger.info(f"File downloaded successfully: {save_path}")
        return True
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return False

async def handle_task_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                task_id: int = None) -> Optional[Dict]:
    """Handle file upload for task (during creation or to existing task)."""
    message = update.message
    user_id = message.from_user.id

    # Get file object from message
    file_obj = None
    original_name = None
    file_size = 0

    if message.document:
        file_obj = await message.document.get_file()
        original_name = message.document.file_name or "unknown_document"
        file_size = message.document.file_size or 0
    elif message.photo:
        file_obj = await message.photo[-1].get_file()  # Get highest resolution
        original_name = f"photo_{file_obj.file_unique_id}.jpg"
        file_size = message.photo[-1].file_size or 0
    elif message.video:
        file_obj = await message.video.get_file()
        original_name = f"video_{file_obj.file_unique_id}.mp4"
        file_size = message.video.file_size or 0
    elif message.audio:
        file_obj = await message.audio.get_file()
        original_name = message.audio.file_name or f"audio_{file_obj.file_unique_id}.mp3"
        file_size = message.audio.file_size or 0
    elif message.voice:
        file_obj = await message.voice.get_file()
        original_name = f"voice_{file_obj.file_unique_id}.ogg"
        file_size = message.voice.file_size or 0
    else:
        await message.reply_text("❌ Тип файлу не підтримується")
        return None

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        await message.reply_text(
            f"❌ Файл занадто великий ({size_mb:.1f} MB)\n"
            f"Максимальний розмір: {MAX_FILE_SIZE / (1024 * 1024):.0f} MB"
        )
        return None

    # Validate file type
    if not is_allowed_file_type(original_name):
        extension = get_file_extension(original_name)
        await message.reply_text(
            f"❌ Тип файлу не підтримується ({extension})\n"
            f"Дозволені типи: {', '.join(ALLOWED_FILE_TYPES[:10])}..."
        )
        return None

    # Generate unique filename and save path
    unique_filename = generate_unique_filename(original_name)
    file_path = os.path.join(TASK_FILES_DIR, unique_filename)

    # Download file
    if not await download_telegram_file(update, context, file_obj, file_path):
        await message.reply_text("❌ Помилка завантаження файлу")
        return None

    # Get actual file size
    actual_size = os.path.getsize(file_path)
    file_type = get_file_extension(original_name)

    # Save to database
    if task_id:
        # Save directly to task
        file_id = save_task_file(
            task_id=task_id,
            user_id=user_id,
            file_name=unique_filename,
            original_name=original_name,
            file_size=actual_size,
            file_path=file_path,
            file_type=file_type
        )
    else:
        # Save as temporary file during task creation
        file_id = save_temp_task_file(
            user_id=user_id,
            file_name=unique_filename,
            original_name=original_name,
            file_size=actual_size,
            file_path=file_path,
            file_type=file_type
        )

    if not file_id:
        # Clean up file if database save failed
        try:
            os.remove(file_path)
        except:
            pass
        await message.reply_text("❌ Помилка збереження файлу")
        return None

    file_info = {
        'id': file_id,
        'original_name': original_name,
        'file_name': unique_filename,
        'file_size': actual_size,
        'file_type': file_type,
        'file_path': file_path
    }

    return file_info

async def handle_chat_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                chat_code: str, sender_role: str) -> Optional[Dict]:
    """Handle file upload in chat."""
    message = update.message
    user_id = message.from_user.id

    # Get file object from message
    file_obj = None
    original_name = None
    file_size = 0

    if message.document:
        file_obj = await message.document.get_file()
        original_name = message.document.file_name or "unknown_document"
        file_size = message.document.file_size or 0
    elif message.photo:
        file_obj = await message.photo[-1].get_file()  # Get highest resolution
        original_name = f"photo_{file_obj.file_unique_id}.jpg"
        file_size = message.photo[-1].file_size or 0
    elif message.video:
        file_obj = await message.video.get_file()
        original_name = f"video_{file_obj.file_unique_id}.mp4"
        file_size = message.video.file_size or 0
    elif message.audio:
        file_obj = await message.audio.get_file()
        original_name = message.audio.file_name or f"audio_{file_obj.file_unique_id}.mp3"
        file_size = message.audio.file_size or 0
    elif message.voice:
        file_obj = await message.voice.get_file()
        original_name = f"voice_{file_obj.file_unique_id}.ogg"
        file_size = message.voice.file_size or 0
    else:
        return None

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        await message.reply_text(
            f"❌ Файл занадто великий ({size_mb:.1f} MB)\n"
            f"Максимальний розмір: {MAX_FILE_SIZE / (1024 * 1024):.0f} MB"
        )
        return None

    # Generate unique filename and save path
    unique_filename = generate_unique_filename(original_name)
    chat_dir = os.path.join(CHAT_FILES_DIR, chat_code)
    os.makedirs(chat_dir, exist_ok=True)
    file_path = os.path.join(chat_dir, unique_filename)

    # Download file
    if not await download_telegram_file(update, context, file_obj, file_path):
        return None

    # Get actual file size
    actual_size = os.path.getsize(file_path)

    file_info = {
        'original_name': original_name,
        'file_name': unique_filename,
        'file_size': actual_size,
        'file_size_formatted': format_file_size(actual_size),
        'file_path': file_path,
        'sender_role': sender_role
    }

    return file_info

def cleanup_temp_files(user_id: int):
    """Clean up temporary files for user."""
    from database import get_user_temp_files, delete_user_temp_files

    try:
        # Get temp files from database
        temp_files = get_user_temp_files(user_id)

        # Delete physical files
        for file_info in temp_files:
            file_path = file_info.get('file_path')
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted temp file: {file_path}")
                except Exception as e:
                    logger.error(f"Error deleting temp file {file_path}: {e}")

        # Delete from database
        delete_user_temp_files(user_id)
        logger.info(f"Cleaned up temp files for user {user_id}")

    except Exception as e:
        logger.error(f"Error cleaning up temp files for user {user_id}: {e}")

def get_file_icon(file_type: str) -> str:
    """Get emoji icon for file type."""
    file_icons = {
        '.pdf': '📄',
        '.doc': '📝', '.docx': '📝',
        '.txt': '📃', '.rtf': '📃',
        '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
        '.mp4': '🎬', '.avi': '🎬', '.mov': '🎬',
        '.mp3': '🎵', '.wav': '🎵',
        '.zip': '🗜️', '.rar': '🗜️', '.7z': '🗜️',
        '.py': '🐍', '.js': '📜', '.html': '🌐',
        '.xls': '📊', '.xlsx': '📊', '.csv': '📊',
        '.ppt': '📋', '.pptx': '📋'
    }
    return file_icons.get(file_type.lower(), '📎')

async def show_task_files(update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: int):
    """Show files attached to a task."""
    from database import get_task_files

    user_id = update.effective_user.id
    files = get_task_files(task_id)

    if not files:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Файлів не знайдено."
        )
        return

    for file in files:
        # Convert Row object to dict for safer access
        file_dict = dict(file)
        file_path = file_dict.get('file_path')
        original_name = file_dict.get('original_name', 'unknown_file')
        file_type = file_dict.get('file_type', '')
        file_name = file_dict.get('file_name', original_name)
        file_sent = False

        # Ensure all path components are strings
        possible_paths = []
        if file_path:
            possible_paths.append(str(file_path))

        # Add alternative paths
        if file_name:
            possible_paths.append(os.path.join(TASK_FILES_DIR, str(file_name)))
            possible_paths.append(os.path.join("uploaded_files", "tasks", str(file_name)))
        if original_name:
            possible_paths.append(os.path.join(TASK_FILES_DIR, str(original_name)))
            possible_paths.append(os.path.join("uploaded_files", "tasks", str(original_name)))

        # Add more comprehensive path options
        if file_name:
            possible_paths.append(os.path.join("uploaded_files", "tasks", str(file_name)))
            possible_paths.append(os.path.join("./uploaded_files/tasks", str(file_name)))
            possible_paths.append(str(file_name))
        if original_name:
            possible_paths.append(os.path.join("uploaded_files", "tasks", str(original_name)))
            possible_paths.append(os.path.join("./uploaded_files/tasks", str(original_name)))

        # Try to find the file in possible locations
        file_sent = False
        for path in possible_paths:
            if path and os.path.exists(path):
                try:
                    # Determine file type by extension if not set
                    if not file_type:
                        ext = os.path.splitext(str(original_name))[1].lower()
                        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                            file_type = 'image/'
                        elif ext in ['.mp4', '.avi', '.mkv', '.mov']:
                            file_type = 'video/'
                        else:
                            file_type = 'document'

                    # Send file based on type
                    if file_type.startswith('image/') or str(original_name).lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                        with open(path, 'rb') as f:
                            await context.bot.send_photo(
                                chat_id=user_id,
                                photo=f,
                                caption=f"📎 {original_name}\n💼 Файл завдання #{task_id}"
                            )
                    elif file_type.startswith('video/') or str(original_name).lower().endswith(('.mp4', '.avi', '.mkv', '.mov')):
                        with open(path, 'rb') as f:
                            await context.bot.send_video(
                                chat_id=user_id,
                                video=f,
                                caption=f"📎 {original_name}\n💼 Файл завдання #{task_id}"
                            )
                    else:
                        # Send as document
                        with open(path, 'rb') as f:
                            await context.bot.send_document(
                                chat_id=user_id,
                                document=f,
                                filename=str(original_name),
                                caption=f"📎 {original_name}\n💼 Файл завдання #{task_id}"
                            )
                    file_sent = True
                    logger.info(f"✅ File sent successfully: {original_name} from {path}")
                    break
                except Exception as e:
                    logger.error(f"Error sending file {original_name} from {path}: {e}")
                    continue

        if not file_sent:
            logger.error(f"❌ File not found in any location: {original_name}")
            logger.error(f"   Tried paths: {[p for p in possible_paths if p]}")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Файл не знайдено: {original_name}"
            )

async def show_chat_files(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_code: str):
    """Show files attached to a chat."""
    from database import get_chat_files

    user_id = update.effective_user.id
    files = get_chat_files(chat_code)

    if not files:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Файлів не знайдено."
        )
        return

    for file in files:
        # Convert Row object to dict for safer access
        file_dict = dict(file)
        file_path = file_dict.get('file_path')
        original_name = file_dict.get('original_name', 'unknown_file')
        file_type = file_dict.get('file_type', '')
        file_name = file_dict.get('file_name', original_name)
        file_sent = False

        # Ensure all path components are strings
        possible_paths = []
        if file_path:
            possible_paths.append(str(file_path))

        # Try to find the file in possible locations
        file_sent = False
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    # Determine file type by extension if not set
                    if not file_type:
                        ext = os.path.splitext(str(original_name))[1].lower()
                        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                            file_type = 'image/'
                        elif ext in ['.mp4', '.avi', '.mkv', '.mov']:
                            file_type = 'video/'
                        else:
                            file_type = 'document'

                    # Send file based on type
                    if file_type.startswith('image/') or str(original_name).lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
                        with open(path, 'rb') as f:
                            await context.bot.send_photo(
                                chat_id=user_id,
                                photo=f,
                                caption=f"📎 {original_name}\n💼 Файл завдання"
                            )
                    elif file_type.startswith('video/') or str(original_name).lower().endswith(('.mp4', '.avi', '.mkv', '.mov')):
                        with open(path, 'rb') as f:
                            await context.bot.send_video(
                                chat_id=user_id,
                                video=f,
                                caption=f"📎 {original_name}\n💼 Файл завдання"
                            )
                    else:
                        # Send as document
                        with open(path, 'rb') as f:
                            await context.bot.send_document(
                                chat_id=user_id,
                                document=f,
                                filename=str(original_name),
                                caption=f"📎 {original_name}\n💼 Файл завдання"
                            )
                    file_sent = True
                    break
                except Exception as e:
                    logger.error(f"Error sending file {original_name} from {path}: {e}")
                    continue

        if not file_sent:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Файл не знайдено: {original_name}"
            )
            logger.error(f"File not found in any location: {original_name}, tried paths: {possible_paths}")