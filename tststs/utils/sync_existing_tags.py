
"""
Script to synchronize existing tags with translation system
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db_connection, update_user
from utils.tag_translator import ENGLISH_TO_UKRAINIAN, translate_tags_to_ukrainian
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_existing_user_tags():
    """Synchronize existing user tags with translation system."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT user_id, executor_tags FROM users 
            WHERE executor_tags IS NOT NULL AND executor_tags != '' AND executor_tags != '{}'
        """)
        
        users = cursor.fetchall()
        updated_count = 0
        
        for user_id, executor_tags_str in users:
            try:
                executor_tags = json.loads(executor_tags_str)
                
                if not isinstance(executor_tags, dict):
                    continue
                
                updated_tags = {}
                changes_made = False
                
                for category, tags in executor_tags.items():
                    if not isinstance(tags, list):
                        continue
                        
                    updated_category_tags = []
                    
                    for tag in tags:
                        # If tag is English and has Ukrainian translation, add both
                        if tag.lower() in ENGLISH_TO_UKRAINIAN:
                            ukrainian_tag = ENGLISH_TO_UKRAINIAN[tag.lower()]
                            if ukrainian_tag not in updated_category_tags:
                                updated_category_tags.append(ukrainian_tag)
                            if tag not in updated_category_tags:
                                updated_category_tags.append(tag)
                            changes_made = True
                        else:
                            # Keep existing tag
                            if tag not in updated_category_tags:
                                updated_category_tags.append(tag)
                    
                    updated_tags[category] = updated_category_tags
                
                if changes_made:
                    update_user(user_id, executor_tags=updated_tags)
                    logger.info(f"Updated tags for user {user_id}")
                    updated_count += 1
                
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error processing tags for user {user_id}: {e}")
                continue
        
        logger.info(f"✅ Updated tags for {updated_count} users")
        
    except Exception as e:
        logger.error(f"Error syncing user tags: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    sync_existing_user_tags()
