import os
import sys
import asyncio
import argparse
from datetime import datetime
from dotenv import load_dotenv
from instagram_tracker.strategies import InstagrapiStrategy
from instagram_tracker.observers import ConsoleProgressObserver
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
    parser = argparse.ArgumentParser(
        description='Анализ подписчиков и подписок в Instagram',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Команды:
python main.py              - проверка своего аккаунта
python main.py USERNAME     - проверка указанного аккаунта
python main.py USERNAME --save           - сохранить результаты в JSON
python main.py USERNAME --compare FILE   - сравнить с данными из файла

Формат файлов:
- Данные: username_DD_MM_YYYY_HH_MM.json
- Сравнение: username_comparison_DD_MM_YYYY_HH_MM.json

Требования:
- Файл .env с учетными данными Instagram
- VPN (если Instagram недоступен в регионе)
'''
    )
    parser.add_argument('username', nargs='?', help='Имя пользователя Instagram')
    parser.add_argument('--save', action='store_true', help='Сохранить в JSON')
    parser.add_argument('--compare', help='Сравнить с файлом')
    args = parser.parse_args()

    # Load environment variables
    load_dotenv()
    
    # Get credentials from environment variables
    username = os.getenv('INSTAGRAM_USERNAME')
    password = os.getenv('INSTAGRAM_PASSWORD')
    
    if not username or not password:
        print("Ошибка: INSTAGRAM_USERNAME и INSTAGRAM_PASSWORD должны быть заданы в файле .env")
        sys.exit(1)
    
    # Get target username from command line or use the authenticated user
    target_username = args.username or username
    
    # Create strategy and observer
    strategy = InstagrapiStrategy()
    observer = ConsoleProgressObserver()
    strategy.attach(observer)
    
    # Create analyzer
    analyzer = InstagramAnalyzer(strategy)
    
    # Create data manager
    data_manager = InstagramDataManager()
    
    try:
        # Login first
        if not strategy.login(username, password):
            print("Failed to login. Please check your credentials.")
            sys.exit(1)
            
        # Get followers and following
        followers = strategy.get_followers(target_username)
        following = strategy.get_following(target_username)
        
        # Find non-followers
        non_followers = following - followers
        
        # Print results
        print(f"\nПользователи, которые не подписаны в ответ на {target_username}:")
        for username in sorted(non_followers):
            print(f"- {username}")
        print(f"\nВсего: {len(non_followers)} пользователей")
        
        # Save data if requested
        if args.save:
            filename = data_manager.save_data(target_username, followers, following)
            print(f"\nДанные сохранены в файл: {filename}")
        
        # Compare with previous data if requested
        if args.compare:
            if not os.path.exists(args.compare):
                print(f"\nОшибка: Файл {args.compare} не найден")
                sys.exit(1)
                
            old_data = data_manager.load_data(args.compare)
            if old_data:
                comparison = data_manager.compare_data(old_data, followers, following)
                print_comparison_results(comparison)
                
                # Save comparison results if --save is also specified
                if args.save:
                    comparison_file = data_manager.save_comparison(target_username, comparison)
                    print(f"\nРезультаты сравнения сохранены в файл: {comparison_file}")
            else:
                print(f"\nОшибка: Не удалось загрузить файл {args.compare}")
        elif args.compare is not None:  # --compare was used without a file path
            print("\nОшибка: Укажите путь к файлу для сравнения")
            print("Пример: python main.py username --compare \"C:\\path\\to\\file.json\"")
            sys.exit(1)
    
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 