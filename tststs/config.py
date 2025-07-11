"""
Rozdum Bot Configuration

Цей файл містить всі основні налаштування для роботи Rozdum Bot:
- Категорії та теги
- Бізнес-логіка (мінімальні ціни, комісії, VIP-параметри)
- Обмеження для файлів
- Стани користувача для FSM
- Шлях до бази даних

Всі секретні ключі та токени мають зберігатися у .env файлі!
"""

import os

# Bot configuration
# BOT_TOKEN moved to environment variables only
# ADMIN_ID will be read directly from environment in each bot
# No default hardcoded value

# Database configuration
DATABASE_PATH = "rozdum.db"
DEFAULT_RATING = 5.0

# Business logic configuration
MINIMUM_TASK_PRICE = 25.0  # UAH
VIP_TASK_PRICE_LOW = 10.0  # UAH for tasks up to 100 UAH
VIP_TASK_PRICE_HIGH = 15.0  # UAH for tasks above 100 UAH
VIP_TASK_THRESHOLD = 100.0  # UAH threshold for VIP pricing
PLATFORM_COMMISSION_RATE = 0.10  # 10% paid by executor
VIP_EXECUTOR_MIN_RATING = 4.0
DEFAULT_RATING = 5.0
TASK_ACCEPTANCE_TIMEOUT = 600  # 10 minutes in seconds

# Categories configuration with Ukrainian translations
CATEGORIES = {
    'presentations': {
        'name': '🎨 Презентації',
        'tags': ['дизайн', 'powerpoint', 'keynote', 'інфографіка', 'бізнес-презентації', 'слайди', 'оформлення']
    },
    'programming': {
        'name': '💻 Програмування',
        'tags': ['python', 'javascript', 'react', 'django', 'fastapi', 'postgresql', 'бази-даних', 'веб-розробка', 'автоматизація', 'api', 'фронтенд', 'бекенд']
    },
    'texts': {
        'name': '📝 Тексти',
        'tags': ['академічні-тексти', 'креативні-тексти', 'технічні-тексти', 'статті', 'есе', 'копірайтинг', 'переклади', 'редагування']
    },
    'consulting': {
        'name': '💼 Консалтинг',
        'tags': ['бізнес-стратегія', 'технічні-консультації', 'маркетинг', 'фінанси', 'управління-проектами', 'аналітика']
    },
    'design': {
        'name': '🎨 Дизайн',
        'tags': ['графічний-дизайн', 'веб-дизайн', 'логотипи', 'брендинг', 'ui-ux', 'ілюстрації', 'баннери']
    },
    'video': {
        'name': '🎬 Відео',
        'tags': ['монтаж-відео', 'анімація', 'озвучка', 'відеореклама', 'youtube', 'motion-graphics']
    }
}

# User states for conversation handling
class UserStates:
    NONE = 0
    CREATING_TASK_CATEGORY = 1
    CREATING_TASK_TAGS = 2
    CREATING_TASK_DESCRIPTION = 3
    CREATING_TASK_FILES = 4  # New state for file upload
    CREATING_TASK_PRICE = 5
    CREATING_TASK_VIP = 6
    CREATING_TASK_CONFIRM = 7
    SETTING_EXECUTOR_TAGS = 8
    ADDING_BALANCE = 9
    WITHDRAWING_BALANCE = 10

# Admin configuration - read from environment
ADMIN_ID = None  # Will be read from environment in each bot

# File upload configuration
MAX_FILE_SIZE = 150 * 1024 * 1024  # 150 MB in bytes
ALLOWED_FILE_TYPES = [
    # Documents
    '.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt',
    # Images
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp',
    # Archives
    '.zip', '.rar', '.7z', '.tar', '.gz',
    # Code
    '.py', '.js', '.html', '.css', '.sql', '.json', '.xml',
    # Spreadsheets
    '.xls', '.xlsx', '.csv', '.ods',
    # Presentations
    '.ppt', '.pptx', '.odp',
    # Audio/Video
    '.mp3', '.wav', '.mp4', '.avi', '.mov', '.mkv',
    # Other
    '.ai', '.psd', '.sketch', '.fig'
]