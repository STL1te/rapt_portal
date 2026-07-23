# Эпик: AI-фичи рецептов

Продолжение [recipes-epic.md](./recipes-epic.md) (отображение → сборка → выгрузка
уже сделаны). Две новые фичи поверх существующей LLM-обвязки:

- **A. Чат-проверка рецепта** на странице рецепта — как AI-ассистент у сессий,
  но контекст = профиль (шаги + алерты), дефолтный запрос «Проверь рецепт, всё
  ли с ним ок?».
- **B. AI-мастер** в редакторе при создании нового рецепта — по свободному
  описанию собирает `ProfileInput` **строго по схеме** (enum'ы + поля шага).

Обе переиспользуют то, что уже есть, и ничего нового в стек не тянут.

## Что уже есть (переиспользуем)

| Кусок | Файл | Как используем |
|---|---|---|
| LLM-клиент + конфиг | [core/config.py](../backend/core/config.py) (`LLM_*`), `AsyncOpenAI` в [ai/services.py](../backend/features/ai/services.py) | тот же клиент, те же параметры (`LLM_TEMPERATURE`/`LLM_TOP_P`), тот же `_load_prompt` |
| Промпты из файлов | [backend/prompts/](../backend/prompts/) + `_load_prompt()` | добавим `recipe_review.md`, `recipe_wizard.md` рядом |
| Роутер AI | [ai/router.py](../backend/features/ai/router.py) | добавим 2 эндпоинта туда же |
| Схема рецепта (Pydantic) | `ProfileIn`/`StepIn`/`AlertIn` в [profiles/router.py](../backend/features/profiles/router.py) | валидация вывода мастера — модель **уже описывает** payload |
| Enum'ы (канон) | [profiles/enums.py](../backend/features/profiles/enums.py) | список допустимых значений в промпт + пост-валидация |
| Чат-окно (UI) | [components/AiAssistant.tsx](../frontend/src/components/AiAssistant.tsx) | переиспользуем окно для чата рецепта |
| Клиент API | [api/ai.ts](../frontend/src/api/ai.ts), [api/profiles.ts](../frontend/src/api/profiles.ts) | добавим 2 вызова |
| Типы | [types/profile.ts](../frontend/src/types/profile.ts) (`ProfileInput`, enum-массивы) | вход/выход мастера = `ProfileInput` |

Модель — локальная (`qwen3:8b` через Ollama, OpenAI-совместимый эндпоинт).

---

## Фича A — Чат-проверка рецепта

### Требования

1. На [RecipeDetail](../frontend/src/pages/RecipeDetail.tsx) кнопка «AI-проверка»
   (иконка `fa-wand-magic-sparkles`, как у сессий) открывает чат-окно.
2. При открытии автоматически уходит дефолтный запрос; в чате он показывается как
   реплика пользователя **«Проверь рецепт, всё ли с ним ок?»**, а модель получает
   расширенную директиву (по образцу `DEFAULT_QUESTIONS` vs `DEFAULT_INSTRUCTIONS`).
3. Дальше — свободный диалог (уточняющие вопросы), история как у сессий
   (`history`, до 12 сообщений, `LLM_CHAT_TEMPERATURE` после первой реплики).
4. Контекст модели — сохранённый профиль по `profile_id`: шаги (с человекочитаемой
   расшифровкой enum'ов), алерты профиля и шагов, тип профиля. Телеметрии нет.
5. Ответ — русский, markdown; та же дисциплина разделов, что у брю-промпта
   (`## Итог / ## Наблюдения / ## Риски / ## Следующие действия`).
6. Модель оценивает: осмысленность порядка шагов, температуры/длительности
   (затирание/мэшаут/кип), пропущенные шаги, подозрительные значения, полезность
   алертов. Не выдумывает засыпь/хмель/дрожжи, которых нет в профиле.

### Бэкенд

- **Промпт** `prompts/recipe_review.md`: «опытный технолог, ревьюит профиль
  варки RAPT». Объяснить единицы (`length` — секунды, температура °C) и смысл
  enum-полей шага/алерта, чтобы модель читала сырой JSON профиля.
- **Контекст** `build_recipe_context(db, profile_id) -> str`: берём `Profile`,
  переиспользуем `profile_dict(p)` (уже отдаёт `steps`+`alerts`), сериализуем в
  JSON. Не тянем «сырые» служебные поля — `profile_dict` их уже чистит.
- **`review_recipe(profile_id, question, history)`** — по образцу `assess()`, но:
  системный промпт = recipe_review, дефолт-директива из нового файла
  `recipe_review_default.md`, **без tools** (v1 — один профиль в контексте;
  сравнение с другими рецептами — потом, YAGNI).
- **Эндпоинт** в [ai/router.py](../backend/features/ai/router.py):
  `POST /api/ai/recipe-review` — `{ profile_id, question?, history[] }` →
  `{ answer, model, question }`. 404 если профиля нет.

```python
class RecipeReviewRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=128)
    question: str | None = Field(default=None, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
```

### Фронтенд

Дефолтный запрос показывается как «Проверь рецепт, всё ли с ним ок?».

Переиспользование `AiAssistant`: компонент сейчас зашит под
`kind: 'brew'|'fermentation'` + `sessionId` + `assessSession`. Всё окно (пузыри,
composer, fullscreen, свайп-закрытие) переиспользуемо, различается только:
запрос (`ask`) и текст дефолтного вопроса.

**Рекомендация (лениво и без дублирования UI):** параметризовать `AiAssistant`
двумя пропами вместо жёсткой привязки к сессиям:

- `defaultQuestion: string`
- `ask(question: string | null, history): Promise<{ question; answer }>`

Страницы сессий передают обёртку над `assessSession`, `RecipeDetail` — над новым
`reviewRecipe`. Внутренний markdown/стриминг/скролл не трогаем. Альтернатива —
скопировать окно во второй компонент — отвергнута (дубль 150 строк UI).

- `api/ai.ts`: `reviewRecipe({ profile_id, question, history })`.
- `types/ai.ts`: `RecipeReviewRequest`, переиспользуем `AiChatMessage`/`AiAssessment`.
- `RecipeDetail.tsx`: кнопка `.assistant-button` + смонтированный `<AiAssistant>`
  (как в [BrewSessionPage](../frontend/src/pages/BrewSessionPage.tsx#L113-L123)).

---

## Фича B — AI-мастер профиля

Подробный актуализированный план для реализации:
[recipes-ai-feature-b-implementation-plan.md](./recipes-ai-feature-b-implementation-plan.md).

### Требования

1. В [RecipeEditor](../frontend/src/pages/RecipeEditor.tsx) **при создании нового**
   рецепта (`!isEdit`) — кнопка «AI-мастер».
2. Открывает поле с описанием на естественном языке (пример плейсхолдера:
   «APA на 23 л, одноступенчатое затирание 66 °C 60 мин, мэшаут 78 °C 10 мин,
   кип 60 мин, добавить алерт на закладку хмеля за 15 мин до конца кипа»).
3. По описанию модель возвращает **валидный `ProfileInput`**: `name`,
   `description`, `steps[]` (с корректными enum'ами, температурами, `length` в
   секундах, `order`), опц. `alerts[]`. `profile_type_id` мастер **не выбирает** —
   ставим текущий из формы (пока только `BrewZilla`).
4. Результат **заполняет форму редактора** (`setName`/`setDescription`/`setSteps`/
   `setAlerts`), а не сохраняется молча — пользователь видит, правит, жмёт
   «Сохранить черновик» существующей кнопкой. Помечаем форму `dirty`.
5. Если полей мало — мастер ставит разумные дефолты: `controlType='Target'`,
   а таймер температурной выдержки запускает по достижении цели через
   `durationType='Temperature'`. Для служебного костяка используются явно
   задокументированные температуры.
6. Ошибку («не смог собрать по описанию») показываем, форму не портим.

### Строгое соответствие схеме — как гарантируем

Локальная модель может нафантазировать структуру, поэтому:

1. **Схема в промпте.** В `recipe_wizard.md` — точный формат JSON и **полные
   списки допустимых значений** из [enums.py](../backend/features/profiles/enums.py)
   (`CONTROL_TYPES`, `END_TYPES`, `DURATION_TYPES`, `ALERT_TRIGGERS`,
   `VALUE_OPERATORS`) + человекочитаемые лейблы (`*_LABELS`) и ограничения
   (`STEP_NAME_MIN/MAX_LEN`, `STEP_REQUIRED_FIELDS`, `length` в секундах).
   Значения подставляем в промпт **из enums.py программно**, не хардкодим в тексте
   (единый источник правды).
2. **Строгая JSON Schema.** OpenAI-совместимому эндпоинту передаётся
   `response_format` с `type="json_schema"`, `strict=true`, закрытыми объектами и
   enum-ограничениями. Просим только JSON, без прозы.
3. **Пост-валидация** ответа:
   - парсим JSON → прогоняем через **существующий `ProfileIn`** (реюз! он уже
     описывает форму payload);
   - проверяем членство enum-полей в кортежах из `enums.py` (Pydantic-поля там
     `str|None` и enum не форсят — добавляем явную проверку или `field_validator`);
   - нормализуем: `order` = индекс, `length` — целые секунды.
4. **Один ретрай** при провале валидации: отправляем модели её же ответ + текст
   ошибки, просим исправить. Больше ретраев — YAGNI.

Схема ограничивает структуру ответа, а `ProfileIn` и wizard-валидатор отдельно
проверяют межполевую семантику таймеров, температур и алертов.

### Бэкенд

- **`prompts/recipe_wizard.md`** — системный промпт (схема подставляется в рантайме).
- **`generate_profile(description) -> dict`** в `ai/services.py`: собирает
  сообщения, зовёт модель в JSON-режиме, парсит, валидирует через `ProfileIn` +
  enum-check, при провале — один ретрай, иначе `ValueError`.
- **Эндпоинт** `POST /api/ai/recipe-wizard` — `{ description }` →
  `ProfileInput`-совместимый dict (`{ name, description, public:false,
  profile_type_id:null, steps, alerts }`; `profile_type_id` фронт подставит сам).
  422/502 при неудаче валидации/модели.

```python
class RecipeWizardRequest(BaseModel):
    description: str = Field(min_length=8, max_length=4000)
```

> ⚠️ Зависимость: enum-валидатор и промпт-схема должны тянуться из `enums.py`.
> Если импорт `profiles.router.ProfileIn` в `ai/services.py` создаёт цикл —
> вынести `ProfileIn/StepIn/AlertIn` в `profiles/schemas.py` и импортить оттуда
> в обоих местах (мелкий рефактор, делаем только если цикл реально возникнет).

### Фронтенд

- `api/ai.ts`: `generateProfile(description) => post<ProfileInput>('/api/ai/recipe-wizard', ...)`.
- `RecipeEditor.tsx`: кнопка «AI-мастер» (только при `!isEdit`), инлайн-панель с
  `<textarea>` + «Собрать» + спиннер. По ответу — засеять состояние формы теми же
  сеттерами, что и `useEffect(existing)` (вынести в `applyProfile(data)` и звать
  из обоих мест), навесить `_uid` на шаги, `markDirty()`.
- Ошибку рендерим в существующий `error`-баннер редактора.

---

## Solидарность фронт/бэк по enum'ам

Мастер валидирует по `enums.py`, фронт-типы — зеркало в `types/profile.ts`. Уже
договорено «держать в синхроне» (комментарии в обоих файлах). Новых источников
правды не заводим.

## Открытые вопросы

1. **Стриминг ответа чата.** Сейчас `assess()` не стримит (ждёт целиком). Оставляем
   так же — консистентно с сессиями. Стриминг — отдельный тикет, если будет надо.
2. **Мастер и типы профиля.** v1 — только `BrewZilla` (как редактор). Fermentation
   потребует gravity-полей и профильных алертов — когда откроем тип в редакторе.
3. **Инструменты чата (сравнение рецептов).** Отложено. Если понадобится — добавить
   tool `search_profiles`/`get_profile_context` по образцу session-tools.
4. **Локальная модель и качество JSON.** Ретрай-петля страхует провайдеры,
   частично реализующие OpenAI Structured Outputs. Если модель стабильно не
   держит схему — проверить поддержку `response_format=json_schema` или поднять модель.

## Порядок работ

**Фаза A — чат-проверка (меньше и без валидации, делаем первой):**
1. `prompts/recipe_review.md` + `recipe_review_default.md`.
2. `build_recipe_context` + `review_recipe` в `ai/services.py`.
3. Эндпоинт `POST /api/ai/recipe-review`.
4. Параметризовать `AiAssistant` (`defaultQuestion` + `ask`); обновить обёртки
   сессий; смонтировать в `RecipeDetail` + кнопка.

**Фаза B — AI-мастер:**
5. `prompts/recipe_wizard.md` + подстановка enum-схемы из `enums.py`.
6. `generate_profile` + enum-валидатор (реюз `ProfileIn`, при цикле — `schemas.py`).
7. Эндпоинт `POST /api/ai/recipe-wizard`.
8. Кнопка/панель «AI-мастер» в `RecipeEditor` + `applyProfile()` реюз для засева.
9. Мини-проверка: юнит на `generate_profile` с замоканным LLM-ответом (валидный +
   битый → ретрай) — один `test_*.py`, без фреймворочной обвязки.
