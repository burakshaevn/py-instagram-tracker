Определяет, кто из пользователей Instagram не подписан в ответ. Программа использует библиотеку `instagrapi` для безопасного взаимодействия с Instagram.

## Возможности

- Определение пользователей, которые не подписаны в ответ
- Возможность проверки любого аккаунта по никнейму
- Асинхронная обработка данных для быстрой работы
- Отображение прогресса выполнения

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Создайте файл `.env` в корневой директории проекта (`...\py-instagram-tracker\`) с вашими учетными данными Instagram:
```
INSTAGRAM_USERNAME=ваш_логин
INSTAGRAM_PASSWORD=ваш_пароль
```

## Использование

1. Проверка своего аккаунта:
```powershell
python main.py
```

2. Проверка другого аккаунта:
```powershell
python main.py имя_пользователя
```

Пример:

**Ввод**:
```powershell
python main.py nikitaaa_bb
```

**Вывод**:
<div align="center">
  <img src="https://github.com/user-attachments/assets/a30f3d2a-92b8-4ae3-aebe-874fce8293c9" alt="image"> 
</div> 


## Как это работает

1. Программа авторизуется в Instagram используя ваши учетные данные, с которого и отправляется запрос
2. Получает список подписчиков указанного аккаунта
3. Получает список подписок указанного аккаунта
4. Сравнивает списки и находит пользователей, которые не подписаны в ответ
5. Выводит результаты в консоль

## Особенности реализации

- Асинхронная обработка данных для оптимизации производительности 
- Использование паттерна «Стратегия» для различных методов получения данных
- Использование паттерна «Наблюдатель» для отслеживания прогресса

## Требования

- Python 3.7 или выше
- Установленные зависимости из `requirements.txt`
- Аккаунт Instagram
- Доступ к интернету
- **ВКЛЮЧЁННЫЙ VPN В МОМЕНТ ВЫПОЛНЕНИЯ ЗАПРОСА**

## Возможные ошибки

Если вы получаете ошибки:
1. Проверьте правильность учетных данных в файле `.env`
2. Убедитесь, что все зависимости установлены
3. Проверьте подключение к интернету
4. При получении ошибки о превышении лимита запросов, подождите несколько минут и попробуйте снова 

## ConnectionError HTTPSConnectionPool
Требует подключения VPN для авторизации.
```powershell
PS C:\dev\repos\py-instagram-tracker> python main.py
Logging in to Instagram...
Login failed: ConnectionError HTTPSConnectionPool(host='i.instagram.com', port=443): Max retries exceeded with url: /api/v1/launcher/sync/ (Caused by ReadTimeoutError("HTTPSConnectionPool(host='i.instagram.com', port=443): Read timed out. (read timeout=None)"))
Failed to login. Please check your credentials.
```
