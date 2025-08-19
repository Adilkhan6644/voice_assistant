import logging
import json
from datetime import datetime
import os

class ChatLogger:
    def __init__(self, log_dir="chat_logs"):
        self.log_dir = log_dir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        self.current_session = None
        self.current_log_file = None
        
    def start_session(self):
        """Start a new chat session with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_session = timestamp
        self.current_log_file = os.path.join(self.log_dir, f"chat_session_{timestamp}.json")
        self.log_event("system", "Chat session started")
        
    def log_event(self, source: str, message: str):
        """Log a chat event with timestamp"""
        if not self.current_session:
            self.start_session()
            
        event = {
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "message": message
        }
        
        with open(self.current_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + "\n")
