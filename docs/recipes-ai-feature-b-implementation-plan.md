# План реализации Фичи B: AI-мастер профиля

План рассчитан на младшую модель: задачи идут в порядке зависимостей, у каждого
шага есть точные файлы, ожидаемый результат и проверка. Исходные требования:
[recipes-ai-epic.md](./recipes-ai-epic.md), раздел «Фича B».

## 1. Цель и границы v1

На странице создания рецепта пользователь открывает AI-мастер, описывает варку
обычным текстом и получает заполненную, но **не сохранённую** форму. Пользователь
проверяет шаги и алерты и сохраняет черновик существующей кнопкой.

В v1:

- мастер доступен только для нового профиля BrewZilla;
- модель возвращает JSON, совместимый с `ProfileInput`;
- `profile_type_id` и `profile_type_name` берутся из текущей формы, а не из LLM;
- корневой `alerts` для BrewZilla всегда пустой: текущий редактор не показывает
  такие алерты; алерты варки создаются внутри подходящего шага;
- выполняется один исправляющий запрос к LLM после невалидного ответа;
- новые зависимости, отдельный маршрут страницы, стриминг и автосохранение не
  добавляются.

Не расширять v1 на Fermentation, General Temperature Control и Pill Hydrometer.
В текущем редакторе эти типы уже есть, но для них нужны другие допустимые поля и
правила. Кнопку показывать при `!isEdit && kind === 'brewzilla'`.

## 2. Проверенные факты текущего кода

- Фича A уже реализована через серверные беседы. Не возвращать старые эндпоинты
  `/api/ai/recipe-review` и не менять conversation flow.
- Схемы `ProfileIn`, `StepIn`, `AlertIn` пока находятся в
  `backend/features/profiles/router.py`.
- Канонические enum находятся в `backend/features/profiles/enums.py`.
- Общий OpenAI-compatible вызов — `_run_chat_completion()` в
  `backend/features/ai/services.py`; сейчас он не принимает `response_format`.
- `RecipeEditor` поддерживает четыре типа профиля. Для BrewZilla разрешены
  `Target`/`Ramp`, но не `FreeRise` и не gravity-условия.
- Программные `setState` не вызывают корневой `onChange`, поэтому после
  применения результата нужно явно вызвать `markDirty()`.
- Для BrewZilla UI редактирует алерты шагов, но не корневой `Profile.alerts`.
- Текущий error-блок скрыт, когда массив `issues` не пуст, из-за конструкции
  `issues ? ... : error ? ...`. Ошибку мастера нужно выводить независимо.

## 3. Целевой пользовательский flow

Панель встраивается в `RecipeEditor`, перед секцией «Основные данные», и
использует существующие классы `panel`, `field`, `btn-solid`, `error`.

Из проверенного через Playwright референса RAPT берём визуальную иерархию:

- крупный заголовок мастера и короткий поясняющий текст;
- явный номер шага и тонкий сегментированный progress bar;
- крупные selectable-карточки с названием и пояснением;
- недоступные варианты остаются видимыми, но приглушены и подписаны
  `Not yet available`;
- нижняя строка действий: `Cancel` слева, основной `Next` справа.

Не копировать боковую навигацию RAPT и preview-premium modal: они относятся к
порталу, а не к самому сценарию создания профиля. В локальном редакторе нет
смысла показывать четыре шага только ради сходства:

- устройство уже выбрано полем типа профиля;
- preset-переключатели не входят в контракт Фичи B и могут быть сформулированы
  пользователем в свободном описании;
- отдельный экран review дублирует будущую заполненную форму `RecipeEditor`;
- заполненный `RecipeEditor` и есть наш рабочий advanced builder.

Поэтому для Фичи B оставить один содержательный шаг с описанием, а progress bar
не добавлять: один сегмент не сообщает пользователю ничего полезного.

1. Новый рецепт по умолчанию имеет тип BrewZilla.
2. В заголовке страницы пользователь нажимает кнопку
   `AI-мастер` с иконкой `fa-wand-magic-sparkles`.
3. Открывается одна панель:
   - заголовок «Собрать профиль с AI»;
   - короткое пояснение, что результат заполнит форму и не сохранится сам;
   - `textarea` с примером из эпика;
   - основная кнопка «Собрать профиль»;
   - вторичная кнопка «Отмена».
4. Пока идёт запрос, textarea, кнопки панели и выбор типа профиля заблокированы;
   основная кнопка показывает «Собираем…».
5. После успеха панель закрывается, поля формы заполняются, форма становится
   `dirty`. Пользователь просматривает карточки шагов и нажимает существующую
   кнопку «Сохранить черновик».
6. После ошибки панель остаётся открытой с исходным описанием, форма не меняется,
   ошибка видна над подсказками о незаполненной форме.

Если форма уже содержит имя, описание, шаги или алерты, перед запуском показать
нативный `window.confirm`, что успешный результат заменит эти поля. Не очищать
форму до получения и полной подготовки валидного ответа.

### Полный подтверждённый flow RAPT

Маршрут `https://brew.rapt.io/automations/ai-wizard` открыт через Playwright.
Перед мастером показывается preview-premium modal, после подтверждения —
`AI Automation Wizard`, подзаголовок и экран `Step 1 of 4`.

**Step 1 — Pick the device you want an automation for.**

Карточки устройств:

- BrewZilla — доступен;
- Temperature Controller — `Not yet available`;
- Fermentation Chamber — `Not yet available`;
- Pill Hydrometer — `Not yet available`.

До выбора карточки `Next` disabled. Внизу находятся `Cancel` и `Next`. Это
подтверждает выбранную границу v1: генерировать только BrewZilla-профили.

**Step 2 — Tell us about your setup.**

Пять карточек-переключателей с пояснениями и дефолтами:

| Настройка | Дефолт | Смысл |
|---|---:|---|
| Use BLE Probe as control sensor | No | использовать BLE probe вместо встроенного датчика |
| Include temperature alerts | Yes | алерты промаха по температуре и готовности к кипу |
| Include a sparge step | Yes | шаг промывки при 78 °C после mash |
| Include a mash-out | Yes | пауза 10 минут при 78 °C |
| Add a whirlpool rest | No | пауза 15 минут при 80 °C после кипа |

`Back` слева, `Next` справа.

**Step 3 — Describe your ideal brew day.**

- пояснение предлагает указать стиль, mash schedule и особые шаги;
- необязательный `textarea` с label `Brew day notes`;
- лимит 500 символов и живой счётчик остатка;
- placeholder:
  `Hazy IPA, single-step mash at 67 °C for 75 min, 90 min boil, whirlpool at
  78 °C for 20 min.`;
- даже с пустым полем `Next` доступен.

**Step 4 — Ready to generate.**

Read-only summary в одной карточке:

- Device;
- BLE Probe;
- Alerts;
- Sparge step;
- Mash out;
- Whirlpool;
- Notes.

Действия: `Back` и `Generate`. Во время запроса обе кнопки блокируются, рядом
появляется `Generating your automation…`.

**Результат генерации.**

RAPT открывает modal `Your Starter Automation`:

- название и badge типа устройства;
- компактный список шагов: название, температура, длительность/условие,
  мощность;
- текстовое описание выбранных параметров;
- `Close` и `Open in Builder`.

На момент проверки `Open in Builder` disabled, а информационный блок говорит,
что открытие и сохранение в full Profile Builder появится позже. В нашей Фиче B
этот разрыв закрывает существующий `RecipeEditor`: после успешной генерации он
сразу показывает все шаги для проверки и только пользователь запускает
сохранение.

Контрольный прогон RAPT получил notes с явным mash `66 °C`, но в preview показал
`65 °C`. Для нашей реализации это нежелательно: промпт обязан сохранять явно
указанные пользователем числа без оптимизации и округления.

## 4. Контракт API

Добавить endpoint:

```text
POST /api/ai/recipe-wizard
Content-Type: application/json

{ "description": "..." }
```

Ограничения запроса:

```python
class RecipeWizardRequest(BaseModel):
    description: str = Field(min_length=8, max_length=4000)
```

Успешный ответ — объект формы:

```json
{
  "name": "APA 23 л",
  "description": "Одноступенчатое затирание и кип 60 минут",
  "public": false,
  "profile_type_id": null,
  "profile_type_name": null,
  "steps": [],
  "alerts": []
}
```

Статусы:

- `200` — валидный нормализованный профиль;
- `422` — описание прошло входную проверку, но оба ответа модели не удалось
  привести к схеме;
- `502` — OpenAI-compatible API вернул ошибку;
- `503` — LLM недоступна.

Не возвращать клиенту сырой ответ модели и внутренний traceback.

## 5. Backend: реализация по шагам

### Шаг B1. Подготовить системный промпт

Создать `backend/prompts/recipe_wizard.md`.

Промпт должен:

- требовать только один JSON-объект без markdown и пояснений;
- объяснять, что это профиль BrewZilla;
- запрещать `FreeRise`, gravity-поля и gravity-алерты;
- задавать `public=false`, `profile_type_id=null`,
  `profile_type_name=null`, корневой `alerts=[]`;
- требовать `order` от нуля, хотя backend всё равно его нормализует;
- объяснять, что `length` хранится в целых секундах;
- использовать минимальный дефолт `controlType="Target"`; для температурной
  выдержки запускать таймер по достижении цели через
  `durationType="Temperature"`;
- запрещать выдумывать ингредиенты, температуры и паузы, кроме минимально
  необходимого каркаса;
- копировать явно заданные пользователем температуры, длительности, мощности и
  моменты алертов точно, без округления и замены на «более разумные» значения;
- объяснять семантику step-alert `Duration`: `length` — время **от запуска
  таймера шага**, а не время до конца. Например, «за 15 минут до конца
  60-минутного кипа» означает `length=2700`.

Не хардкодить списки enum в файле промпта. В `ai/services.py` собрать блок
контракта из констант `profiles/enums.py` и дописать его к тексту промпта.
Передать:

- `CONTROL_TYPES`, `END_TYPES`, `DURATION_TYPES`;
- `ALERT_TRIGGERS`, `VALUE_OPERATORS`;
- доступные `*_LABELS`;
- `STEP_NAME_MIN_LEN`, `STEP_NAME_MAX_LEN`, `STEP_REQUIRED_FIELDS`;
- отдельное указание разрешённых для BrewZilla подмножеств.

Проверка: в тесте найти в фактически отправленном system message значения
`Target`, `Ramp`, `Duration`, `StepStart`, `GreaterThan`.

### Шаг B2. Разрешить JSON mode в общем LLM-вызове

В `backend/features/ai/services.py` добавить к `_run_chat_completion()` один
необязательный keyword-only аргумент:

```python
response_format: dict | None = None
```

Если он передан, добавить его в `request`. Существующие вызовы бесед не менять:
для них аргумент по умолчанию `None`, а значит набор параметров запроса останется
прежним.

Мастер вызывает helper со строгой JSON Schema:

```python
response_format={
    "type": "json_schema",
    "json_schema": {"name": "recipe_wizard_profile", "strict": True, "schema": {...}},
}
tools=None
current_session_id=None
temperature=LLM_TEMPERATURE
```

### Шаг B3. Добавить строгую нормализацию и проверку

В `backend/features/ai/services.py` добавить небольшую функцию
`_validate_generated_profile(raw: str) -> dict`.

Порядок внутри функции:

1. `json.loads(raw)`; корень обязан быть объектом.
2. `ProfileIn.model_validate(data)`.
3. Дополнительные проверки, которых нет в текущем `ProfileIn`:
   - имя профиля длиной 4–50 символов после `strip`;
   - минимум один шаг;
   - имя каждого шага длиной `STEP_NAME_MIN_LEN..STEP_NAME_MAX_LEN`;
   - `controlType` только `Target` или `Ramp`;
   - `endType` только `Duration`, `Temperature` или `Manual`;
   - `durationType` принадлежит `DURATION_TYPES`;
   - непустой `operator` принадлежит `VALUE_OPERATORS`;
   - у `Target`/`Ramp` есть конечная числовая `temperature`;
   - если `controlType == "Ramp"` или `endType == "Duration"`, `length` —
     положительное целое число секунд;
   - trigger каждого step-alert входит в
     `StepStart`, `StepEnd`, `Duration`, `Temperature`;
   - у `Duration`-алерта есть неотрицательный целый `length`, у
     `Temperature`-алерта — `temperature`;
   - текст каждого алерта непустой;
   - `steps[].alerts` и корневой `alerts` имеют правильную структуру.
4. Нормализация:
   - `name` и `description` обрезать по краям;
   - `order` каждого шага заменить его индексом;
   - `public=false`;
   - `profile_type_id=null`, `profile_type_name=null`;
   - корневой `alerts=[]`;
   - вернуть `profile.model_dump()`, а не исходный объект модели. Так лишние
     придуманные ключи не попадут на фронтенд.

Для проверки конечного числа использовать `math.isfinite`. Не создавать новый
набор Pydantic-моделей только для LLM.

Импортировать `ProfileIn` из `features.profiles.router` напрямую. Если при
реальном запуске возникнет цикл импорта, только тогда перенести `AlertIn`,
`StepIn`, `ProfileIn` без изменений в `features/profiles/schemas.py` и
импортировать их из router и AI service. Не делать этот рефактор заранее.

### Шаг B4. Реализовать один ретрай

Добавить:

```python
async def generate_profile(description: str) -> dict:
    ...
```

Алгоритм:

1. Первый запрос: system prompt + schema block, user description.
2. Попытаться вызвать `_validate_generated_profile`.
3. При `JSONDecodeError`, `ValidationError`, `TypeError` или `ValueError`
   добавить в сообщения:
   - ответ ассистента как `assistant`;
   - короткий user message с текстом ошибки и просьбой вернуть целиком
     исправленный JSON.
4. Сделать ровно второй запрос с тем же `response_format`.
5. Если второй ответ невалиден, поднять единый `ValueError(
   "Модель не смогла собрать корректный профиль"
   )`.

Не включать полный сырой ответ модели в исключение или HTTP detail. Для ретрая
передавать только конкретное сообщение валидатора.

### Шаг B5. Подключить endpoint

В `backend/features/ai/router.py`:

- импортировать `generate_profile`;
- добавить `RecipeWizardRequest`;
- добавить `POST /api/ai/recipe-wizard`;
- `ValueError` преобразовать в `HTTPException(422, str(error))`;
- `APIConnectionError` и `OpenAIError` пропускать через существующий
  `_raise_ai_error`.

Не менять существующие conversation endpoints.

## 6. Backend: офлайн-проверки

Расширить существующий `backend/scripts/test_ai.py`; отдельную тестовую
инфраструктуру не создавать.

Добавить четыре сценария на замоканном `AsyncOpenAI`:

1. Валидный JSON:
   - возвращается `ProfileInput`-совместимый dict;
   - `order` исправлен на `0..n-1`;
   - типы профиля равны `null`, `public=false`, корневой `alerts=[]`;
   - в запросе есть строгий `response_format` с `type="json_schema"`.
2. Первый ответ невалиден, второй валиден:
   - выполнено два completion-вызова;
   - второй запрос содержит первый ответ и причину ошибки.
3. Оба ответа невалидны:
   - наружу выходит безопасный `ValueError`.
4. Неверный enum (`FreeRise` или gravity trigger) отклоняется, даже если JSON
   синтаксически валиден.

В валидном fixture обязательно проверить алерт:

```json
{
  "trigger": "Duration",
  "length": 2700,
  "alertText": "Добавить хмель — до конца кипа 15 минут"
}
```

Команды после backend-части:

```powershell
cd backend
uv run ruff format .
uv run ruff check . --fix
uv run python scripts/test_ai.py
uv run ruff format --check .
uv run ruff check .
```

## 7. Frontend: реализация по шагам

### Шаг F1. Добавить API-функцию

В `frontend/src/api/ai.ts`:

```ts
export const generateProfile = (description: string, signal?: AbortSignal) =>
  post<ProfileInput>(
    '/api/ai/recipe-wizard',
    { description },
    { signal },
  )
```

Импортировать `ProfileInput` через `@/types`. Новый response type не создавать:
ответ уже совпадает с существующим `ProfileInput`.

### Шаг F2. Добавить состояние панели

В `frontend/src/pages/RecipeEditor.tsx` добавить только:

```ts
const [wizardOpen, setWizardOpen] = useState(false)
const [wizardDescription, setWizardDescription] = useState('')
const [wizardLoading, setWizardLoading] = useState(false)
```

Использовать общий `error` для ошибки запроса. Отдельный error-state мастера не
нужен.

Кнопку `AI-мастер` разместить в `.page-head` и показывать только при
`!isEdit && kind === 'brewzilla'`. При выборе другого типа закрыть панель.

### Шаг F3. Выделить применение профиля

Добавить локальный helper, который **сначала целиком готовит** новое состояние,
а затем вызывает setters:

```ts
const applyGeneratedProfile = (profile: ProfileInput) => {
  const nextSteps = profile.steps
    .slice()
    .sort((a, b) => a.order - b.order)
    .map((step, order) => ({ ...step, order, _uid: uid() }))

  setName(profile.name ?? '')
  setDescription(profile.description ?? '')
  setSteps(nextSteps)
  setAlerts(profile.alerts)
  setEditing(null)
  markDirty()
}
```

Не менять `typeId`, `isPublic` и выбранный `profile_type_name`: сервер специально
возвращает тип `null`, а пользователь мог уже изменить публичность.

Существующий `useEffect(existing)` не обязан использовать этот helper: он
работает только в edit mode и не должен помечать загруженную форму как dirty.
Не объединять эти два пути ценой флагов и условной логики.

### Шаг F4. Реализовать submit мастера

Функция submit:

1. Очистить `error`.
2. Проверить `wizardDescription.trim().length >= 8`.
3. Если форма непустая, запросить подтверждение замены.
4. Установить loading, вызвать `generateProfile(trimmedDescription)`.
5. Только после полного ответа вызвать `applyGeneratedProfile`.
6. Закрыть панель после успеха.
7. В `catch` установить читаемую ошибку и не вызывать ни один form setter.
8. В `finally` снять loading.

На время запроса заблокировать переключатели типа профиля, иначе BrewZilla-ответ
может примениться к другому типу.

### Шаг F5. Исправить порядок баннеров

В sticky action bar показывать `error` отдельным условием, а `issues` — следующим.
Ошибка мастера должна быть видна даже тогда, когда пустая форма одновременно
имеет список `issues`.

Не очищать error автоматически на обычном `onChange`: достаточно очищать его
при новом submit мастера и при `save()`.

### Шаг F6. Добавить минимальные стили

В `frontend/src/index.css` добавить только недостающую раскладку:

- промежуток между текстом и кнопками панели;
- flex/wrap для кнопок;
- мобильное растягивание основной кнопки при необходимости.

Переиспользовать существующие цвета, поля, панели, spinner/disabled-состояния.
Не добавлять CSS-модуль, компонентную библиотеку или отдельный modal.

## 8. Frontend-проверки

Ручной smoke-check:

1. `/recipes/new`, BrewZilla: кнопка видна.
2. Edit route: кнопки нет.
3. Fermentation/General/Pill: кнопки нет; открытая панель закрывается после
   смены типа.
4. Пустое или слишком короткое описание не отправляется.
5. Во время запроса повторный submit и смена типа невозможны.
6. Успех заполняет имя, описание, шаги и step-alerts; тип остаётся BrewZilla;
   форма помечена dirty; сетевой запрос сохранения не выполняется.
7. Ошибка сохраняет прежние поля и видна одновременно с validation issues.
8. Шаги открываются в существующем modal и редактируются как вручную созданные.
9. На узком экране панель не даёт горизонтального скролла.

Команды:

```powershell
cd frontend
npm run fmt
npm run fmt:check
npm run build
npm run lint
```

## 9. Рекомендуемый порядок одного рабочего прохода

1. `recipe_wizard.md`.
2. JSON mode в `_run_chat_completion`.
3. `_validate_generated_profile` и `generate_profile`.
4. Четыре offline-сценария и backend-проверки.
5. Endpoint.
6. `generateProfile` на фронтенде.
7. Панель, submit и атомарное применение результата.
8. Баннеры и минимальный CSS.
9. Frontend-проверки и ручной smoke-check.

После каждого пункта не делать промежуточный commit без запроса пользователя.

## 10. Definition of Done

- AI-мастер доступен только при создании BrewZilla-профиля.
- В LLM уходит runtime-контракт из `enums.py` и включён JSON mode.
- Невалидные JSON, enum, обязательные поля и нечисловые значения отклоняются.
- Есть не больше одного ретрая.
- Ответ нормализован через `ProfileIn`, порядок шагов пересчитан.
- Модель не выбирает тип профиля и не создаёт скрытые корневые BrewZilla-алерты.
- Форма меняется только после полностью успешного ответа и не сохраняется
  автоматически.
- Ошибка не портит форму и всегда видна.
- Backend offline-check, ruff, frontend format/build/lint проходят.
- UTF-8/Cyrillic сохранены; `data/rapt.db` и секреты не изменены.
