# Анализ подписчиков и подписок в Instagram

Определяет, кто не подписан в ответ, кто отписался, кто пришёл, и как список меняется со
временем. Работает **без ввода пароля**: данные берутся из официального экспорта Instagram,
а живой режим — из сохранённой браузерной сессии.

```powershell
python main.py analyze                                   # найти выгрузку рядом и разобрать
python main.py analyze --export instagram-export.zip     # разбор выгрузки из архива
python main.py analyze --export exp/ --save --compare     # + снимок в историю и сравнение с прошлым
python main.py snapshots list                             # история снимков
python main.py snapshots diff old.json new.zip            # сравнить любые два источника
python main.py session login --cookie "sessionid=…"       # живая сессия без пароля
python main.py analyze --live                              # то же самое, но данными «живьём»
```

---

## Почему не работало: диагноз

Разбор в старой версии (`instagrapi>=1.18.0`, `following - followers` и пустые `set`)
ломался по трём независимым причинам. Первые две — свойства самого Instagram, их нельзя
победить кодом; из-за них анализ и «не работал нормально», даже когда скрипт не падал.

### 1. Instagram обрезает списки подписчиков на стороне API

Приватный API отвечает флагом `should_limit_list_of_followers` — и `instagrapi` в этом
случае тихо переключается на GraphQL-фоллбэк, который отдаёт десятки–сотни записей вместо
тысяч ([#2811](https://github.com/subzeroid/instagrapi/issues/2811),
[#1318](https://github.com/subzeroid/instagrapi/issues/1318),
[discussion #1612](https://github.com/subzeroid/instagrapi/discussions/1612)).
Эндпоинты перечисления подписок — ещё и самые лимитируемые: `PleaseWaitFewMinutes`,
`FeedbackRequired`.

**Следствие:** `followers` неполный → `following - followers` выдаёт «фантомные» отписки.
Цифры при этом выглядят правдоподобно — это и есть «не работает нормально».

### 2. Библиотека за это время уехала на мажор вперёд

В PyPI `instagrapi 3.0.x` (требует Python ≥ 3.10), а проект был прибит к `>=1.18.0`.
Сигнатуры поменялись: `user_followers(user_id, use_cache=True, amount=0, order=None)`
возвращает `Dict[str, UserShort]`, появились `user_followers_v1_chunk`,
`login_by_sessionid`, `load_settings/dump_settings`. Метода `challenge_code_handler`,
который вызывал старый код, в библиотеке нет — ветка обработки challenge была мёртвой.

### 3. Собственные баги, которые превращали ошибки в «правдоподобную чушь»

| Было | Стало |
| --- | --- |
| `except Exception: break` → `return followers` (пустой `set`) — пустой список неотличим от «отписок нет» | источник либо отдаёт `Snapshot`, либо бросает `SourceError`/`RateLimited`/`IncompleteDataError` |
| усечённый список принимался за полный | `Snapshot.truncations`/`reliable`: сверка с `follower_count`, предупреждение в отчёте |
| `InstagramAnalyzer` создавался и не вызывался, анализ был продублирован в `main.py` | анализ живёт в `analyzer.py`, CLI его только печатает |
| `for username in sorted(non_followers)` затирал переменную с логином из `.env` | затенения нет |
| `asyncio.run()` ради `await asyncio.sleep(0.1)` и `list(dict.values())[i:i+50]` (O(n²)) внутри синхронного метода | обычной пагинации, без псевдо-асинхронности |
| `DELAY_BETWEEN_REQUESTS` импортировался, но не использовался; `delay_range=[0.5,1.5]` | настраиваемая пауза между страницами из `settings.py` |
| `from config import …` внутри пакета работало только из корня репозитория | настройки в `instagram_tracker/settings.py`, корневой `config.py` — прослойка |
| `get_available_files` матчил `username_*.json` и цеплял файлы сравнения → `load_data` падал по `KeyError` | снимки и отчёты лежат в `data/snapshots/` и `data/reports/`, отчёты в список снимков не попадают |
| имена файлов `ДД_ММ_ГГГГ` (не сортируются) и другой формат у отчётов, чем обещал README | `ник__20260926T112030Z__snapshot.json`, сортировка = хронология |
| оставались только ники: ни `pk`, ни дат, ни полного имени | `UserRef(username, user_id, full_name, is_private, since)` + CSV/JSON |
| сравнение по нику: переименованный аккаунт = «отписался» + «подписался» | если известны `user_id`, смена ника распознаётся (`renames`) |
| каждый запуск — новый `client.login()` с паролем, сессия не сохранялась | сессия переиспользуется: `sessionid` из браузера либо файл сессии |

Итог: **надёжный способ — официальный экспорт Instagram** (он всегда полный, и для него не
нужен логин), а live-режим оставлен как опция для случаев, когда данные нужны прямо сейчас.

---

## Способ 1 (рекомендуется): экспорт данных Instagram

Логин, пароль, 2FA и cookies скрипту не нужны вообще — вы скачиваете файл в браузере,
скрипт его только читает. Никакого риска блокировки и никаких лимитов.

1. Instagram → **Настройки и конфиденциальность → Центр аккаунтов → Ваши данные и
   разрешения → Скачать или перенести информацию** (в английском интерфейсе:
   *Accounts Center → Your information and permissions → Download or transfer information*).
2. Выберите свой аккаунт → **Some of your information** → отметьте только
   **Followers and following**.
3. **Format: JSON** (HTML тоже читается), **Date range: All time** → *Download to device*.
4. Дождитесь письма, скачайте ZIP. Внутри будет
   `connections/followers_and_following/followers_1.json` и `following.json`
   (при большом количестве подписчиков — `followers_2.json`, `followers_3.json`, …; их
   читаем все).
5. Запуск:

```powershell
# архив целиком
python main.py analyze --export C:\Users\you\Downloads\instagram-export.zip

# или просто положить followers_1.json и following.json в папку запуска — файлы найдутся сами
python main.py analyze
```

Минус способа: данные статичны на момент выгрузки (обычно 1–30 минут ждать письмо), и
доступна **только своя** выгрузка — чужие подписчики Instagram не отдаёт никому.

## Способ 2: живая сессия без пароля

Если нужны данные «прямо сейчас» или чужой публичный профиль. Вместо пароля используется
живучая сессия браузера — Instagram видит знакомое устройство, поэтому чекпоинты и
`Please wait a few minutes` высыпаются гораздо реже, чем при логине по паролю.

1. Откройте `instagram.com` в браузере (в профиле, от которого нужен анализ) и скопируйте
   `sessionid`: DevTools (`F12`) → **Application → Cookies → https://www.instagram.com →
   sessionid**. Значение вида `58645670417:a1b2c3…` (можно вставить и весь заголовок
   `Cookie: …`, и `cookies.txt` — доставим сами).
2. Сохраните сессию — один раз, дальше она нужна не будет:

```powershell
python main.py session login --cookie "sessionid=58645670417:a1b2c3…"
# или: python main.py session login --sessionid 58645670417:a1b2c3…
python main.py session status
```

3. Анализ: `python main.py analyze --live` (или `--live --username somebody`).
4. Проверка: `python main.py analyze --live` сам скажет, если список урезан:

```
⚠ Достоверность:
  • Список «followers» усечён Instagram'ом: 249 из 8123. Часть подписчиков физически
    отсутствует в данных, поэтому они будут выглядеть как отписавшиеся.
    Надёжный источник — выгрузка (--export).
```

По умолчанию в этом случае программа **падает с внятной ошибкой**, а не выдаёт выдуманные
отписки. Осознанно согласиться на неполные данные — `--allow-partial`.

Пароль (`INSTAGRAM_USERNAME`/`INSTAGRAM_PASSWORD` в `.env` или `session login --username …
--password …`) остался, но он не нужен: сессия после первого входа сохраняется в
`data/instagram_session.json` (файл с `chmod 600`; в `.gitignore` добавлен).

**Про «код, чтобы сессия жила»:** `sessionid` — и есть этот код. Он живёт до смены пароля и
до выхода из аккаунта, скрипт после `session login` его больше не просит. Автоматически
продлить протухшую сессию нельзя: это решение Meta, а не библиотеки.

---

## Что показывает анализ

| Секция | Смысл |
| --- | --- |
| **Вы подписаны, они — нет** | те, кто не подписан в ответ (`following − followers`) |
| **Они подписаны на вас, вы — нет** | ваши «фанаты», на кого вы не подписаны (`followers − following`) |
| **Взаимные подписки** | пересечение списков |
| **Новые подписчики / Отписались от вас** | динамика `followers` между снимками |
| **Вы подписались / Вы отписались** | динамика `following` |
| **Сменили ник** | не считаются отпиской, если известен `user_id` (в выгрузке его нет, там сравнение по нику) |

## Файлы

```
data/
├── instagram_session.json              # живая сессия (секрет! в git не попадает)
├── snapshots/<ник>__<20260926T112030Z>__snapshot.json
└── reports/<ник>__<момент>__diff.json | __followback.json
```

Снимок — это `followers`/`following` с меткой времени, источником и признаком полноты;
`--save` кладёт его в историю, `--compare` без значения берёт последний снимок.
Старые файлы вида `username_DD_MM_YYYY_HH_MM.json` и `username_comparison_*.json`
по-прежнему читаются.

## Установка и запуск

```bash
pip install -r requirements.txt        # ядру зависимости не нужны: только python-dotenv (опция)
pip install -r requirements-live.txt   # если нужен живой режим (instagrapi>=3.0, Python>=3.10)
```

`.env` не обязателен. Переменные: `INSTAGRAM_SESSIONID`, `INSTAGRAM_DATA_DIR`,
`INSTAGRAM_SESSION_FILE`, `INSTAGRAM_PROXY`, `INSTAGRAM_DELAY_RANGE`, `INSTAGRAM_MAX_RETRIES`,
`INSTAGRAM_RETRY_DELAY`, `INSTAGRAM_MAX_ITEMS`, `INSTAGRAM_ALLOW_PARTIAL`,
`INSTAGRAM_STALENESS_DAYS`.

## Тесты

```bash
python -m pytest            # 70+ тестов, сеть не нужна
```

Фикстуры — настоящие формы выгрузки (`string_list_data`, чанки `followers_2.json`, HTML,
ZIP, legacy-формат), а живой режим проверяется на подставном клиенте: пагинация, ретраи
по лимитам, откат на публичный GraphQL, реакция на обрезку списка.

## Чего честно не умеет

* Чужие приватные аккаунты и чужие списки подписчиков — Instagram их не отдаёт; выгрузка
  и live-режим показывают только ваш профиль (для `--live` чужой публичный профиль — с
  поправкой на обрезку).
* Точная дата отписки: её нет ни в API, ни в экспорте; фиксируется факт «между снимками N и M».
* Официальный Graph API: списков подписчиков не существует в природе
  (scope `follower_list` закрыт с 2018 года), поэтому «легального» автоматического пути нет.
