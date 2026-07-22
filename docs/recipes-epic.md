# Эпик: Рецепты (профили варки) — отображение и сборка

Отображение библиотеки рецептов, а в дальнейшем — локальная сборка и выгрузка
профилей обратно в RAPT.

## Findings: что даёт RAPT API по профилям

### Как профили попадают к нам сейчас

Профиль варки берётся **только** из `activeProfileSession.profile` в ответе
`GET /api/BrewZillas/GetBrewZillas` ([sync.py](../backend/core/sync.py) `_sync_brewzillas`,
и повторно в [portal_data_sync.py](../backend/scripts/portal_data_sync.py)) и складывается
в `BrewSession.profile_json`. То есть в БД есть только профили тех сессий, что были
**активны в момент синка**. Отдельной библиотеки рецептов нет.

### Чтение профилей — публичный API (bearer `rapt-user`, как в `rapt_client`)

Проверено вживую: `GetProfiles` вернул 5 профилей, все типа `BrewZilla`
(16 шагов затирания/кипячения с реальными T и таймингами).

| Метод | Эндпоинт | Что даёт |
|---|---|---|
| GET | `/api/Profiles/GetProfiles` | **Вся библиотека профилей аккаунта** (включая ни разу не запущенные) |
| GET | `/api/Profiles/GetProfile?profileId=` | Один профиль |
| GET | `/api/ProfileTypes/GetAll` | Типы профилей + их темп. диапазоны |

Типы аккаунта (`ProfileTypes/GetAll`): `BrewZilla` (0–110 °C), `Fermentation`
(-5–65 °C), `General Temperature Control` (-40–400 °C), `Pill Hydrometer`.
Варочный профиль отличается по `profileTypeId` → тип `BrewZilla`.

### Запись профилей — портальный API (bearer `rapt-web`, как в `portal_data_sync`/`sync_yeasts`)

Эти эндпоинты **нет в публичном swagger** — вытащены из бандла портала
`app.rapt.io` (`chunk-OZUFNZMC.js`, страница профилей):

| Метод | Эндпоинт | Назначение |
|---|---|---|
| **POST** | **`/api/Profiles/AddOrUpdateProfile`** | Создать/обновить рецепт. Тело — `ProfileModel`. Пустой `id` → создание, заполненный → апдейт |
| GET | `/api/Profiles/CloneProfile?profileId=` | Скопировать существующий |
| DELETE | `/api/Profiles/RemoveProfile?profileId=` | Удалить |
| GET | `/api/Profiles/GetPublicProfiles?pageSize=&pageNum=&filterText=` | Публичная библиотека (импорт чужих рецептов) |
| GET | `/api/Profiles/AddRating?profileId=` | Оценка |
| GET | `/api/Profiles/DownloadProfileToBrewZilla?brewZillaId=&profileId=` | **Залить профиль прямо на устройство** |

Портальный токен короткоживущий (~60 мин, руками из DevTools) — то же
ограничение, что у текущего портального синка (`PORTAL_TOKEN` / `.portal_token`).

### Схема `ProfileModel` (это и есть рецепт)

```
id, deleted, createdOn/By, modifiedOn/By
name, description, profileName
public, rating, ratingCount, ratingScore, copyCount, viewCount
profileTypeId                       # → тип BrewZilla / Fermentation / ...
alerts[]        ProfileAlertModel   # алерты уровня профиля
steps[]         ProfileStepModel    # костяк рецепта, см. ниже
profileSessions[] ProfileSessionModel  # история запусков (startDate/endDate/OG/FG/yeast)
```

`ProfileStepModel` (шаг):
```
id, name, order
controlType   enum: Target | Ramp | FreeRise
endType       enum: Duration | Temperature | Gravity | GravityVelocity | Manual
durationType  enum: Start | Temperature | Gravity | GravityVelocity | Manual | null
operator      enum: Equals | LessThan | GreaterThan | null
length        # ДЛИТЕЛЬНОСТЬ В СЕКУНДАХ
temperature, minTemperature, maxTemperature
gravity
pumpEnabled, pumpUtilisation, heatingUtilisation
pidEnabled, sensorDifferential
alerts[]      ProfileStepAlertModel   # алерты уровня шага, см. ниже
```

`ProfileAlertModel` (уровень профиля) / `ProfileStepAlertModel` (уровень шага):
```
id, alertText
trigger    enum: StepStart | StepEnd | Temperature | Gravity | GravityVelocity | Duration
operator   enum: Equals | LessThan | GreaterThan | null
temperature, gravity
length     # секунды, только у ProfileStepAlertModel (trigger=Duration)
```

### Enum'ы (единый список — для AI-wizard и жёстких схем)

Канонический источник — [backend/features/profiles/enums.py](../backend/features/profiles/enums.py)
(визард на бэкенде). Зеркалятся в `frontend/src/types/profile.ts` как
`as const`-массивы + union-типы; держать в синхроне.

| Enum | Значения |
|---|---|
| `ProfileStepControlTypes` | `Target`, `Ramp`, `FreeRise` |
| `ProfileStepEndTypes` | `Duration`, `Temperature`, `Gravity`, `GravityVelocity`, `Manual` |
| `ProfileStepDurationTypes` | `Start`, `Temperature`, `Gravity`, `GravityVelocity`, `Manual`, `null` |
| `ProfileValueOperators` | `Equals`, `LessThan`, `GreaterThan`, `null` |
| `ProfileAlertTriggers` | `StepStart`, `StepEnd`, `Temperature`, `Gravity`, `GravityVelocity`, `Duration` |
| `ProfileTypes` (аккаунт) | `BrewZilla`, `Fermentation`, `General Temperature Control`, `Pill Hydrometer` |

### Заметки

- `profileSessions[]` внутри `ProfileModel` содержит историю запусков с OG/FG/датами/дрожжами
  — вопреки тому, что AGENTS.md утверждает про отсутствие истории в публичном API.
  **TODO проверить полноту** — если полна, упрощает всю модель «наблюдай активную сессию».
- Записи профилей в публичном API нет — только через портальный `AddOrUpdateProfile`.
- Наши фронтовые типы `BrewStep`/`BrewProfile` ([types/brew.ts](../frontend/src/types/brew.ts))
  уже покрывают подмножество полей шага — переиспользуем/расширим.

## План реализации

> **Важно (уточнено на практике):** `GetProfiles` с публичным `rapt-user`
> токеном возвращает профили с **пустыми** `alerts` (и на уровне профиля, и на
> уровне шага). Чтобы получить алерты, синк идёт с **портальным** токеном
> (как `sync_yeasts`). Значит уже Фаза 1 требует портальный токен.

### Фаза 1 — Отображение (read-only, портальный токен ради алертов)

1. **Модель** `Profile` в [core/db.py](../backend/core/db.py): `id`, `name`, `description`,
   `public`, `rating`, `profile_type_id`, `profile_type_name`, `steps_json` (Text),
   `alerts_json` (Text), `updated_at`. Шаги храним JSON-строкой — как `BrewSession.profile_json`,
   без отдельной таблицы шагов (нормализация — только когда потребует редактор, YAGNI).
2. **Alembic-ревизия**: `create_table("profiles", ...)`.
3. **rapt_client**: `get_profiles()` / `get_profile(id)` / `get_profile_types()`.
4. **Сервис** `features/profiles/services.py::sync_profiles()` — GetProfiles + GetProfileTypes,
   upsert по образцу `sync_yeasts`. Публичный токен → портальный не нужен.
5. **Роутер** `features/profiles/router.py`: `GET /api/profiles` (список без шагов),
   `GET /api/profiles/{id}` (полный со шагами). Регистрация в [app.py](../backend/app.py).
6. **Триггер синка**: job-kind `profile_sync` в [system/services.py](../backend/features/system/services.py)
   + `POST /api/sync_profiles`, чтобы дёргать со страницы System Syncs. Плюс скрипт
   `scripts/sync_profiles.py`.
7. **Фронт**: `types/profile.ts`, `api/profiles.ts`, страница `pages/Recipes.tsx`
   (список) + деталь профиля (шаги как timeline/таблица), маршрут и навигация в
   [App.tsx](../frontend/src/App.tsx).

### Фаза 2 — Сборка и выгрузка (портальный API)

1. Локальное редактирование `Profile` (CRUD шагов в UI), хранение в нашей БД
   с признаком «черновик / не залит».
2. `features/profiles/services.py::upload_profile()` — `POST /api/Profiles/AddOrUpdateProfile`
   с портальным токеном (пустой `id` → создание). Job-kind `profile_upload` + роут.
3. Опционально `DownloadProfileToBrewZilla` — заливка сохранённого профиля на устройство.
4. Импорт из `GetPublicProfiles` / `CloneProfile`.

Начинаем с Фазы 1.
