# Анализ подписчиков и подписок в Instagram

Определяет, кто из пользователей Instagram не подписан в ответ. Программа использует официальную библиотеку `instagrapi` для взаимодействия с Instagram.

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![Instagram](https://img.shields.io/badge/Instagram-E4405F?logo=instagram&logoColor=white)

## Команды

```powershell
python main.py                                 ← проверка своего аккаунта
python main.py USERNAME                        ← проверка указанного аккаунта
python main.py USERNAME --save                 ← сохранить результаты в JSON
python main.py USERNAME --compare FILE         ← сравнить с данными из файла
python main.py USERNAME --compare FILE --save  ← сравнить и сохранить результаты сравнения
```

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Создайте файл «`.env`» в корневой директории проекта с учетными данными Instagram:
```
INSTAGRAM_USERNAME=ваш_логин
INSTAGRAM_PASSWORD=ваш_пароль
```

## Формат файлов

- Файлы данных: `username_DD_MM_YYYY_HH_MM.json`
- Файлы сравнения: `username_comparison_DD_MM_YYYY_HH_MM.json`

## Требования

- Python 3.7 или выше
- Установленные зависимости из `requirements.txt`
- Любой аккаунт Instagram 
- VPN (если Instagram недоступен в регионе)

## Возможные ошибки

1. Проверьте правильность учетных данных в файле `.env`
2. Убедитесь, что все зависимости установлены
3. Проверьте подключение к интернету и VPN
4. При получении ошибки о превышении лимита запросов, подождите несколько минут и попробуйте снова

### [?] Решение проблемы «**ConnectionError HTTPSConnectionPool**»:

Требует подключения VPN для авторизации, если Instagram недоступен в вашем регионе.
```powershell
PS C:\dev\repos\py-instagram-tracker> python main.py
Logging in to Instagram...
Login failed: ConnectionError HTTPSConnectionPool(host='i.instagram.com', port=443): Max retries exceeded with url: /api/v1/launcher/sync/ (Caused by ReadTimeoutError("HTTPSConnectionPool(host='i.instagram.com', port=443): Read timed out. (read timeout=None)"))       
Failed to login. Please check your credentials.
```
