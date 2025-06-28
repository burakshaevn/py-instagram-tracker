import time
import asyncio
from typing import Set
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError
from .interfaces import InstagramDataStrategy, ProgressSubject
from config import DELAY_BETWEEN_REQUESTS, MAX_RETRIES, RETRY_DELAY

class InstagrapiStrategy(InstagramDataStrategy, ProgressSubject):
    """Concrete strategy using instagrapi library"""
    
    def __init__(self):
        super().__init__()
        self.client = Client()
        self.client.delay_range = [0.5, 1.5]   
    
    def login(self, username: str, password: str) -> bool:
        try:
            self.notify("Вход в Instagram...")
            
            # Попытка входа
            try:
                self.client.login(username, password)
                self.notify("Успешный вход!")
                return True
            except Exception as e:
                error_msg = str(e).lower()
                
                # Если требуется 2FA
                if "two-factor authentication" in error_msg or "verification_code" in error_msg:
                    self.notify("Требуется код двухфакторной аутентификации...")
                    code = input("Введите 6-значный код из приложения 2FA: ")
                    
                    try:
                        self.client.login(username, password, verification_code=code)
                        self.notify("Успешный вход с 2FA!")
                        return True
                    except Exception as twofa_error:
                        self.notify(f"Ошибка 2FA: {str(twofa_error)}")
                        return False
                
                # Если требуется подтверждение устройства
                elif "challenge" in error_msg or "verification" in error_msg:
                    self.notify("Требуется подтверждение устройства...")
                    code = input("Введите код подтверждения (3 или 6 цифр): ")
                    
                    try:
                        # Пытаемся обработать challenge
                        if hasattr(self.client, 'challenge_code_handler'):
                            self.client.challenge_code_handler(code)
                        else:
                            # Альтернативный способ
                            self.client.login(username, password, verification_code=code)
                        self.notify("Подтверждение успешно!")
                        return True
                    except Exception as confirm_error:
                        self.notify(f"Ошибка подтверждения: {str(confirm_error)}")
                        return False
                
                else:
                    self.notify(f"Ошибка входа: {str(e)}")
                    return False
                
        except Exception as e:
            self.notify(f"Ошибка входа: {str(e)}")
            return False
    
    def _handle_rate_limit(self, retry_count: int) -> bool:
        """Handle rate limiting by waiting and retrying"""
        if retry_count >= MAX_RETRIES:
            self.notify("Достигнуто максимальное количество повторных попыток. Пожалуйста, повторите попытку позже.")
            return False
        
        wait_time = RETRY_DELAY * (retry_count + 1)
        self.notify(f"Скорость ограничена. Подождите {wait_time} секунды перед повторной попыткой...")
        time.sleep(wait_time)
        return True

    async def _process_users_batch(self, users_data, batch_size=50):
        """Process users in batches"""
        usernames = set()
        total = len(users_data)
        current = 0
        
        # Разбиваем на батчи для параллельной обработки
        for i in range(0, total, batch_size):
            batch = list(users_data.values())[i:i + batch_size]
            for user in batch:
                usernames.add(user.username)
                current += 1
                if current % 10 == 0:  # Увеличили интервал обновления для уменьшения вывода
                    percentage = (current / total) * 100 if total > 0 else 0
                    self.notify(f"Обработано {current} пользователей из {total}.", percentage)
            await asyncio.sleep(0.1)  # Небольшая пауза между батчами
        
        return usernames
    
    def get_followers(self, username: str) -> Set[str]:
        self.notify("Извлекаем пользователей...")
        followers = set()
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                user_id = self.client.user_id_from_username(username)
                followers_data = self.client.user_followers(user_id)
                
                # Используем асинхронную обработку
                followers = asyncio.run(self._process_users_batch(followers_data))
                return followers
                
            except ClientError as e:
                if "rate limit" in str(e).lower():
                    if not self._handle_rate_limit(retry_count):
                        break
                    retry_count += 1
                    continue
                self.notify(f"Client error: {str(e)}")
                break
            except Exception as e:
                self.notify(f"Error fetching followers: {str(e)}")
                break
        
        return followers
    
    def get_following(self, username: str) -> Set[str]:
        self.notify("Извлекаем пользователей...")
        following = set()
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                user_id = self.client.user_id_from_username(username)
                following_data = self.client.user_following(user_id)
                
                # Используем асинхронную обработку
                following = asyncio.run(self._process_users_batch(following_data))
                return following
                
            except ClientError as e:
                if "rate limit" in str(e).lower():
                    if not self._handle_rate_limit(retry_count):
                        break
                    retry_count += 1
                    continue
                self.notify(f"Client error: {str(e)}")
                break
            except Exception as e:
                self.notify(f"Error fetching following: {str(e)}")
                break
        
        return following 