import sys
import argparse
from instagram_tracker.strategies import InstagrapiStrategy
from instagram_tracker.observers import ConsoleProgressObserver
from instagram_tracker.analyzer import InstagramAnalyzer
from config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Find Instagram users who don\'t follow back')
    parser.add_argument('username', nargs='?', default=INSTAGRAM_USERNAME,
                      help='Instagram username to check (default: your own username)')
    args = parser.parse_args()

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
    target_username = args.username
    print(f"\nAnalyzing followers for user: {target_username}")
    non_followers = analyzer.find_non_followers(target_username)
    
    # Print results
    print(f"\nUsers who don't follow {target_username} back:")
    if non_followers:
        for username in sorted(non_followers):
            print(f"- {username}")
        print(f"\nTotal: {len(non_followers)} users don't follow back")
    else:
        print("No users found who don't follow back")

if __name__ == "__main__":
    main() 