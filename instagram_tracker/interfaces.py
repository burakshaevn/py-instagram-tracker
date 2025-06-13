from abc import ABC, abstractmethod
from typing import Set, List

class InstagramDataStrategy(ABC):
    """Strategy interface for different methods of retrieving Instagram data"""
    
    @abstractmethod
    def login(self, username: str, password: str) -> bool:
        """Login to Instagram"""
        pass
    
    @abstractmethod
    def get_followers(self, username: str) -> Set[str]:
        """Get set of followers"""
        pass
    
    @abstractmethod
    def get_following(self, username: str) -> Set[str]:
        """Get set of users being followed"""
        pass

class ProgressObserver(ABC):
    """Observer interface for progress updates"""
    
    @abstractmethod
    def update_progress(self, message: str, percentage: float = None):
        """Update progress status"""
        pass

class ProgressSubject(ABC):
    """Subject interface for the Observer pattern"""
    
    def __init__(self):
        self._observers: List[ProgressObserver] = []
    
    def attach(self, observer: ProgressObserver):
        if observer not in self._observers:
            self._observers.append(observer)
    
    def detach(self, observer: ProgressObserver):
        self._observers.remove(observer)
    
    def notify(self, message: str, percentage: float = None):
        for observer in self._observers:
            observer.update_progress(message, percentage) 