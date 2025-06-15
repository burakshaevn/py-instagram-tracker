import json
import os
from datetime import datetime
from typing import Dict, Set, Optional, List

class InstagramDataManager:
    """Класс для управления данными Instagram"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
    
    def _get_filename(self, username: str, timestamp: Optional[datetime] = None) -> str:
        """Генерирует имя файла для пользователя с временной меткой"""
        if timestamp is None:
            timestamp = datetime.now()
        # Формат: username_DD_MM_YYYY_HH_MM.json
        timestamp_str = timestamp.strftime("%d_%m_%Y_%H_%M")
        return os.path.join(self.data_dir, f"{username}_{timestamp_str}.json")
    
    def save_data(self, username: str, followers: Set[str], following: Set[str]) -> str:
        """Сохраняет данные в JSON файл и возвращает имя файла"""
        data = {
            "username": username,
            "timestamp": datetime.now().strftime("%d_%m_%Y_%H_%M"),
            "followers": sorted(list(followers)),
            "following": sorted(list(following)),
            "stats": {
                "followers_count": len(followers),
                "following_count": len(following)
            }
        }
        
        filename = self._get_filename(username)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filename
    
    def get_available_files(self, username: str) -> List[Dict]:
        """Возвращает список доступных файлов с данными для пользователя"""
        files = []
        for filename in os.listdir(self.data_dir):
            if filename.startswith(f"{username}_") and filename.endswith(".json"):
                file_path = os.path.join(self.data_dir, filename)
                timestamp = datetime.fromtimestamp(os.path.getmtime(file_path))
                files.append({
                    "filename": filename,
                    "path": file_path,
                    "timestamp": timestamp,
                    "display_name": timestamp.strftime("%Y-%m-%d %H:%M")
                })
        return sorted(files, key=lambda x: x["timestamp"], reverse=True)
    
    def load_data(self, file_path: str) -> Optional[Dict]:
        """Загружает данные из JSON файла"""
        if not os.path.exists(file_path):
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Конвертируем списки обратно в множества
            data['followers'] = set(data['followers'])
            data['following'] = set(data['following'])
            return data
    
    def compare_data(self, old_data: Dict, new_followers: Set[str], new_following: Set[str]) -> Dict:
        """Сравнивает старые и новые данные"""
        old_followers = set(old_data['followers'])
        old_following = set(old_data['following'])
        
        # Находим новых подписчиков
        new_followers_added = new_followers - old_followers
        # Находим отписавшихся
        new_followers_removed = old_followers - new_followers
        # Находим новые подписки
        new_following_added = new_following - old_following
        # Находим отписанных
        new_following_removed = old_following - new_following
        
        return {
            "new_followers": sorted(list(new_followers_added)),
            "unfollowers": sorted(list(new_followers_removed)),
            "new_following": sorted(list(new_following_added)),
            "unfollowed": sorted(list(new_following_removed)),
            "timestamp": datetime.now().strftime("%d_%m_%Y_%H_%M"),
            "compared_with": old_data['timestamp']
        }
    
    def save_comparison(self, username: str, comparison_data: Dict) -> str:
        """Сохраняет результаты сравнения в отдельный файл"""
        timestamp = datetime.now()
        filename = os.path.join(self.data_dir, f"{username}_comparison_{timestamp.strftime('%Y-%m-%d_%H-%M')}.json")
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(comparison_data, f, ensure_ascii=False, indent=2)
        return filename 