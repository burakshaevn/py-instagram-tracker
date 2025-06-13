import time
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
        self.client.delay_range = [1, 3]  # Random delay between requests
    
    def login(self, username: str, password: str) -> bool:
        try:
            self.notify("Logging in to Instagram...")
            self.client.login(username, password)
            self.notify("Successfully logged in!")
            return True
        except Exception as e:
            self.notify(f"Login failed: {str(e)}")
            return False
    
    def _handle_rate_limit(self, retry_count: int) -> bool:
        """Handle rate limiting by waiting and retrying"""
        if retry_count >= MAX_RETRIES:
            self.notify("Maximum retry attempts reached. Please try again later.")
            return False
        
        wait_time = RETRY_DELAY * (retry_count + 1)
        self.notify(f"Rate limited. Waiting {wait_time} seconds before retrying...")
        time.sleep(wait_time)
        return True
    
    def get_followers(self, username: str) -> Set[str]:
        self.notify("Fetching followers...")
        followers = set()
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                user_id = self.client.user_id_from_username(username)
                followers_data = self.client.user_followers(user_id)
                total = len(followers_data)
                current = 0
                
                for follower in followers_data.values():
                    followers.add(follower.username)
                    current += 1
                    if current % 5 == 0:
                        percentage = (current / total) * 100 if total > 0 else 0
                        self.notify(f"Processed {current}/{total} followers", percentage)
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                
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
        self.notify("Fetching following...")
        following = set()
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                user_id = self.client.user_id_from_username(username)
                following_data = self.client.user_following(user_id)
                total = len(following_data)
                current = 0
                
                for followee in following_data.values():
                    following.add(followee.username)
                    current += 1
                    if current % 5 == 0:
                        percentage = (current / total) * 100 if total > 0 else 0
                        self.notify(f"Processed {current}/{total} following", percentage)
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                
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