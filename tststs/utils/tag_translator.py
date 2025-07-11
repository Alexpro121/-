
"""
Tag translation system for language compatibility
"""

import logging

logger = logging.getLogger(__name__)

# Translation mapping from English to Ukrainian
ENGLISH_TO_UKRAINIAN = {
    'design': 'дизайн',
    'powerpoint': 'powerpoint',
    'keynote': 'keynote',
    'business': 'бізнес-презентації',
    'infographics': 'інфографіка',
    'slides': 'слайди',
    'presentation': 'оформлення',
    
    # Programming tags
    'python': 'python',
    'javascript': 'javascript',
    'react': 'react',
    'django': 'django',
    'fastapi': 'fastapi',
    'postgresql': 'postgresql',
    'database': 'бази-даних',
    'web-development': 'веб-розробка',
    'automation': 'автоматизація',
    'api': 'api',
    'frontend': 'фронтенд',
    'backend': 'бекенд',
    
    # Text tags
    'academic-texts': 'академічні-тексти',
    'creative-texts': 'креативні-тексти',
    'technical-texts': 'технічні-тексти',
    'articles': 'статті',
    'essays': 'есе',
    'copywriting': 'копірайтинг',
    'translations': 'переклади',
    'editing': 'редагування',
    
    # Consulting tags
    'business-strategy': 'бізнес-стратегія',
    'technical-consulting': 'технічні-консультації',
    'marketing': 'маркетинг',
    'finance': 'фінанси',
    'project-management': 'управління-проектами',
    'analytics': 'аналітика',
    
    # Design tags
    'graphic-design': 'графічний-дизайн',
    'web-design': 'веб-дизайн',
    'logos': 'логотипи',
    'branding': 'брендинг',
    'ui-ux': 'ui-ux',
    'illustrations': 'ілюстрації',
    'banners': 'баннери',
    
    # Video tags
    'video-editing': 'монтаж-відео',
    'animation': 'анімація',
    'voice-over': 'озвучка',
    'video-ads': 'відеореклама',
    'youtube': 'youtube',
    'motion-graphics': 'motion-graphics'
}

# Reverse mapping from Ukrainian to English
UKRAINIAN_TO_ENGLISH = {v: k for k, v in ENGLISH_TO_UKRAINIAN.items()}

def translate_tags_to_ukrainian(english_tags):
    """Translate English tags to Ukrainian."""
    ukrainian_tags = []
    for tag in english_tags:
        ukrainian_tag = ENGLISH_TO_UKRAINIAN.get(tag.lower(), tag)
        ukrainian_tags.append(ukrainian_tag)
        if tag.lower() in ENGLISH_TO_UKRAINIAN:
            logger.info(f"Translated tag: '{tag}' -> '{ukrainian_tag}'")
    return ukrainian_tags

def translate_tags_to_english(ukrainian_tags):
    """Translate Ukrainian tags to English."""
    english_tags = []
    for tag in ukrainian_tags:
        english_tag = UKRAINIAN_TO_ENGLISH.get(tag.lower(), tag)
        english_tags.append(english_tag)
        if tag.lower() in UKRAINIAN_TO_ENGLISH:
            logger.info(f"Translated tag: '{tag}' -> '{english_tag}'")
    return english_tags

def normalize_tags_for_matching(task_tags, executor_tags):
    """
    Normalize tags for matching by ensuring both are in the same language.
    Returns normalized task_tags and executor_tags for comparison.
    """
    # Convert task tags to both languages for flexible matching
    task_tags_set = set(task_tags)
    
    # Add Ukrainian translations of English task tags
    for tag in task_tags:
        if tag.lower() in ENGLISH_TO_UKRAINIAN:
            task_tags_set.add(ENGLISH_TO_UKRAINIAN[tag.lower()])
    
    # Add English translations of Ukrainian task tags
    for tag in task_tags:
        if tag.lower() in UKRAINIAN_TO_ENGLISH:
            task_tags_set.add(UKRAINIAN_TO_ENGLISH[tag.lower()])
    
    # Convert executor tags to both languages for flexible matching
    executor_tags_set = set(executor_tags)
    
    # Add Ukrainian translations of English executor tags
    for tag in executor_tags:
        if tag.lower() in ENGLISH_TO_UKRAINIAN:
            executor_tags_set.add(ENGLISH_TO_UKRAINIAN[tag.lower()])
    
    # Add English translations of Ukrainian executor tags
    for tag in executor_tags:
        if tag.lower() in UKRAINIAN_TO_ENGLISH:
            executor_tags_set.add(UKRAINIAN_TO_ENGLISH[tag.lower()])
    
    logger.debug(f"Normalized task tags: {task_tags_set}")
    logger.debug(f"Normalized executor tags: {executor_tags_set}")
    
    return list(task_tags_set), list(executor_tags_set)

def find_matching_tags(task_tags, executor_tags):
    """
    Find matching tags between task and executor with language flexibility.
    """
    normalized_task_tags, normalized_executor_tags = normalize_tags_for_matching(task_tags, executor_tags)
    
    task_set = set(normalized_task_tags)
    executor_set = set(normalized_executor_tags)
    
    matching_tags = task_set & executor_set
    
    logger.info(f"Original task tags: {task_tags}")
    logger.info(f"Original executor tags: {executor_tags}")
    logger.info(f"Matching tags found: {list(matching_tags)}")
    
    return list(matching_tags)
