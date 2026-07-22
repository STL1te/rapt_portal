import { type Dispatch, type DragEvent, type SetStateAction, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createProfile, getProfile, getProfileTypes, updateProfile } from '@/api'
import { ALERT_TRIGGERS, CONTROL_TYPES, DURATION_TYPES, END_TYPES } from '@/types/profile'
import type { ProfileAlert, ProfileInput, ProfileStep, ProfileStepAlert } from '@/types'
import { useTitle } from '@/hooks/useTitle'

const numOr = (v: string): number | null => (v.trim() === '' ? null : Number(v))

// option labels mirroring RAPT's step editor (Russian to match the app)
const CONTROL_LABEL: Record<string, string> = {
  Target: 'Нагрев/охлаждение до целевой температуры',
  Ramp: 'Плавный разгон до температуры за время шага',
  FreeRise: 'Свободный подъём',
}
const END_LABEL: Record<string, string> = {
  Duration: 'по таймеру шага',
  Temperature: 'по достижению температуры',
  Gravity: 'по плотности',
  GravityVelocity: 'по скорости плотности',
  Manual: 'вручную кнопкой на устройстве',
}
const DURATION_LABEL: Record<string, string> = {
  Start: 'сразу с началом шага',
  Temperature: 'по достижению температуры',
  Gravity: 'по плотности',
  GravityVelocity: 'по скорости плотности',
  Manual: 'вручную кнопкой на устройстве',
}
// «Alert When …» option texts from RAPT's alert editor, translated
const TRIGGER_LABEL: Record<string, string> = {
  StepStart: 'шаг начинается',
  StepEnd: 'шаг завершается',
  Duration: 'прошло заданное время после старта таймера шага',
  Temperature: 'достигнута заданная температура',
  Gravity: 'достигнута заданная плотность',
  GravityVelocity: 'скорость изменения плотности выше/ниже заданной',
}
// step-header icons, mirroring RAPT's collapsed step title (see RecipeDetail)
const CONTROL_ICON: Record<string, string> = { Target: 'fa-bullseye', Ramp: 'fa-chart-line' }
const END_ICON: Record<string, string> = {
  Temperature: 'fa-thermometer-half',
  Duration: 'fa-clock',
  Manual: 'fa-hand-point-up',
  Gravity: 'fa-droplet',
  GravityVelocity: 'fa-droplet',
}
// RAPT's Heating % dropdown: Manual Control (→ null) or 100..5 step 5
const HEATING_OPTIONS = Array.from({ length: 20 }, (_, i) => 100 - i * 5)

// step-alert time (stored in seconds) is entered in a chosen unit
type TimeUnit = 'sec' | 'min' | 'hour'
const UNIT_SEC: Record<TimeUnit, number> = { sec: 1, min: 60, hour: 3600 }
const UNIT_LABEL: Record<TimeUnit, string> = { sec: 'сек', min: 'мин', hour: 'ч' }
function deriveUnit(seconds: number | null): TimeUnit {
  if (seconds == null || seconds === 0) return 'min'
  if (seconds % 3600 === 0) return 'hour'
  if (seconds % 60 === 0) return 'min'
  return 'sec'
}

// steps carry a stable local uid so collapse state and React keys survive reorder
type EditStep = ProfileStep & { _uid: string }
const uid = () => Math.random().toString(36).slice(2)

function blankStep(order: number): EditStep {
  return {
    _uid: uid(),
    id: null,
    name: '',
    order,
    controlType: 'Target',
    endType: 'Duration',
    durationType: 'Start', // required by RAPT
    operator: null,
    length: null,
    temperature: null,
    minTemperature: null,
    maxTemperature: null,
    gravity: null,
    pumpEnabled: null,
    pumpUtilisation: null,
    heatingUtilisation: null,
    pidEnabled: null,
    sensorDifferential: null,
    alerts: [],
  }
}

function blankAlert(): ProfileStepAlert {
  return {
    id: null,
    alertText: '',
    trigger: 'StepStart',
    operator: null,
    temperature: null,
    gravity: null,
    length: null,
  }
}

// Alert list editor shared by profile-level and step-level alerts.
function AlertsEditor({
  alerts,
  step,
  stepTemperature,
  onChange,
}: {
  alerts: ProfileAlert[]
  step: boolean
  stepTemperature?: number | null
  onChange: (next: ProfileAlert[]) => void
}) {
  const patch = (i: number, p: Partial<ProfileStepAlert>) =>
    onChange(alerts.map((a, idx) => (idx === i ? { ...a, ...p } : a)))
  // chosen display unit per alert index (falls back to a unit derived from the value)
  const [units, setUnits] = useState<Record<number, TimeUnit>>({})
  return (
    <div className="alerts-editor">
      {alerts.map((a, i) => (
        <div key={a.id ?? i} className="alert-row">
          <label className="field">
            <span>Оповестить, когда</span>
            <select
              value={a.trigger ?? ''}
              onChange={(e) => {
                const trigger = (e.target.value || null) as ProfileAlert['trigger']
                const p: Partial<ProfileStepAlert> = { trigger }
                // prefill from the step's target temperature when it's not set yet
                if (trigger === 'Temperature' && a.temperature == null && stepTemperature != null)
                  p.temperature = stepTemperature
                patch(i, p)
              }}
            >
              {ALERT_TRIGGERS.map((t) => (
                <option key={t} value={t}>
                  {TRIGGER_LABEL[t] ?? t}
                </option>
              ))}
            </select>
          </label>
          {a.trigger === 'Temperature' ? (
            <label className="field">
              <span>Температура, °C</span>
              <input
                type="number"
                value={a.temperature ?? ''}
                onChange={(e) => patch(i, { temperature: numOr(e.target.value) })}
              />
            </label>
          ) : null}
          {step && a.trigger === 'Duration'
            ? (() => {
                const len = (a as ProfileStepAlert).length
                const unit = units[i] ?? deriveUnit(len)
                return (
                  <label className="field">
                    <span>Время от старта таймера шага</span>
                    <div className="time-input">
                      <input
                        type="number"
                        min={0}
                        value={len == null ? '' : len / UNIT_SEC[unit]}
                        onChange={(e) =>
                          patch(i, {
                            length:
                              e.target.value.trim() === ''
                                ? null
                                : Math.round(Number(e.target.value) * UNIT_SEC[unit]),
                          })
                        }
                      />
                      <select
                        value={unit}
                        onChange={(e) => setUnits({ ...units, [i]: e.target.value as TimeUnit })}
                      >
                        {(['sec', 'min', 'hour'] as const).map((u) => (
                          <option key={u} value={u}>
                            {UNIT_LABEL[u]}
                          </option>
                        ))}
                      </select>
                    </div>
                  </label>
                )
              })()
            : null}
          <label className="field">
            <span>Сообщение</span>
            <input
              type="text"
              value={a.alertText ?? ''}
              onChange={(e) => patch(i, { alertText: e.target.value })}
            />
          </label>
          <button
            type="button"
            className="icon-btn alert-del"
            onClick={() => onChange(alerts.filter((_, idx) => idx !== i))}
          >
            <i className="fa-solid fa-trash" /> Удалить
          </button>
        </div>
      ))}
      <button type="button" className="link-btn" onClick={() => onChange([...alerts, blankAlert()])}>
        <i className="fa-solid fa-plus" /> алерт
      </button>
    </div>
  )
}

export default function RecipeEditor() {
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  useTitle(isEdit ? 'Редактирование рецепта' : 'Новый рецепт')

  const { data: existing } = useQuery({
    queryKey: ['profile', id],
    queryFn: () => getProfile(id as string),
    enabled: isEdit,
  })
  const { data: types } = useQuery({ queryKey: ['profile-types'], queryFn: getProfileTypes })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isPublic, setPublic] = useState(false)
  const [typeId, setTypeId] = useState('')
  const [steps, setSteps] = useState<EditStep[]>([])
  const [alerts, setAlerts] = useState<ProfileAlert[]>([])
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [advanced, setAdvanced] = useState<Set<string>>(new Set())
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [over, setOver] = useState<{ i: number; pos: 'before' | 'after' } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const markDirty = () => setDirty(true)

  // warn on browser close/reload while there are unsaved edits
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  // guarded in-page navigation (Назад / Отмена)
  const leave = () => {
    if (dirty && !window.confirm('Изменения не сохранены и будут потеряны. Покинуть страницу?')) {
      return
    }
    navigate(-1)
  }

  // seed the form once the profile loads (edit mode)
  useEffect(() => {
    if (!existing) return
    setName(existing.name ?? '')
    setDescription(existing.description ?? '')
    setPublic(existing.public)
    setTypeId(existing.profile_type_id ?? '')
    setSteps(
      existing.steps
        .slice()
        .sort((a, b) => a.order - b.order)
        .map((s) => ({ ...s, _uid: uid() })),
    )
    setAlerts(existing.alerts)
  }, [existing])

  // default the type picker to the first known type when creating
  useEffect(() => {
    if (!isEdit && !typeId && types?.length) setTypeId(types[0].id)
  }, [isEdit, typeId, types])

  const reindex = (s: EditStep[]) => s.map((st, idx) => ({ ...st, order: idx }))

  const patchStep = (i: number, p: Partial<ProfileStep>) =>
    setSteps((s) => s.map((st, idx) => (idx === i ? { ...st, ...p } : st)))

  const toggleIn =
    (setter: Dispatch<SetStateAction<Set<string>>>) => (key: string) =>
      setter((c) => {
        const next = new Set(c)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      })
  const toggleCollapsed = toggleIn(setCollapsed)
  const toggleAdvanced = toggleIn(setAdvanced)

  // drag-and-drop reorder (native HTML5; arrows below stay for touch/mobile)
  const onStepDragStart = (e: DragEvent, i: number) => {
    setDragIdx(i)
    e.dataTransfer.effectAllowed = 'move'
    // drag the whole step card, not just the tiny handle icon
    const card = (e.currentTarget as HTMLElement).closest('.step-editor')
    if (card) e.dataTransfer.setDragImage(card, 24, 24)
  }

  const onStepDragOver = (e: DragEvent, i: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const pos: 'before' | 'after' = e.clientY < r.top + r.height / 2 ? 'before' : 'after'
    if (!over || over.i !== i || over.pos !== pos) setOver({ i, pos })
  }

  const endDrag = () => {
    setDragIdx(null)
    setOver(null)
  }

  const onStepDrop = () => {
    if (dragIdx != null && over) {
      const from = dragIdx
      let to = over.pos === 'before' ? over.i : over.i + 1
      if (from < to) to-- // account for the gap left by removing the dragged item
      if (to !== from) {
        markDirty()
        setSteps((s) => {
          const next = s.slice()
          const [moved] = next.splice(from, 1)
          next.splice(to, 0, moved)
          return reindex(next)
        })
      }
    }
    endDrag()
  }

  const moveStep = (i: number, dir: -1 | 1) => {
    markDirty()
    setSteps((s) => {
      const j = i + dir
      if (j < 0 || j >= s.length) return s
      const next = s.slice()
      ;[next[i], next[j]] = [next[j], next[i]]
      return reindex(next)
    })
  }

  async function save() {
    setError(null)
    if (name.trim().length < 4) return setError('Название рецепта: от 4 до 50 символов')
    if (!typeId) return setError('Выберите тип профиля')
    const payload: ProfileInput = {
      name: name.trim(),
      description: description.trim() || null,
      public: isPublic,
      profile_type_id: typeId,
      profile_type_name: types?.find((t) => t.id === typeId)?.name ?? null,
      // _uid is a local-only key; backend StepIn ignores it and _pick drops it
      steps: steps.map((st, i) => ({ ...st, order: i })),
      alerts,
    }
    setSaving(true)
    try {
      const saved = isEdit ? await updateProfile(id as string, payload) : await createProfile(payload)
      setDirty(false) // saved — don't warn on the navigation below
      await queryClient.invalidateQueries({ queryKey: ['profiles'] })
      await queryClient.invalidateQueries({ queryKey: ['profile', saved.id] })
      navigate(`/recipes/${saved.id}`)
    } catch (e) {
      setError(String(e))
      setSaving(false)
    }
  }

  return (
    <div onChange={markDirty}>
      <a className="back" onClick={leave}>
        <i className="fa-solid fa-arrow-left" /> Назад
      </a>

      <div className="page-head">
        <h2>{isEdit ? 'Редактирование рецепта' : 'Новый рецепт'}</h2>
      </div>

      <section className="panel recipe-form">
        <label className="field">
          <span>Название</span>
          <input
            type="text"
            minLength={4}
            maxLength={50}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Описание</span>
          <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Тип профиля</span>
            <select value={typeId} onChange={(e) => setTypeId(e.target.value)}>
              {types?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name ?? t.id}
                </option>
              ))}
            </select>
          </label>
          <div className="field">
            <span>Доступ</span>
            <label className="sync-checkbox">
              <input
                type="checkbox"
                checked={isPublic}
                onChange={(e) => setPublic(e.target.checked)}
              />
              <span>Публичный</span>
            </label>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="steps-head">
          <h3 className="panel-title">Шаги</h3>
          <button
            type="button"
            onClick={() => {
              markDirty()
              setSteps((s) => [...s, blankStep(s.length)])
            }}
          >
            <i className="fa-solid fa-plus" /> Шаг
          </button>
        </div>

        {steps.map((st, i) => {
          const isCollapsed = collapsed.has(st._uid)
          const isAdvanced = advanced.has(st._uid)
          return (
          <div
            key={st._uid}
            className={`step-editor${dragIdx === i ? ' dragging' : ''}${
              over && over.i === i && dragIdx !== i ? ` drop-${over.pos}` : ''
            }`}
            onDragOver={(e) => onStepDragOver(e, i)}
            onDrop={onStepDrop}
          >
            <div className="step-editor-head">
              <i
                className="handle fa-solid fa-grip-vertical"
                title="Перетащить"
                draggable
                onDragStart={(e) => onStepDragStart(e, i)}
                onDragEnd={endDrag}
              />
              <button
                type="button"
                className="icon-btn"
                title={isCollapsed ? 'Развернуть' : 'Свернуть'}
                onClick={() => toggleCollapsed(st._uid)}
              >
                <i className={`fa-solid ${isCollapsed ? 'fa-chevron-right' : 'fa-chevron-down'}`} />
              </button>
              <span className="step-num">{i + 1}</span>
              <input
                type="text"
                className="step-name"
                placeholder="Название шага"
                minLength={4}
                maxLength={50}
                value={st.name ?? ''}
                onChange={(e) => patchStep(i, { name: e.target.value })}
              />
              {st.controlType && CONTROL_ICON[st.controlType] ? (
                <i className={`fa-solid ${CONTROL_ICON[st.controlType]} step-icon`} title={st.controlType} />
              ) : null}
              {st.endType && END_ICON[st.endType] ? (
                <i className={`fa-solid ${END_ICON[st.endType]} step-icon`} title={st.endType} />
              ) : null}
              <button type="button" className="icon-btn" disabled={i === 0} onClick={() => moveStep(i, -1)}>
                <i className="fa-solid fa-arrow-up" />
              </button>
              <button
                type="button"
                className="icon-btn"
                disabled={i === steps.length - 1}
                onClick={() => moveStep(i, 1)}
              >
                <i className="fa-solid fa-arrow-down" />
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() => {
                  markDirty()
                  setSteps((s) => reindex(s.filter((_, idx) => idx !== i)))
                }}
              >
                <i className="fa-solid fa-trash" />
              </button>
            </div>

            {isCollapsed ? null : (
            <>
            <div className="step-editor-fields">
              <label className="field field-wide">
                <span>Тип шага</span>
                <select
                  value={st.controlType ?? ''}
                  onChange={(e) => patchStep(i, { controlType: (e.target.value || null) as ProfileStep['controlType'] })}
                >
                  {CONTROL_TYPES.map((c) => (
                    <option key={c} value={c}>
                      {CONTROL_LABEL[c] ?? c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field-narrow">
                <span>Целевая температура, °C</span>
                <input
                  type="number"
                  value={st.temperature ?? ''}
                  onChange={(e) => patchStep(i, { temperature: numOr(e.target.value) })}
                />
              </label>
              <label className="field field-256">
                <span>Переход к следующему шагу</span>
                <select
                  value={st.endType ?? ''}
                  onChange={(e) => patchStep(i, { endType: (e.target.value || null) as ProfileStep['endType'] })}
                >
                  {END_TYPES.map((c) => (
                    <option key={c} value={c}>
                      {END_LABEL[c] ?? c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field-256">
                <span>Запуск таймера шага</span>
                <select
                  value={st.durationType ?? ''}
                  onChange={(e) => patchStep(i, { durationType: (e.target.value || null) as ProfileStep['durationType'] })}
                >
                  {DURATION_TYPES.map((c) => (
                    <option key={c} value={c}>
                      {DURATION_LABEL[c] ?? c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field-narrow">
                <span>Длительность, мин</span>
                <input
                  type="number"
                  min={1}
                  value={st.length == null ? '' : st.length / 60}
                  onChange={(e) =>
                    patchStep(i, {
                      length: e.target.value.trim() === '' ? null : Math.round(Number(e.target.value) * 60),
                    })
                  }
                />
              </label>
            </div>

            <label className="sync-checkbox adv-toggle">
              <input type="checkbox" checked={isAdvanced} onChange={() => toggleAdvanced(st._uid)} />
              <span>Показать доп. параметры</span>
            </label>

            {isAdvanced ? (
              <div className="step-editor-fields">
                <label className="field field-256">
                  <span>Нагрев, %</span>
                  <select
                    value={st.heatingUtilisation == null ? 'manual' : String(st.heatingUtilisation)}
                    onChange={(e) =>
                      patchStep(i, {
                        heatingUtilisation: e.target.value === 'manual' ? null : Number(e.target.value),
                      })
                    }
                  >
                    <option value="manual">Ручное управление</option>
                    {HEATING_OPTIONS.map((n) => (
                      <option key={n} value={n}>
                        {n}%
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field field-256">
                  <span>PID</span>
                  <select
                    value={st.pidEnabled == null ? 'manual' : st.pidEnabled ? 'on' : 'off'}
                    onChange={(e) =>
                      patchStep(i, {
                        pidEnabled: e.target.value === 'manual' ? null : e.target.value === 'on',
                      })
                    }
                  >
                    <option value="manual">Ручное управление</option>
                    <option value="on">Вкл</option>
                    <option value="off">Выкл</option>
                  </select>
                </label>
                <label className="field field-narrow">
                  <span>Допустимый разброс температуры, °C</span>
                  <input
                    type="number"
                    value={st.sensorDifferential ?? ''}
                    onChange={(e) => patchStep(i, { sensorDifferential: numOr(e.target.value) })}
                  />
                </label>
              </div>
            ) : null}

            <div className="step-alerts-editor">
              <span className="muted">Алерты шага</span>
              <AlertsEditor
                alerts={st.alerts}
                step
                stepTemperature={st.temperature}
                onChange={(next) => {
                  markDirty()
                  patchStep(i, { alerts: next as ProfileStepAlert[] })
                }}
              />
            </div>
            </>
            )}
          </div>
          )
        })}
        {steps.length === 0 ? <p className="muted">Шагов пока нет.</p> : null}
      </section>

      {error ? <p className="error">{error}</p> : null}

      <div className="pagination-actions">
        <button type="button" disabled={saving} onClick={() => void save()}>
          {saving ? 'Сохранение…' : 'Сохранить черновик'}
        </button>
        <button type="button" onClick={leave}>
          Отмена
        </button>
      </div>
    </div>
  )
}
