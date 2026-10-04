## Swapmeet Astana

Telegram-бот для объявлений купли, продажи и обмена. Данные хранятся в SQLite.

### Возможности

- reply-меню для управления объявлениями: подача, снятие и редактирование;
- публикация новых объявлений в чат `@swapmeet_astana` через бота;
- категории при создании: `Дом(быт/ремонт)`, `Другое`, `Одежда`, `Животные`, `Книги`, `Детские`;
- ссылка на автора в начале каждого объявления;
- объявления `Купить` с лимитом описания 500 символов и суточным лимитом из `.env`;
- объявления `Продать` с категорией, описанием, ценой, адресом и фото;
- добавление до 6 фото, включая отправку Telegram-медиагруппой;
- проверка повторов фото по perceptual hash за настраиваемый период;
- снятие/удаление объявлений с указанием причины и копированием в `hist_market`;
- бронь ответом на объявление текстом `бронь`/`забронировать` или через Reply-menu по номеру объявления;
- удаление объявления автором или админом через личный диалог с ботом по номеру объявления;
- автоматическая очистка объявлений старше периода хранения: при запуске и ежедневно в 01:00;
- статус расписания хранится в таблице `scheduled_jobs` (`last_run_at`, `next_run_at`).

### Настройка

Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN`.

```env
BOT_TOKEN=put-telegram-bot-token-here
DATABASE_PATH=data/swapmeet_astana.sqlite3
FSM_STORAGE=memory
REDIS_URL=redis://localhost:6379/0
PUBLICATION_CHAT_ID=@swapmeet_astana
COMMUNICATION_TOPIC_ID=
TOPIC_OTHER_ID=
TOPIC_ANIMALS_ID=
TOPIC_BOOKS_ID=
TOPIC_HOME_ID=
TOPIC_KIDS_ID=
TOPIC_CLOTHES_ID=
COMMUNICATION_DAILY_MESSAGE_LIMIT=20
BUY_DAILY_LIMIT=2
USER_DAILY_AD_LIMIT=10
USER_HOURLY_AD_LIMIT=5
DUPLICATE_PHOTO_DAYS=7
RETENTION_PERIOD_DAYS=7
ADMIN_IDS=
```

Для публикации объявлений в темы Telegram укажите `message_thread_id` нужных тем:

```env
TOPIC_OTHER_ID=
TOPIC_ANIMALS_ID=
TOPIC_BOOKS_ID=
TOPIC_HOME_ID=
TOPIC_KIDS_ID=
TOPIC_CLOTHES_ID=
```

Если ID темы для категории не указан, объявление публикуется в `General`.

### Таблицы SQLite

| Таблица | Назначение |
|---|---|
| `market` | Основная таблица объявлений: создание, чтение, редактирование, снятие и бронь. |
| `market_photos` | Фото объявлений, включая `file_id`, `file_unique_id` и perceptual hash для поиска повторов. |
| `ad_messages` | Связь объявлений с опубликованными Telegram-сообщениями, чтобы обновлять или удалять публикации. |
| `admins` | Администраторы. Поле `can_manage_admins` даёт право добавлять других админов. Админы из `ADMIN_IDS` получают это право при запуске. |
| `communication_messages` | Учёт сообщений пользователей в теме `Общение` для суточного лимита. |
| `user_blocks` | Блокировки пользователей с причиной и сроком действия, например если пользователь запретил боту писать в личку. |
| `ui_messages` | Служебные сообщения интерфейса и ленты, которые бот может удалять при очистке. |
| `hist_market` | Архив снятых или истёкших объявлений с причиной удаления. |
| `scheduled_jobs` | Состояние фоновых задач, сейчас используется для ежедневной очистки объявлений. |

### Запуск

```bash
uv sync
$env:PYTHONPATH="src"
uv run python -m bot
```

Или:

```powershell
$env:PYTHONPATH="src"
python -m bot
```

### Запуск в Docker

Скопируйте пример настроек и заполните токен:

```bash
cp .env.example .env
```

База проекта хранится в `data/swapmeet_astana.sqlite3`. В Docker этот каталог монтируется в контейнер как `/app/data`, а `DATABASE_PATH` внутри образа задан как `/app/data/swapmeet_astana.sqlite3`.

```env
DATABASE_PATH=data/swapmeet_astana.sqlite3
```

Dockerfile лежит в корне проекта. Соберите и запустите бота:

```bash
docker build -t swapmeet-astana .
docker run -d --name swapmeet-astana --env-file .env -v ./data:/app/data swapmeet-astana
```

При Docker-запуске Redis стартует внутри этого же контейнера. Dockerfile задает:

```env
FSM_STORAGE=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

Для локального запуска без Docker можно оставить `FSM_STORAGE=memory`; Redis тогда не нужен, но незавершенные сценарии пользователей будут сбрасываться при перезапуске процесса.

Полезные команды на сервере:

```bash
docker logs -f swapmeet-astana
docker restart swapmeet-astana
docker stop swapmeet-astana
docker rm swapmeet-astana
```

SQLite хранится в `data/swapmeet_astana.sqlite3`. Сделать резервную копию:

```bash
cp data/swapmeet_astana.sqlite3 data/swapmeet_astana.backup.sqlite3
```

Восстановить базу из файла рядом с проектом:

```bash
docker stop swapmeet-astana
docker rm swapmeet-astana
cp swapmeet_astana.sqlite3 data/swapmeet_astana.sqlite3
docker run -d --name swapmeet-astana --env-file .env -v ./data:/app/data swapmeet-astana
```
