
"""
Chat Bot Log Analyzer
Utility for analyzing chat bot logs and generating reports
"""

import json
import re
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import os

class ChatLogAnalyzer:
    def __init__(self, log_dir="chat_bot"):
        self.log_dir = log_dir
        self.chat_events_log = os.path.join(log_dir, "chat_events.log")
        self.security_log = os.path.join(log_dir, "security.log")
        self.main_log = os.path.join(log_dir, "chat_bot.log")
    
    def parse_chat_events(self, hours_back=24):
        """Parse chat events from the last N hours"""
        events = []
        if not os.path.exists(self.chat_events_log):
            return events
        
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        with open(self.chat_events_log, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    if 'CHAT_EVENT:' in line:
                        # Extract JSON part
                        json_part = line.split('CHAT_EVENT: ')[1].strip()
                        event_data = json.loads(json_part)
                        event_time = datetime.fromisoformat(event_data['timestamp'])
                        
                        if event_time >= cutoff_time:
                            events.append(event_data)
                except Exception as e:
                    continue
        
        return events
    
    def parse_security_events(self, hours_back=24):
        """Parse security events from the last N hours"""
        events = []
        if not os.path.exists(self.security_log):
            return events
        
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        with open(self.security_log, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    if 'SECURITY_EVENT:' in line:
                        json_part = line.split('SECURITY_EVENT: ')[1].strip()
                        event_data = json.loads(json_part)
                        event_time = datetime.fromisoformat(event_data['timestamp'])
                        
                        if event_time >= cutoff_time:
                            events.append(event_data)
                except Exception as e:
                    continue
        
        return events
    
    def generate_activity_report(self, hours_back=24):
        """Generate activity report"""
        chat_events = self.parse_chat_events(hours_back)
        security_events = self.parse_security_events(hours_back)
        
        # Statistics
        event_counts = Counter([event['event'] for event in chat_events])
        security_counts = Counter([event['event'] for event in security_events])
        
        # Active users
        active_users = set(event['user_id'] for event in chat_events if event['user_id'] != 0)
        
        # Active chats
        active_chats = set(event['chat_code'] for event in chat_events if event.get('chat_code'))
        
        # Messages per hour
        messages_by_hour = defaultdict(int)
        for event in chat_events:
            if event['event'] == 'MESSAGE_SAVED':
                hour = datetime.fromisoformat(event['timestamp']).hour
                messages_by_hour[hour] += 1
        
        report = f"""
📊 ЗВІТ ПО АКТИВНОСТІ ЧАТ БОТА ({hours_back} годин)
{'='*50}

📈 ЗАГАЛЬНА СТАТИСТИКА:
• Активних користувачів: {len(active_users)}
• Активних чатів: {len(active_chats)}
• Всього подій: {len(chat_events)}
• Проблем безпеки: {len(security_events)}

📋 ПОДІЇ ЧАТУ:
"""
        
        for event_type, count in event_counts.most_common(10):
            report += f"• {event_type}: {count}\n"
        
        if security_events:
            report += f"\n🚨 ПОДІЇ БЕЗПЕКИ:\n"
            for event_type, count in security_counts.most_common():
                report += f"• {event_type}: {count}\n"
        
        if messages_by_hour:
            report += f"\n📬 ПОВІДОМЛЕННЯ ПО ГОДИНАХ:\n"
            for hour in sorted(messages_by_hour.keys()):
                report += f"• {hour:02d}:00 - {messages_by_hour[hour]} повідомлень\n"
        
        return report
    
    def get_chat_statistics(self, chat_code: str):
        """Get statistics for specific chat"""
        chat_events = self.parse_chat_events(hours_back=24*7)  # Last week
        chat_events = [e for e in chat_events if e.get('chat_code') == chat_code]
        
        if not chat_events:
            return f"Немає даних для чату {chat_code}"
        
        # Statistics
        event_counts = Counter([event['event'] for event in chat_events])
        participants = set(event['user_id'] for event in chat_events if event['user_id'] != 0)
        
        messages = [e for e in chat_events if e['event'] == 'MESSAGE_SAVED']
        total_messages = len(messages)
        
        customer_messages = len([m for m in messages if m['details'].get('sender_role') == 'customer'])
        executor_messages = len([m for m in messages if m['details'].get('sender_role') == 'executor'])
        
        report = f"""
📊 СТАТИСТИКА ЧАТУ {chat_code}
{'='*30}

👥 Учасники: {len(participants)}
💬 Всього повідомлень: {total_messages}
🛒 Повідомлень замовника: {customer_messages}
⚡ Повідомлень виконавця: {executor_messages}

📋 ПОДІЇ:
"""
        
        for event_type, count in event_counts.most_common():
            report += f"• {event_type}: {count}\n"
        
        return report

def main():
    """Run log analyzer"""
    analyzer = ChatLogAnalyzer()
    
    print("📊 АНАЛІЗ ЛОГІВ ЧАТ БОТА")
    print("=" * 40)
    
    # Generate reports
    print("\n1. Звіт за останні 24 години:")
    print(analyzer.generate_activity_report(24))
    
    print("\n2. Звіт за останні 7 днів:")
    print(analyzer.generate_activity_report(24*7))
    
    # Save reports
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"chat_bot_report_{timestamp}.txt"
    
    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(analyzer.generate_activity_report(24*7))
    
    print(f"\n📄 Звіт збережено: {report_filename}")

if __name__ == "__main__":
    main()
