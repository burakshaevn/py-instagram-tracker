from typing import Set
from .interfaces import InstagramDataStrategy, ProgressObserver

class InstagramAnalyzer:
    """Main class for analyzing Instagram relationships"""
    
    def __init__(self, strategy: InstagramDataStrategy):
        self.strategy = strategy
        if hasattr(strategy, 'attach'):
            self.progress_subject = strategy
        else:
            self.progress_subject = None
    
    def add_observer(self, observer: ProgressObserver):
        """Add an observer for progress updates"""
        if self.progress_subject:
            self.progress_subject.attach(observer)
    
    def login(self, username: str, password: str) -> bool:
        """Login to Instagram"""
        return self.strategy.login(username, password)
    
    def find_non_followers(self, username: str) -> Set[str]:
        """Find users who don't follow back"""
        followers = self.strategy.get_followers(username)
        following = self.strategy.get_following(username)
        
        non_followers = following - followers
        
        if self.progress_subject:
            self.progress_subject.notify(
                f"Анализ завершен, найдено {len(non_followers)} пользователей, которые не подписаны в ответ."
            )
        
        return non_followers 