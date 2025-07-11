"""
Configuration for Chat Bot
"""

import os

# Database path (relative to parent directory)
DATABASE_PATH = "../rozdum.db"

# File upload settings
UPLOAD_FOLDER = "uploaded_files"
MAX_FILE_SIZE = 150 * 1024 * 1024  # 150 MB
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx',
    'zip', 'rar', '7z', 'py', 'js', 'html', 'css', 'json'
}

# Chat settings
CHAT_CODE_LENGTH = 6
CHAT_EXPIRY_HOURS = 24

# Default rating for new users
DEFAULT_RATING = 5.0

# Admin settings from environment only
admin_id_str = os.getenv("ADMIN_ID")
if admin_id_str:
    try:
        ADMIN_ID = int(admin_id_str)
    except ValueError:
        ADMIN_ID = 5857065034  # Default to @fezerstop
else:
    ADMIN_ID = 5857065034  # Default to @fezerstop