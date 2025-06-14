import os
import sys
import asyncio
import argparse
from datetime import datetime
from dotenv import load_dotenv
from instagram_tracker.strategies import InstagrapiStrategy
from instagram_tracker.observers import ConsoleObserver
from instagram_tracker.analyzer import InstagramAnalyzer
from instagram_tracker.data_manager import InstagramDataManager
from config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD

def print_comparison_results(comparison_data: dict):
    """Выводит результаты сравнения"""
    print("\n=== Результаты сравнения ===")
    print(f"Сравнение с данными от: {comparison_data['compared_with']}")
    
    if comparison_data["new_followers"]:
        print("\nНовые подписчики:")
        for username in comparison_data["new_followers"]:
            print(f"+ {username}")
    
    if comparison_data["unfollowers"]:
        print("\nОтписались:")
        for username in comparison_data["unfollowers"]:
            print(f"- {username}")
    
    if comparison_data["new_following"]:
        print("\nНовые подписки:")
        for username in comparison_data["new_following"]:
            print(f"+ {username}")
    
    if comparison_data["unfollowed"]:
        print("\nОтписались от вас:")
        for username in comparison_data["unfollowed"]:
            print(f"- {username}")
    
    print(f"\nВремя сравнения: {comparison_data['timestamp']}")

def main():
    parser = argparse.ArgumentParser(description='Instagram Non-Followers Tracker')
    parser.add_argument('username', nargs='?', help='Instagram username to check')
    parser.add_argument('--save', action='store_true', help='Save results to JSON file')
    parser.add_argument('--compare', nargs='?', const=True, metavar='FILE', help='Compare with previous data from file')
    args = parser.parse_args()

    # Load environment variables
    load_dotenv()
    
    # Get credentials from environment variables
    username = os.getenv('INSTAGRAM_USERNAME')
    password = os.getenv('INSTAGRAM_PASSWORD')
    
    if not username or not password:
        print("Error: INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD must be set in .env file")
        sys.exit(1)
    
    # Get target username from command line or use the authenticated user
    target_username = args.username or username
    
    # Create strategy and observer
    strategy = InstagrapiStrategy(username, password)
    observer = ConsoleObserver()
    strategy.add_observer(observer)
    
    # Create analyzer
    analyzer = InstagramAnalyzer(strategy)
    
    # Create data manager
    data_manager = InstagramDataManager()
    
    try:
        # Get followers and following
        followers = asyncio.run(analyzer.get_followers(target_username))
        following = asyncio.run(analyzer.get_following(target_username))
        
        # Find non-followers
        non_followers = analyzer.find_non_followers(followers, following)
        
        # Print results
        print(f"\nПользователи, которые не подписаны в ответ на {target_username}:")
        for user in non_followers:
            print(f"- {user['username']} ({user['full_name']})")
        print(f"\nВсего: {len(non_followers)} пользователей")
        
        # Save data if requested
        if args.save:
            filename = data_manager.save_data(target_username, followers, following)
            print(f"\nДанные сохранены в файл: {filename}")
        
        # Compare with previous data if requested
        if args.compare:
            if isinstance(args.compare, str):
                old_data = data_manager.load_data(args.compare)
                if old_data:
                    comparison = data_manager.compare_data(old_data, {
                        'followers': followers,
                        'following': following
                    })
                    print_comparison_results(comparison)
                    
                    # Save comparison results if --save is also specified
                    if args.save:
                        comparison_file = data_manager.save_comparison(target_username, comparison)
                        print(f"\nРезультаты сравнения сохранены в файл: {comparison_file}")
                else:
                    print(f"\nОшибка: Не удалось загрузить файл {args.compare}")
            else:
                print("\nОшибка: Укажите путь к файлу для сравнения")
                print("Пример: python main.py username --compare data/username_2024-03-19_14-20.json")
    
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 