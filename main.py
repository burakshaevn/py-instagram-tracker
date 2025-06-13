import sys
from instagram_tracker.strategies import InstagrapiStrategy
from instagram_tracker.observers import ConsoleProgressObserver
from instagram_tracker.analyzer import InstagramAnalyzer
from config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD

def main():
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("Error: Please set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD in .env file")
        sys.exit(1)
    
    # Create strategy and observer
    strategy = InstagrapiStrategy()
    observer = ConsoleProgressObserver()
    
    # Create analyzer and add observer
    analyzer = InstagramAnalyzer(strategy)
    analyzer.add_observer(observer)
    
    # Login to Instagram
    if not analyzer.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD):
        print("Failed to login. Please check your credentials.")
        sys.exit(1)
    
    # Find non-followers
    non_followers = analyzer.find_non_followers(INSTAGRAM_USERNAME)
    
    # Print results
    print("\nUsers who don't follow you back:")
    for username in sorted(non_followers):
        print(f"- {username}")

if __name__ == "__main__":
    main() 