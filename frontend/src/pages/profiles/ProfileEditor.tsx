import { type DragEvent, useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createProfile, getProfile, getProfileTypes, updateProfile } from '@/api'
import { byTriggerTime, CONTROL_TYPES, DURATION_TYPES, END_TYPES } from '@/types/profile'
import type {
  AlertTrigger,
  ControlType,
  DurationType,
  EndType,
  ProfileAlert,
  ProfileInput,
  ProfileStep,
  ProfileStepAlert,
} from '@/types'
import { useTitle } from '@/hooks/useTitle'

const numOr = (v: string): number | null => (v.trim() === '' ? null : Number(v))

// RAPT gates the form per profile type (rules live client-side only). We key off
// the type name from /api/profile-types. Fermentation & General Temp Control behave
// the same ('temp'); Pill has no steps, only profile alerts.
type ProfileKind = 'brewzilla' | 'temp' | 'pill'
const kindOf = (name?: string | null): ProfileKind =>
  name === 'Pill Hydrometer' ? 'pill' : name === 'BrewZilla' ? 'brewzilla' : 'temp'
// BrewZilla drops FreeRise; other step-based types keep all three
const controlOptionsFor = (kind: ProfileKind): readonly ControlType[] =>
  kind === 'brewzilla' ? (['Target', 'Ramp'] as const) : CONTROL_TYPES
// RAPT's per-type default sensor differential (°C)
const sensorDefaultFor = (kind: ProfileKind): number => (kind === 'brewzilla' ? 2 : 5)

// BrewZilla has no gravity sensor — drop gravity-based options everywhere it appears
const dropGravity = <T extends string>(xs: readonly T[]): readonly T[] =>
  xs.filter((x) => x !== 'Gravity' && x !== 'GravityVelocity')
const endTypesFor = (kind: ProfileKind): readonly EndType[] =>
  kind === 'brewzilla' ? (dropGravity(END_TYPES) as EndType[]) : END_TYPES
const durationTypesFor = (kind: ProfileKind): readonly DurationType[] =>
  kind === 'brewzilla' ? (dropGravity(DURATION_TYPES) as DurationType[]) : DURATION_TYPES
// Alert triggers per type: BrewZilla step alerts can't use gravity; Pill / profile-level
// alerts drop the step-boundary triggers (mirrors RAPT's T(profileType, isStepAlert)).
// Note: RAPT's profile-level list also has 'Duration', but our ProfileAlert has no
// length field to store it, so we omit it to avoid an unsavable alert.
const alertTriggersFor = (kind: ProfileKind, isStep: boolean): readonly AlertTrigger[] =>
  kind !== 'pill' && isStep
    ? kind === 'brewzilla'
      ? (['StepStart', 'StepEnd', 'Duration', 'Temperature'] as const)
      : (['StepStart', 'StepEnd', 'Duration', 'Temperature', 'Gravity', 'GravityVelocity'] as const)
    : (['Temperature', 'Gravity', 'GravityVelocity'] as const)

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
// short labels for the collapsed step summary (RAPT shows "Target · 18°C · Manual")
const CONTROL_SHORT: Record<string, string> = {
  Target: 'Целевая температура',
  Ramp: 'Разгон',
  FreeRise: 'Свободный подъём',
}
const END_SHORT: Record<string, string> = {
  Duration: 'по таймеру',
  Temperature: 'по температуре',
  Gravity: 'по плотности',
  GravityVelocity: 'по скорости плотности',
  Manual: 'вручную',
}
// RAPT's Heating % dropdown: Manual Control (→ null) or 100..0 step 5
const HEATING_OPTIONS = Array.from({ length: 21 }, (_, i) => 100 - i * 5)

// step duration (stored in seconds) is entered in a chosen unit (RAPT: min/hr/day)
const DUR_UNIT_SEC = { minutes: 60, hours: 3600, days: 86400 } as const
type DurUnit = keyof typeof DUR_UNIT_SEC
const DUR_UNIT_LABEL: Record<DurUnit, string> = { minutes: 'мин', hours: 'ч', days: 'дн' }
const deriveDurUnit = (sec: number | null): DurUnit =>
  sec == null || sec === 0
    ? 'hours'
    : sec % 86400 === 0
      ? 'days'
      : sec % 3600 === 0
        ? 'hours'
        : 'minutes'
// RAPT shows the step timer / duration fields only for these shapes
const showsDuration = (s: Pick<ProfileStep, 'controlType' | 'endType'>): boolean =>
  s.controlType === 'Ramp' || s.endType === 'Duration'

// step field validation mirroring RAPT's M(e) — returns the first problem or null
const stepProblem = (s: ProfileStep): string | null => {
  if ((s.name ?? '').trim() === '') return 'нет названия'
  if (s.controlType === 'FreeRise') {
    if (s.minTemperature == null) return 'нет мин. температуры'
    if (s.maxTemperature == null) return 'нет макс. температуры'
    if (s.minTemperature > s.maxTemperature) return 'макс. < мин.'
  } else if (s.temperature == null) {
    return 'нет целевой температуры'
  }
  if (showsDuration(s) && s.length == null) return 'нет длительности'
  if (s.endType === 'Gravity' && s.gravity == null) return 'нет плотности'
  if (s.endType === 'GravityVelocity' && s.gravity == null) return 'нет скорости плотности'
  return null
}

// alert field validation mirroring RAPT's w(e) — used for Pill profile alerts
const alertProblem = (a: ProfileAlert): string | null => {
  if ((a.alertText ?? '').trim() === '') return 'нет текста'
  if (a.trigger === 'Temperature' && a.temperature == null) return 'нет температуры'
  if (a.trigger === 'Gravity' && a.gravity == null) return 'нет плотности'
  if (a.trigger === 'GravityVelocity' && a.gravity == null) return 'нет скорости'
  if (a.trigger === 'Duration' && (a as ProfileStepAlert).length == null) return 'нет времени'
  return null
}

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
    durationType: 'Temperature',
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

function blankAlert(trigger: AlertTrigger = 'StepStart'): ProfileStepAlert {
  return {
    id: null,
    alertText: '',
    trigger,
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
  kind,
  stepTemperature,
  onChange,
}: {
  alerts: ProfileAlert[]
  step: boolean
  kind: ProfileKind
  stepTemperature?: number | null
  onChange: (next: ProfileAlert[]) => void
}) {
  const patch = (i: number, p: Partial<ProfileStepAlert>) =>
    onChange(alerts.map((a, idx) => (idx === i ? { ...a, ...p } : a)))
  // triggers available for this profile type / alert scope (BrewZilla has no gravity)
  const triggers = alertTriggersFor(kind, step)
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
              {triggers.map((t) => (
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
          {a.trigger === 'GravityVelocity' ? (
            <label className="field">
              <span>Условие</span>
              <select
                value={a.operator ?? 'LessThan'}
                onChange={(e) => patch(i, { operator: e.target.value as ProfileAlert['operator'] })}
              >
                <option value="LessThan">меньше</option>
                <option value="GreaterThan">больше</option>
              </select>
            </label>
          ) : null}
          {a.trigger === 'Gravity' || a.trigger === 'GravityVelocity' ? (
            <label className="field">
              <span>{a.trigger === 'Gravity' ? 'Плотность (SG)' : 'Скорость (пункты/день)'}</span>
              <input
                type="number"
                step={a.trigger === 'Gravity' ? '0.001' : undefined}
                value={a.gravity ?? ''}
                onChange={(e) => patch(i, { gravity: numOr(e.target.value) })}
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
      <button
        type="button"
        className="link-btn"
        onClick={() => onChange([...alerts, blankAlert(triggers[0])])}
      >
        <i className="fa-solid fa-plus" /> алерт
      </button>
      {/* profile-level alerts are all condition-based — nothing to order there */}
      {step && alerts.length > 1 ? (
        <button
          type="button"
          className="link-btn"
          title="Старт шага → по таймеру → по условию → конец шага"
          // rows are keyed by index for unsaved alerts, so drop the per-row unit
          // overrides — they'd stay pinned to the old positions after the reorder
          onClick={() => {
            setUnits({})
            onChange(alerts.slice().sort(byTriggerTime))
          }}
        >
          <i className="fa-solid fa-arrow-down-1-9" /> по времени
        </button>
      ) : null}
    </div>
  )
}

// Step edit dialog — RAPT opens the step form in a modal instead of expanding inline.
function StepModal({
  draft,
  index,
  kind,
  onChange,
  onSave,
  onClose,
}: {
  draft: EditStep
  index: number
  kind: ProfileKind
  onChange: (p: Partial<ProfileStep>) => void
  onSave: () => void
  onClose: () => void
}) {
  const controlOptions = controlOptionsFor(kind)
  const isFreeRise = draft.controlType === 'FreeRise'
  // RAPT flags boil risk on BrewZilla when target ≥ 110 °C (not for FreeRise)
  const boilWarn =
    kind === 'brewzilla' && !isFreeRise && draft.temperature != null && draft.temperature >= 110
  const [durUnit, setDurUnit] = useState<DurUnit>(deriveDurUnit(draft.length))
  // Esc closes the dialog (ponytail: no full focus-trap; add if a11y audit needs it)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-layer">
      <button type="button" className="modal-backdrop" aria-label="Закрыть" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label="Редактирование шага">
        <div className="modal-head">
          <h3>Шаг {index + 1}</h3>
          <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onClose}>
            <i className="fa-solid fa-xmark" />
          </button>
        </div>

        <div className="modal-body">
          <label className="field">
            <span>Название шага</span>
            <input
              type="text"
              minLength={4}
              maxLength={50}
              placeholder="Название шага"
              value={draft.name ?? ''}
              onChange={(e) => onChange({ name: e.target.value })}
            />
          </label>
          <label className="field">
            <span>Тип шага</span>
            <select
              value={draft.controlType ?? ''}
              onChange={(e) => {
                const controlType = (e.target.value || null) as ProfileStep['controlType']
                onChange({
                  controlType,
                  ...(draft.endType === 'Duration'
                    ? { durationType: controlType === 'Ramp' ? 'Start' : 'Temperature' }
                    : {}),
                })
              }}
            >
              {controlOptions.map((c) => (
                <option key={c} value={c}>
                  {CONTROL_LABEL[c] ?? c}
                </option>
              ))}
            </select>
          </label>
          {isFreeRise ? (
            <div className="field-row">
              <label className="field">
                <span>Мин. температура, °C</span>
                <input
                  type="number"
                  value={draft.minTemperature ?? ''}
                  onChange={(e) => onChange({ minTemperature: numOr(e.target.value) })}
                />
              </label>
              <label className="field">
                <span>Макс. температура, °C</span>
                <input
                  type="number"
                  value={draft.maxTemperature ?? ''}
                  onChange={(e) => onChange({ maxTemperature: numOr(e.target.value) })}
                />
              </label>
            </div>
          ) : (
            <label className="field">
              <span>Целевая температура, °C</span>
              <input
                type="number"
                value={draft.temperature ?? ''}
                onChange={(e) => onChange({ temperature: numOr(e.target.value) })}
              />
              {boilWarn ? (
                <span className="warn-note">
                  <i className="fa-solid fa-triangle-exclamation" /> ≥ 110 °C — кипение
                </span>
              ) : null}
            </label>
          )}
          <label className="field">
            <span>Переход к следующему шагу</span>
            <select
              value={draft.endType ?? ''}
              onChange={(e) => {
                const endType = (e.target.value || null) as ProfileStep['endType']
                onChange({
                  endType,
                  ...(endType === 'Duration'
                    ? { durationType: draft.controlType === 'Ramp' ? 'Start' : 'Temperature' }
                    : {}),
                })
              }}
            >
              {endTypesFor(kind).map((c) => (
                <option key={c} value={c}>
                  {END_LABEL[c] ?? c}
                </option>
              ))}
            </select>
          </label>
          {draft.endType === 'Gravity' ? (
            <label className="field">
              <span>Целевая плотность (SG)</span>
              <input
                type="number"
                step="0.001"
                value={draft.gravity ?? ''}
                onChange={(e) => onChange({ gravity: numOr(e.target.value) })}
              />
            </label>
          ) : null}
          {draft.endType === 'GravityVelocity' ? (
            <div className="field-row">
              <label className="field">
                <span>Условие</span>
                <select
                  value={draft.operator ?? 'LessThan'}
                  onChange={(e) =>
                    onChange({ operator: e.target.value as ProfileStep['operator'] })
                  }
                >
                  <option value="LessThan">меньше</option>
                  <option value="GreaterThan">больше</option>
                </select>
              </label>
              <label className="field">
                <span>Скорость (пункты/день)</span>
                <input
                  type="number"
                  value={draft.gravity ?? ''}
                  onChange={(e) => onChange({ gravity: numOr(e.target.value) })}
                />
              </label>
            </div>
          ) : null}
          {draft.endType === 'Duration' ? (
            <label className="field">
              <span>Запуск таймера шага</span>
              <select
                value={draft.durationType ?? ''}
                onChange={(e) =>
                  onChange({
                    durationType: (e.target.value || null) as ProfileStep['durationType'],
                  })
                }
              >
                {durationTypesFor(kind).map((c) => (
                  <option key={c} value={c}>
                    {DURATION_LABEL[c] ?? c}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {showsDuration(draft) ? (
            <label className="field">
              <span>
                {draft.controlType === 'Ramp' ? 'Длительность разгона' : 'Длительность шага'}
              </span>
              <div className="time-input">
                <input
                  type="number"
                  min={1}
                  value={draft.length == null ? '' : draft.length / DUR_UNIT_SEC[durUnit]}
                  onChange={(e) =>
                    onChange({
                      length:
                        e.target.value.trim() === ''
                          ? null
                          : Math.round(Number(e.target.value) * DUR_UNIT_SEC[durUnit]),
                    })
                  }
                />
                <select value={durUnit} onChange={(e) => setDurUnit(e.target.value as DurUnit)}>
                  {(['minutes', 'hours', 'days'] as const).map((u) => (
                    <option key={u} value={u}>
                      {DUR_UNIT_LABEL[u]}
                    </option>
                  ))}
                </select>
              </div>
            </label>
          ) : null}

          <details className="fine-tuning">
            <summary>Тонкая настройка</summary>
            <div>
              <label className="field">
                <span>Нагрев, %</span>
                <select
                  value={
                    draft.heatingUtilisation == null ? 'manual' : String(draft.heatingUtilisation)
                  }
                  onChange={(e) =>
                    onChange({
                      heatingUtilisation:
                        e.target.value === 'manual' ? null : Number(e.target.value),
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
              <label className="field">
                <span>PID</span>
                <select
                  value={draft.pidEnabled == null ? 'manual' : draft.pidEnabled ? 'on' : 'off'}
                  onChange={(e) =>
                    onChange({
                      pidEnabled: e.target.value === 'manual' ? null : e.target.value === 'on',
                    })
                  }
                >
                  <option value="manual">Ручное управление</option>
                  <option value="on">Вкл</option>
                  <option value="off">Выкл</option>
                </select>
              </label>
              <label className="field">
                <span>Допустимый разброс температуры, °C</span>
                <input
                  type="number"
                  value={draft.sensorDifferential ?? ''}
                  onChange={(e) => onChange({ sensorDifferential: numOr(e.target.value) })}
                />
              </label>
            </div>
          </details>

          <div className="step-alerts-editor">
            <span className="muted">Алерты шага</span>
            <AlertsEditor
              alerts={draft.alerts}
              step
              kind={kind}
              stepTemperature={draft.temperature}
              onChange={(next) => onChange({ alerts: next as ProfileStepAlert[] })}
            />
          </div>
        </div>

        <div className="modal-foot">
          <button type="button" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="btn-solid" onClick={onSave}>
            Сохранить шаг
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ProfileEditor() {
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  useTitle(isEdit ? 'Редактирование профиля' : 'Новый профиль')

  // profile handed over by the AI wizard (never persisted — save() does that)
  const generated = (useLocation().state as { generated?: ProfileInput } | null)?.generated ?? null

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
  const [editing, setEditing] = useState<{ uid: string; draft: EditStep } | null>(null)
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [over, setOver] = useState<{ i: number; pos: 'before' | 'after' } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const markDirty = () => setDirty(true)

  // selected profile type drives the whole form shape (steps vs Pill alerts, etc.)
  const kind = kindOf(types?.find((t) => t.id === typeId)?.name)

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

  // default the type picker when creating; the wizard only ever emits BrewZilla profiles
  useEffect(() => {
    if (isEdit || typeId || !types?.length) return
    const brewzilla = types.find((t) => t.name === 'BrewZilla')
    setTypeId((generated && brewzilla?.id) || types[0].id)
  }, [isEdit, typeId, types, generated])

  // seed the form from the AI wizard's result, handed over via navigation state
  useEffect(() => {
    if (!generated) return
    setName(generated.name ?? '')
    setDescription(generated.description ?? '')
    setSteps(
      generated.steps
        .slice()
        .sort((a, b) => a.order - b.order)
        .map((step, order) => ({ ...step, order, _uid: uid() })),
    )
    setAlerts(generated.alerts)
    setDirty(true)
  }, [generated])

  const reindex = (s: EditStep[]) => s.map((st, idx) => ({ ...st, order: idx }))

  // open a step in the modal, editing a draft copy so Отмена discards changes
  const openStep = (st: EditStep) =>
    setEditing({ uid: st._uid, draft: { ...st, alerts: st.alerts.map((a) => ({ ...a })) } })
  const patchDraft = (p: Partial<ProfileStep>) =>
    setEditing((e) => (e ? { ...e, draft: { ...e.draft, ...p } } : e))
  const saveStep = () => {
    if (!editing) return
    markDirty()
    setSteps((s) => s.map((st) => (st._uid === editing.uid ? { ...editing.draft } : st)))
    setEditing(null)
  }

  const addStep = () => {
    markDirty()
    const st = { ...blankStep(steps.length), sensorDifferential: sensorDefaultFor(kind) }
    setSteps((s) => [...s, st])
    openStep(st) // RAPT opens the editor immediately for a fresh step
  }

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
    if (name.trim().length < 4) return setError('Название профиля: от 4 до 50 символов')
    if (!typeId) return setError('Выберите тип профиля')
    const payload: ProfileInput = {
      name: name.trim(),
      description: description.trim() || null,
      public: isPublic,
      profile_type_id: typeId,
      profile_type_name: types?.find((t) => t.id === typeId)?.name ?? null,
      // Pill profiles have no steps — only profile-level alerts
      // _uid is a local-only key; backend StepIn ignores it and _pick drops it
      steps:
        kind === 'pill'
          ? []
          : steps.map((st, i) => ({
              ...st,
              order: i,
              alerts: st.alerts.slice().sort(byTriggerTime),
            })),
      alerts,
    }
    setSaving(true)
    try {
      const saved = isEdit
        ? await updateProfile(id as string, payload)
        : await createProfile(payload)
      setDirty(false) // saved — don't warn on the navigation below
      await queryClient.invalidateQueries({ queryKey: ['profiles'] })
      await queryClient.invalidateQueries({ queryKey: ['profile', saved.id] })
      navigate(`/profiles/${saved.id}`)
    } catch (e) {
      setError(String(e))
      setSaving(false)
    }
  }

  // reasons saving is blocked — shown proactively next to the button (RAPT-style)
  const issues: string[] = []
  if (name.trim().length < 4) issues.push('название профиля — минимум 4 символа')
  if (!typeId) issues.push('не выбран тип профиля')
  if (kind === 'pill') {
    if (alerts.length === 0) issues.push('добавьте хотя бы один алерт')
    else if (alerts.some(alertProblem)) issues.push('заполните поля алертов')
  } else if (steps.length === 0) {
    issues.push('добавьте хотя бы один шаг')
  } else if (steps.some(stepProblem)) {
    issues.push('заполните поля шагов')
  }

  return (
    <div onChange={markDirty}>
      <a className="back" onClick={leave}>
        <i className="fa-solid fa-arrow-left" /> Назад
      </a>

      <div className="page-head">
        <div>
          <h2>{isEdit ? 'Редактирование профиля' : 'Новый профиль'}</h2>
          <p className="editor-subtitle">Пошаговый профиль управления температурой для брожения.</p>
        </div>
      </div>

      <section className="panel">
        <h3 className="panel-title">Тип профиля</h3>
        <div className="pill-group">
          {types?.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-pressed={typeId === t.id}
              className={`pill${typeId === t.id ? ' active' : ''}`}
              onClick={() => {
                markDirty()
                setTypeId(t.id)
              }}
            >
              {t.name ?? t.id}
            </button>
          ))}
        </div>
      </section>

      <section className="panel profile-form">
        <h3 className="panel-title">Основные данные</h3>
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
        <div className="switch-row">
          <div>
            <div className="switch-label">Публичный профиль</div>
            <div className="switch-desc">
              Другие пользователи смогут просматривать и копировать профиль.
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={isPublic}
            aria-label="Публичный профиль"
            className={`switch${isPublic ? ' on' : ''}`}
            onClick={() => {
              markDirty()
              setPublic((v) => !v)
            }}
          />
        </div>
      </section>

      {kind === 'pill' ? (
        <section className="panel">
          <h3 className="panel-title">Алерты Pill</h3>
          <p className="pill-note">
            Профиль Pill отслеживает показания и шлёт оповещения — шагов у него нет.
          </p>
          <AlertsEditor
            alerts={alerts}
            step={false}
            kind={kind}
            onChange={(next) => {
              markDirty()
              setAlerts(next)
            }}
          />
        </section>
      ) : (
        <section className="panel">
          <div className="steps-head">
            <h3 className="panel-title">Шаги</h3>
            <button type="button" onClick={addStep}>
              <i className="fa-solid fa-plus" /> Шаг
            </button>
          </div>

          {steps.map((st, i) => (
            <div
              key={st._uid}
              className={`step-editor step-row${dragIdx === i ? ' dragging' : ''}${
                over && over.i === i && dragIdx !== i ? ` drop-${over.pos}` : ''
              }`}
              onDragOver={(e) => onStepDragOver(e, i)}
              onDrop={onStepDrop}
            >
              <i
                className="handle fa-solid fa-grip-vertical"
                title="Перетащить"
                draggable
                onDragStart={(e) => onStepDragStart(e, i)}
                onDragEnd={endDrag}
              />
              <span className="step-num">{i + 1}</span>
              <button type="button" className="step-row-main" onClick={() => openStep(st)}>
                <span className="name">{st.name?.trim() || `Шаг ${i + 1}`}</span>
                <span className="step-summary-meta">
                  {st.controlType ? (
                    <span className="badge active">
                      {CONTROL_SHORT[st.controlType] ?? st.controlType}
                    </span>
                  ) : null}
                  {st.temperature != null ? <span>{st.temperature}°C</span> : null}
                  {st.endType ? <span>· {END_SHORT[st.endType] ?? st.endType}</span> : null}
                </span>
              </button>
              {stepProblem(st) ? (
                <i
                  className="fa-solid fa-triangle-exclamation step-warn"
                  title={stepProblem(st) ?? undefined}
                />
              ) : null}
              <div className="step-row-actions">
                <button
                  type="button"
                  className="icon-btn"
                  title="Вверх"
                  disabled={i === 0}
                  onClick={() => moveStep(i, -1)}
                >
                  <i className="fa-solid fa-arrow-up" />
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Вниз"
                  disabled={i === steps.length - 1}
                  onClick={() => moveStep(i, 1)}
                >
                  <i className="fa-solid fa-arrow-down" />
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Редактировать"
                  onClick={() => openStep(st)}
                >
                  <i className="fa-solid fa-pen" />
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Удалить"
                  onClick={() => {
                    markDirty()
                    setSteps((s) => reindex(s.filter((_, idx) => idx !== i)))
                  }}
                >
                  <i className="fa-solid fa-trash" />
                </button>
              </div>
            </div>
          ))}
          {steps.length === 0 ? (
            <button type="button" className="empty-steps" onClick={addStep}>
              <i className="fa-solid fa-plus" />
              <span className="empty-steps-title">Добавьте первый шаг</span>
              <span className="empty-steps-desc">
                Шаги задают температуру и условие перехода по ходу брожения.
              </span>
            </button>
          ) : null}
        </section>
      )}

      {editing ? (
        <StepModal
          draft={editing.draft}
          index={steps.findIndex((s) => s._uid === editing.uid)}
          kind={kind}
          onChange={patchDraft}
          onSave={saveStep}
          onClose={() => setEditing(null)}
        />
      ) : null}

      <div className="editor-actions">
        {error ? <p className="error">{error}</p> : null}
        {issues.length > 0 ? (
          <div className="info-banner">
            <i className="fa-solid fa-circle-info" />
            Сохранение недоступно: {issues.join('; ')}.
          </div>
        ) : null}
        <div className="editor-actions-row">
          <button
            type="button"
            className="btn-solid"
            disabled={saving || issues.length > 0}
            onClick={() => void save()}
          >
            {saving ? 'Сохранение…' : 'Сохранить черновик'}
          </button>
          <button type="button" onClick={leave}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}
