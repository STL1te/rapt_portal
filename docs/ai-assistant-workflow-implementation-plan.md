# План реализации серверного workflow AI-ассистентов

## 1. Цель

Перевести все три существующих AI-ассистента:

- анализ сессии варки;
- анализ сессии брожения;
- проверку рецепта;

с клиентской истории на серверные беседы. После реализации:

1. беседа привязана к конкретной сессии или рецепту и переживает закрытие окна,
   обновление страницы и повторный вход;
2. frontend отправляет только идентификатор беседы и новую реплику;
3. backend сам загружает историю, каждый раз строит свежий контекст объекта и
   вызывает OpenAI-совместимую LLM;
4. успешно завершённые пары `user`/`assistant` сохраняются в БД;
5. старые сообщения остаются в БД, но в контекст модели попадают summary и
   ограниченный хвост истории;
6. tool-calls остаются временной внутренней частью одного вызова модели и не
   дают модели произвольного доступа к БД, URL или файловой системе.

План основан на `docs/ai-workflow-by-chatgpt.md`, но адаптирован к текущим
FastAPI, SQLAlchemy/Alembic, React и OpenAI-compatible API проекта.

## 2. Что сейчас неправильно

Текущий flow находится в:

- `backend/features/ai/router.py`;
- `backend/features/ai/services.py`;
- `frontend/src/components/AiAssistant.tsx`;
- `frontend/src/api/ai.ts`;
- `frontend/src/types/ai.ts`;
- `backend/scripts/test_ai.py`.

Основные проблемы:

1. `AiAssistant` хранит историю только в React state. После перезагрузки страницы
   беседа исчезает.
2. Каждый запрос принимает `history` от браузера. Backend доверяет клиенту роли и
   содержимое прежних сообщений вместо загрузки собственной канонической истории.
3. Контекст объекта, дефолтная инструкция и вопрос склеены в одно `user`-сообщение.
   Модели сложнее отличить актуальные данные приложения от пользовательского ввода.
4. Ограничение `history` до 12 сообщений просто отрезает ранний смысл разговора;
   summary отсутствует.
5. Backend не имеет `conversation_id`, поэтому не может восстановить беседу,
   защитить привязку к объекту или централизованно управлять контекстом.
6. Дефолтные отображаемые вопросы продублированы в Python и TypeScript.
7. При неуспешном запросе UI оставляет локальную реплику, которой нет на сервере,
   и следующий запрос может передать её как будто она была частью состоявшегося
   разговора.
8. Старый ответ может содержать уже неактуальную плотность или температуру; сейчас
   нет явного правила, что новый контекст приоритетнее истории.

Существующие сильные части нужно сохранить: промпты из UTF-8 файлов, компактный
контекст с выборкой телеметрии, разные дефолтные инструкции для активных и
завершённых сессий, OpenAI-compatible клиент и белый список tools.

## 3. Архитектурные решения

### 3.1. Одна беседа на один объект

В первой версии поддержать ровно одну беседу для каждой пары
`(subject_type, subject_id)`:

| `subject_type` | Модель объекта | Ассистент |
|---|---|---|
| `brew_session` | `BrewSession` | анализ варки |
| `fermentation_session` | `HydrometerSession` | анализ брожения |
| `recipe` | `Profile` | проверка рецепта |

Уникальность обеспечить в БД. Выбор нескольких чатов, заголовки бесед,
архивирование и кнопка «Новый чат» пока не нужны: текущий UI таких сценариев не
имеет.

В проекте нет пользователей и авторизации, поэтому не добавлять фиктивный
`user_id`. Если появится многопользовательский режим, уникальный ключ нужно будет
расширить до `(user_id, subject_type, subject_id)`.

### 3.2. Источник истины — backend

Frontend больше не передаёт `history`, `kind`, `completed` или дефолтную
инструкцию. После открытия беседы он работает только с ответами backend.

Backend по сохранённым `subject_type` и `subject_id`:

- выбирает системный промпт;
- проверяет наличие объекта;
- определяет, активна ли сессия;
- выбирает отображаемый дефолтный вопрос и внутреннюю расширенную инструкцию;
- строит свежий контекст;
- разрешает нужный набор tools.

Так клиент не может подменить тип беседы или подсунуть модели выдуманную историю.

### 3.3. Один системный блок

Для совместимости с локальными моделями формировать одно `system`-сообщение:

```text
[ROLE AND RULES]
содержимое существующего prompt-файла

[CURRENT UTC TIME]
...

[CURRENT SUBJECT CONTEXT]
Актуальные данные ниже имеют приоритет над числами и состояниями,
упомянутыми в истории беседы.
<current_session_context>...</current_session_context>

[CONVERSATION SUMMARY]
...если summary уже существует...
```

После него передавать последние сохранённые `user`/`assistant` сообщения и новую
реплику `user`. Данные приложения не смешивать с пользовательским текстом.

Для рецепта оставить тег `<recipe_context>`, для сессий —
`<current_session_context>`. Данные внутри тегов прямо объявить справочными
данными, а не инструкциями.

### 3.4. Атомарный успешный ход

Новая пользовательская реплика и ответ ассистента должны сохраняться одной
транзакцией только после успешного завершения LLM-вызова:

1. проверить беседу и входной текст;
2. загрузить сохранённую историю;
3. построить свежий контекст;
4. вызвать модель и завершить возможные tool-calls;
5. одной транзакцией добавить `user` и `assistant`, обновить `updated_at`;
6. вернуть обе канонические записи frontend.

Если LLM недоступна, не оставлять в БД «висящее» `user`-сообщение без ответа.
Frontend сохраняет текст в поле ввода и позволяет повторить запрос.

Это минимальная согласованная модель для локального однопользовательского UI.
Очередь заданий, статусы сообщений, distributed lock и автоматические повторы
здесь не нужны.

### 3.5. Tool-calls не являются сообщениями пользователя

В `ai_messages` сохранять только финальные роли `user` и `assistant`.
`assistant` с `tool_calls` и ответы роли `tool` существуют только в локальном
массиве `messages` текущего вызова `assess`. Это:

- не засоряет отображаемую историю техническими данными;
- не сохраняет большие контексты чужих сессий;
- оставляет действующий whitelist из `TOOLS` единственной точкой доступа модели.

## 4. Схема данных

### 4.1. SQLAlchemy-модели

В `backend/core/db.py` добавить две модели.

`AiConversation`:

| Поле | Тип | Правило |
|---|---|---|
| `id` | `String` | UUID строкой, primary key |
| `subject_type` | `String` | одно из трёх допустимых значений, index |
| `subject_id` | `String` | ID сессии/профиля, index |
| `prompt_version` | `String` | версия prompt-контракта, например `v1` |
| `summary` | `Text`, nullable | summary старой части беседы |
| `summary_through_message_id` | `Integer`, nullable | последний message id, включённый в summary |
| `created_at` | `DateTime` | naive UTC |
| `updated_at` | `DateTime` | naive UTC, index |

Добавить `UniqueConstraint("subject_type", "subject_id",
name="uq_ai_conversation_subject")`.

`AiMessage`:

| Поле | Тип | Правило |
|---|---|---|
| `id` | `Integer` | autoincrement primary key, задаёт порядок |
| `conversation_id` | `String` | FK на `ai_conversations.id`, index |
| `role` | `String` | только `user` или `assistant` |
| `content` | `Text` | непустой текст |
| `created_at` | `DateTime` | naive UTC |

Добавить DB check constraints для допустимых `subject_type` и `role`.
`token_count`, title, hidden messages и отдельную таблицу turns не добавлять:
текущий продукт их не использует.

Полиморфный `subject_id` нельзя корректно связать одним FK сразу с тремя
таблицами. Поэтому наличие объекта проверяет сервис при открытии беседы и каждом
новом ходе. Не добавлять три nullable FK-колонки.

Все новые timestamps создавать через маленький локальный `_utcnow()` с
`datetime.now(timezone.utc).replace(tzinfo=None)`, сохраняя принятую в проекте
нормализацию SQLite/PostgreSQL `DateTime`.

### 4.2. Alembic

Создать следующую ревизию после `20260722_03`:

`backend/alembic/versions/20260723_04_ai_conversations.py`.

`upgrade()`:

1. создать `ai_conversations`;
2. создать индексы и unique constraint;
3. создать `ai_messages` с FK и индексом;
4. создать check constraints.

`downgrade()` удаляет сначала `ai_messages`, затем `ai_conversations`.

Не изменять runtime БД вручную и не использовать `Base.metadata.create_all()` в
приложении: миграции остаются deploy step, как указано в `backend/app.py`.

## 5. Новые HTTP-контракты

### 5.1. Открыть или создать беседу

```http
POST /api/ai/conversations/open
Content-Type: application/json
```

```json
{
  "subject_type": "fermentation_session",
  "subject_id": "..."
}
```

Ответ:

```json
{
  "id": "conversation-uuid",
  "subject_type": "fermentation_session",
  "subject_id": "...",
  "model": "configured-model",
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "Как идёт брожение?",
      "created_at": "2026-07-23T12:00:00"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "...",
      "created_at": "2026-07-23T12:00:10"
    }
  ]
}
```

Поведение:

1. проверить `subject_type` и существование объекта;
2. найти беседу по unique key или создать пустую;
3. если сообщения уже есть — вернуть их без LLM-вызова;
4. если беседа пуста — выполнить начальный ход:
   - сохранить как пользовательский текст короткий `DEFAULT_QUESTIONS` или
     `RECIPE_REVIEW_DEFAULT_QUESTION`;
   - модели передать соответствующую расширенную default instruction;
   - сохранить пару сообщений и вернуть полную беседу;
5. если начальный LLM-вызов упал, оставить беседу пустой и вернуть существующий
   502/503. Следующее открытие повторит bootstrap.

Unique constraint должен быть последней защитой от двух бесед при двух почти
одновременных открытиях. При конфликте перечитать уже созданную запись, а не
возвращать 500.

Ошибки:

- 404 — объект не найден;
- 422 — неизвестный `subject_type` или невалидный ID;
- 502 — OpenAI-compatible API вернул ошибку;
- 503 — LLM недоступна.

### 5.2. Отправить следующую реплику

```http
POST /api/ai/conversations/{conversation_id}/messages
Content-Type: application/json
```

```json
{
  "content": "Можно уже делать cold crash?"
}
```

Ответ:

```json
{
  "user_message": {
    "id": 3,
    "role": "user",
    "content": "Можно уже делать cold crash?",
    "created_at": "..."
  },
  "assistant_message": {
    "id": 4,
    "role": "assistant",
    "content": "...",
    "created_at": "..."
  },
  "model": "configured-model"
}
```

Ограничения оставить эквивалентными текущим: trim, непустой текст, максимум
2000 символов. Роль с клиента не принимать.

### 5.3. Старые endpoints

После перевода всех трёх страниц удалить:

- `POST /api/ai/assessments`;
- `POST /api/ai/recipe-review`;
- request-модели с `history`;
- frontend-функции `assessSession` и `reviewRecipe`.

Внешняя обратная совместимость для локального портала не заявлена. Не держать
два параллельных протокола и не писать адаптер, который снова доверяет истории
браузера.

## 6. Backend: структура и задачи

### 6.1. `backend/features/ai/services.py`

Сохранить в этом модуле простую реализацию без новых repository/factory классов.
Добавить тип:

```python
SubjectType = Literal["brew_session", "fermentation_session", "recipe"]
```

И небольшие функции:

1. `_subject_exists(db, subject_type, subject_id) -> bool`;
2. `_subject_settings(db, conversation) -> SubjectSettings` либо обычный dict,
   содержащий:
   - system prompt;
   - свежий context;
   - displayed default question;
   - model default instruction;
   - completed;
   - tools или `None`;
3. `_load_conversation_messages(db, conversation_id)`;
4. `_build_model_messages(system_prompt, context, summary, history,
   user_content)`;
5. `_run_chat_completion(...)` — общий OpenAI-compatible tool loop;
6. `open_conversation(subject_type, subject_id)`;
7. `send_conversation_message(conversation_id, content)`;
8. `_maybe_summarize_conversation(...)`.

Не создавать интерфейсы, dependency-injection container или отдельный generic
LLM SDK wrapper. `assess` и `review_recipe` сейчас отличаются главным образом
промптом, контекстом и tools; общий `_run_chat_completion` должен устранить
дублирование двух `AsyncOpenAI(...)` блоков.

`build_context`, `build_recipe_context`, `_sample`, `_run_tool`, `TOOLS` и
существующие prompt constants переиспользовать.

Для сессионных tools текущий `session_id` получать только из conversation subject.
Для `recipe` передавать `tools=None` и вообще не включать `tools`/`tool_choice` в
API-вызов.

### 6.2. Построение model messages

Для обычного follow-up:

```python
[
    {"role": "system", "content": combined_system_and_fresh_context},
    # при наличии summary оно уже находится в system content
    *recent_messages_from_db,
    {"role": "user", "content": stripped_user_content},
]
```

Для bootstrap в сохранённую историю записывается короткий отображаемый вопрос,
но последним сообщением модели становится расширенная default instruction. Это
единственное место, где сохранённый `content` и model `content` намеренно
различаются.

`_FOLLOW_UP_HINT` можно оставить частью последнего `user`-сообщения только для
follow-up, но не добавлять к сохранённому тексту. Более чистый вариант — перенести
его в общий system block. Выбрать второй вариант, чтобы model message пользователя
совпадал с реально введённым текстом.

Нельзя:

- брать историю из HTTP request;
- повторно добавлять текущий вопрос и в history, и последним сообщением;
- сохранять system prompt, context JSON или tool results в `ai_messages`;
- включать battery/RSSI в brewing context;
- делать старый ответ источником текущего состояния.

### 6.3. Tool loop

Вынести существующий цикл до `_MAX_TOOL_ROUNDS` в общий
`_run_chat_completion(messages, tools, current_session_id, temperature)`.

Сохранить правила:

- `tool_choice="auto"` только когда tools переданы;
- JSON arguments парсятся backend;
- выполняются только имена из `_run_tool`;
- `LookupError` и `JSONDecodeError` возвращаются модели как безопасный
  `{"error": ...}`;
- после исчерпания лимита возвращается текущая русская ошибка;
- финально сохраняется только текстовый ответ модели.

Дополнительно валидировать, что `get_session_context` получает непустой
`session_id`; неизвестная сессия должна дать tool error, а не уронить endpoint.

### 6.4. Температура модели

Определять первый ход по отсутствию сохранённых сообщений, а не по присланной
истории:

- bootstrap: `LLM_TEMPERATURE`;
- follow-up: `LLM_CHAT_TEMPERATURE`.

### 6.5. Summary длинной беседы

Не добавлять зависимость на tokenizer. Для первой версии использовать лимиты по
числу сообщений:

```python
_RECENT_MESSAGES = 12
_SUMMARY_TRIGGER_MESSAGES = 24
```

Перед follow-up:

1. загрузить сообщения после `summary_through_message_id`;
2. если их не больше 24, использовать их все вместе с текущим сохранённым
   summary; нельзя молча выбросить сообщения, которые ещё не вошли в summary;
3. если больше 24:
   - взять старую часть, оставив последние 12 дословно;
   - отправить старое summary плюс эту часть отдельным коротким LLM-запросом;
   - потребовать фактическое русское резюме: решения, предпочтения пользователя,
     оговорки и открытые вопросы; текущие показания не объявлять актуальными;
   - сохранить новый `summary` и id последнего вошедшего сообщения;
4. собрать основной запрос из нового summary и последних 12 сообщений;
5. исходные сообщения не удалять.

Если создание summary не удалось, залогировать warning и продолжить основной
ответ с последними 24 сообщениями. Ошибка вспомогательного summary не должна
ломать пользовательский вопрос или приводить к неограниченному контексту.

Summary делать только при достижении порога, а не на каждом ходе. Отдельный
prompt-файл `backend/prompts/conversation_summary.md` использовать для правил
суммаризации.

### 6.6. `backend/features/ai/router.py`

Заменить две старые request-модели на:

- `OpenConversationRequest`;
- `ConversationMessageRequest`.

Добавить два endpoint из раздела 5. Pydantic должен валидировать enum и длины до
вызова сервиса. Существующее преобразование `APIConnectionError` в 503 и
`OpenAIError` в 502 сохранить в одном маленьком helper или в обоих endpoint без
новой exception hierarchy.

Сервисные `LookupError`:

- неизвестный subject/conversation → 404;
- повреждённая привязка беседы к удалённому объекту → 404 с безопасным текстом.

Не отдавать frontend сырой exception LLM или содержимое tool-call.

## 7. Frontend: структура и задачи

### 7.1. Типы

В `frontend/src/types/ai.ts` заменить старые request types на:

```ts
export type AiSubjectType = 'brew_session' | 'fermentation_session' | 'recipe'

export type AiMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export type AiConversation = {
  id: string
  subject_type: AiSubjectType
  subject_id: string
  model: string
  messages: AiMessage[]
}

export type AiTurn = {
  user_message: AiMessage
  assistant_message: AiMessage
  model: string
}
```

Удалить `AiAssessmentRequest`, `RecipeReviewRequest` и клиентский history.

### 7.2. API

В `frontend/src/api/ai.ts` оставить две функции:

```ts
openAiConversation(subject_type, subject_id)
sendAiMessage(conversationId, content)
```

Удалить `SESSION_DEFAULT_QUESTIONS`, `sessionAssistant` и `recipeAssistant`.
Отображаемый default question теперь приходит в первом сохранённом сообщении от
backend, поэтому зеркалить Python constants больше не нужно.

### 7.3. `AiAssistant`

Новый минимальный props-контракт:

```ts
type Props = {
  open: boolean
  onClose: () => void
  subjectType: AiSubjectType
  subjectId: string
}
```

Поведение компонента:

1. при первом `open=true` или смене subject вызвать `openAiConversation`;
2. показать отдельный loading начальной загрузки;
3. заменить локальные messages каноническим массивом ответа;
4. повторное закрытие/открытие можно обслужить из state, но после remount или
   reload всегда снова вызвать `open`; backend вернёт сохранённую историю без
   повторной начальной оценки;
5. при отправке:
   - trim и проверить текст;
   - сохранить копию текста;
   - отключить composer;
   - можно показать временную user bubble без фиктивного server id;
   - вызвать `sendAiMessage`;
   - заменить временную bubble на `user_message` и добавить
     `assistant_message`;
6. при ошибке убрать временную bubble, восстановить текст в textarea и показать
   текущий error banner;
7. не передавать локальные messages в API;
8. сохранить существующие markdown, fullscreen, swipe-to-close, Enter/Shift+Enter
   и auto-scroll.

Удалить `started` как источник истины: его текущее значение не связано ни с
subject, ни с серверной беседой. Использовать `conversation?.id` и effect
dependencies.

Защититься от ответа старого запроса после смены subject: в cleanup effect
использовать `AbortController` либо булевый `cancelled`, чтобы старый response не
перезаписал новый чат. Для этого удобно добавить необязательный `signal` в
`get/post` из `frontend/src/api/client.ts`; новой библиотеки не нужно.

### 7.4. Страницы

Заменить adapters:

- `BrewSessionPage.tsx`:
  `subjectType="brew_session"`, `subjectId={s.id}`;
- `HydrometerSessionPage.tsx`:
  `subjectType="fermentation_session"`, `subjectId={s.id}`;
- `RecipeDetail.tsx`:
  `subjectType="recipe"`, `subjectId={data.id}`.

Существующие `key={id}`, кнопки открытия и подписи оставить.

## 8. Порядок реализации для младшей модели

Каждый этап должен завершаться работающей проверкой до перехода к следующему.

### Этап 1. Модели и миграция

1. Добавить `AiConversation` и `AiMessage` в `core/db.py`.
2. Добавить Alembic revision.
3. Проверить имена таблиц, constraints, индексы, порядок downgrade и naive UTC.
4. Не менять существующие таблицы и runtime data.

Готово, когда новая схема создаётся миграцией и backend lint проходит.

### Этап 2. Чистая сборка prompt и общий LLM loop

1. Отделить system/current context от user content.
2. Объединить дублированные LLM-вызовы сессии и рецепта.
3. Сохранить работу tools только для сессий.
4. Сохранить разные temperature для bootstrap/follow-up.
5. Дополнить offline assertions в `scripts/test_ai.py`.

Готово, когда существующий tool-call тест проходит, а тест явно доказывает, что
актуальный context находится в system block и введённый вопрос остаётся отдельным
последним `user` message.

### Этап 3. Conversation service и endpoints

1. Реализовать поиск/создание беседы.
2. Реализовать bootstrap только для пустой беседы.
3. Реализовать атомарное сохранение пары сообщений.
4. Добавить новые API routes и сериализацию timestamps.
5. Добавить проверки 404/422/502/503.
6. Пока оставить старые endpoints, чтобы frontend продолжал собираться во время
   этого этапа.

Готово, когда backend-тесты подтверждают сохранение и повторное открытие без
второго LLM-вызова.

### Этап 4. Перевод frontend

1. Обновить TS types и API.
2. Перевести `AiAssistant` на server conversation.
3. Перевести три страницы.
4. Проверить восстановление текста после ошибки и смену subject.
5. Удалить adapters и дубли default questions.

Готово, когда build/lint проходят, а reload страницы восстанавливает историю.

### Этап 5. Удаление legacy API

1. Убедиться через `rg`, что старые функции и types больше не вызываются.
2. Удалить два старых endpoint и request history models.
3. Не оставлять compatibility shim.

Готово, когда в frontend отсутствует поле `history` в AI-запросах.

### Этап 6. Summary

1. Добавить `conversation_summary.md`.
2. Реализовать threshold, накопительное summary и marker id.
3. При ошибке summary продолжать с recent messages.
4. Дополнить offline test сценарием длинной беседы.

Готово, когда старые сообщения остаются в БД, в model request передаются summary
и ровно ограниченный хвост, а повторно суммаризированные сообщения не попадают в
следующее summary второй раз.

## 9. Изменения в `backend/scripts/test_ai.py`

Файл должен остаться запускаемым через:

```powershell
uv run python scripts/test_ai.py
```

Не добавлять pytest только ради этого изменения. Расширить текущие mock clients и
assertions следующими сценариями:

1. `_sample` по-прежнему исключает battery/RSSI.
2. Bootstrap:
   - использует `LLM_TEMPERATURE`;
   - сохраняет короткий вопрос;
   - отправляет модели расширенную default instruction.
3. Follow-up:
   - использует `LLM_CHAT_TEMPERATURE`;
   - берёт history в правильном порядке из БД;
   - имеет один system block со свежим context;
   - последним идёт только новый `user` text.
4. Tool-call:
   - `search_sessions` вызывает `_run_tool`;
   - tool result возвращается модели;
   - сохраняется только финальный assistant text.
5. Recipe:
   - не отправляет `tools` и `tool_choice`;
   - использует `<recipe_context>`.
6. Persistence:
   - первое `open` создаёт ровно два сообщения;
   - второе `open` возвращает те же сообщения и не вызывает LLM;
   - успешный follow-up добавляет ровно два сообщения;
   - LLM exception не добавляет ни одного из двух сообщений.
7. Fresh data:
   - после изменения тестового context следующий follow-up получает новое
     значение, хотя в старом assistant message есть прежнее.
8. Summary:
   - после порога старые сообщения входят в summary один раз;
   - основной запрос получает summary плюс последние 12;
   - ошибка summarizer не отменяет основной ответ.
9. UTF-8:
   - русский вопрос и ответ сохраняются и читаются без искажения.

Для persistence-тестов использовать отдельную временную SQLite БД или
замоканный SQLAlchemy session; никогда не подключаться к `data/rapt.db` или БД из
`backend/.env`. Если выбран SQLite, создавать временный файл через stdlib
`tempfile` и удалять его автоматически.

Mock client должен хранить список всех `create()` requests, а не только последний:
после появления summarizer и tool rounds одного поля `request` недостаточно.

## 10. Ручные acceptance-сценарии

Проверить каждый из трёх subject types.

### Новый чат

1. Открыть ассистента.
2. Увидеть короткий default question и один ответ.
3. Закрыть и открыть окно: новый LLM-запрос не должен выполняться.
4. Обновить страницу: оба сообщения должны восстановиться из backend.

### Follow-up

1. Задать «А температуру поднять?».
2. Убедиться, что ответ понимает предыдущий контекст и не повторяет полное ревью.
3. Обновить страницу: follow-up остаётся в истории.

### Свежие данные

1. Открыть активное брожение и получить оценку.
2. После синхронизации новой телеметрии задать следующий вопрос.
3. Ответ должен использовать новые текущие значения; старые числа из истории не
   должны называться текущими.

### Ошибка LLM

1. Остановить/указать недоступный LLM endpoint.
2. Отправить вопрос.
3. Увидеть error, сохранённый текст в textarea и отсутствие полупары в БД.
4. Восстановить LLM и повторить вопрос один раз.

### Tools

1. В сессионном чате попросить сравнить с прошлой сессией по имени.
2. Проверить `search_sessions` → `get_session_context` → финальный ответ.
3. Убедиться, что recipe chat tools не получает.

### Длинная беседа

1. Создать больше 24 сообщений.
2. Убедиться, что UI показывает всю сохранённую историю.
3. Проверить лог/mock: модель получает summary и последние 12 сообщений, а не всю
   таблицу.

## 11. Обязательные проверки перед handoff

Backend:

```powershell
cd backend
uv run ruff format .
uv run ruff check . --fix
uv run ruff format --check .
uv run ruff check .
uv run python scripts/test_ai.py
uv run alembic upgrade head
```

`alembic upgrade head` запускать только против явно выбранной dev/test БД, не
против пользовательской production/runtime БД без подтверждения.

Frontend:

```powershell
cd frontend
npm run fmt
npm run fmt:check
npm run build
npm run lint
```

Дополнительно выполнить ручные сценарии из раздела 10 и проверить читаемость
кириллицы во всех затронутых `.py`, `.tsx`, `.ts` и `.md`.

## 12. Что сознательно не входит в эту реализацию

- SSE/WebSocket streaming. Сначала нужен правильный server-owned conversation
  flow. Streaming делать отдельным этапом после стабилизации tool loop; обычный
  JSON endpoint уже функционально корректен.
- несколько бесед на один объект, список/поиск/удаление бесед;
- user accounts и разграничение доступа, пока их нет в приложении;
- RAG, embeddings и vector DB;
- сохранение chain-of-thought, system/tool messages и сырых LLM requests;
- фоновые очереди, distributed locks и multi-worker orchestration;
- точный tokenizer и бюджетирование по токенам;
- tools для recipe review;
- автоматическая миграция в startup приложения.

Добавлять эти возможности следует только после появления конкретного
пользовательского сценария или измеренной проблемы. Они не нужны для исправления
текущего workflow.
