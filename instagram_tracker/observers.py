from .interfaces import ProgressObserver

class ConsoleProgressObserver(ProgressObserver):
    """Concrete observer that displays progress in the console"""
    
    def update_progress(self, message: str, percentage: float = None):
        if percentage is not None:
            print(f"{message} - {percentage:.1f}%")
        else:
            print(message) 