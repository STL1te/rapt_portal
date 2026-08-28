import { type ChangeEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { importProfile } from '@/api'
import type { BrewZillaOverrides, RecipeSourceFormat } from '@/types'
import { useTitle } from '@/hooks/useTitle'

const numOr = (v: string): number | undefined => (v.trim() === '' ? undefined : Number(v))

const FORMATS: {
  id: RecipeSourceFormat
  title: string
  icon: string
  accept: string
  desc: string
}[] = [
  {
    id: 'brewfather_json',
    title: 'BrewFather JSON',
    icon: 'fa-solid fa-flask',
    accept: '.json',
    desc: 'Родной экспорт BrewFather: в рецепте «Share → Export → Recipe (JSON)».',
  },
  {
    id: 'beerxml',
    title: 'BeerXML',
    icon: 'fa-solid fa-file-code',
    accept: '.xml',
    desc: 'Обменный формат, который понимают BrewFather, BeerSmith, Brewer’s Friend.',
  },
  {
    id: 'beerjson',
    title: 'BeerJSON',
    icon: 'fa-solid fa-file-lines',
    accept: '.json',
    desc: 'Современная замена BeerXML. Такой же документ отдаёт наш AI-мастер.',
  },
]

function Toggle({
  icon,
  label,
  desc,
  checked,
  disabled,
  onChange,
}: {
  icon: string
  label: string
  desc: string
  checked: boolean
  disabled?: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <div className="switch-card">
      <i className={icon} aria-hidden="true" />
      <div>
        <div className="switch-label">{label}</div>
        <div className="switch-desc">{desc}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        className={`switch${checked ? ' on' : ''}`}
        onClick={() => onChange(!checked)}
      />
    </div>
  )
}

export default function ProfileImport() {
  useTitle('Импорт рецепта')
  const navigate = useNavigate()
  const [format, setFormat] = useState<RecipeSourceFormat>('brewfather_json')
  const [fileName, setFileName] = useState('')
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [includeSparge, setIncludeSparge] = useState(true)
  const [includeMashOut, setIncludeMashOut] = useState(true)
  const [includeTemperatureAlerts, setIncludeTemperatureAlerts] = useState(true)
  const [restEndAlerts, setRestEndAlerts] = useState(true)
  const [pidEnabled, setPidEnabled] = useState(true)
  // 90/50: разгон между паузами на 90 %, удержание паузы на 50 % — разные мощности
  // это и то, что заставляет компилятор выделить переход в отдельный шаг
  const [heatPowerPct, setHeatPowerPct] = useState('90')
  const [restPowerPct, setRestPowerPct] = useState('50')
  const [mashInOverride, setMashInOverride] = useState(false)
  const [mashInTemperature, setMashInTemperature] = useState('')

  const selected = FORMATS.find((f) => f.id === format)!

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setFileName(file.name)
    setContent(await file.text())
  }

  async function submit() {
    setError(null)
    if (!content) {
      setError('Выберите файл рецепта')
      return
    }
    const overrides: BrewZillaOverrides = {
      include_sparge: includeSparge,
      include_mash_out: includeMashOut,
      include_temperature_alerts: includeTemperatureAlerts,
      mash_pid_enabled: pidEnabled,
      heat_power_pct: numOr(heatPowerPct),
      rest_power_pct: numOr(restPowerPct),
      ...(mashInOverride ? { mash_in_temperature_c: numOr(mashInTemperature) } : {}),
    }
    setLoading(true)
    try {
      const profile = await importProfile(format, content, overrides, {
        restEndAlerts,
      })
      // hand the unsaved profile to the editor, same as the AI wizard: nothing is
      // persisted until the user saves it there
      navigate('/profiles/new', { state: { generated: profile } })
    } catch (e) {
      // keep the server's reason — it names the actual problem (bad JSON, an addition
      // outside the boil, a field the recipe is missing), which the generic hint can't
      const reason = e instanceof Error ? e.message : ''
      setError(
        `Не удалось разобрать файл как ${selected.title}. Проверьте выбранный формат.` +
          (reason ? ` Ответ сервера: ${reason}` : ''),
      )
      setLoading(false)
    }
  }

  return (
    <div>
      <a className="back" onClick={() => navigate('/profiles')}>
        <i className="fa-solid fa-arrow-left" /> Профили
      </a>

      <div className="page-head">
        <div>
          <h2>Импорт рецепта</h2>
          <p className="editor-subtitle">
            Загрузите рецепт — он соберётся в профиль BrewZilla и откроется в редакторе. Ничего не
            сохранится, пока вы не нажмёте «Сохранить черновик».
          </p>
        </div>
      </div>

      <section className="panel profile-wizard-panel">
        <h3 className="profile-wizard-title">
          <i className="fa-solid fa-file-import" /> Формат файла
        </h3>
        <div className="format-cards">
          {FORMATS.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={format === f.id}
              disabled={loading}
              className={`format-card${format === f.id ? ' active' : ''}`}
              onClick={() => setFormat(f.id)}
            >
              <span className="format-card-title">
                <i className={f.icon} aria-hidden="true" /> {f.title}
              </span>
              <span className="format-card-desc">{f.desc}</span>
            </button>
          ))}
        </div>

        {error ? <p className="error">{error}</p> : null}

        <label className="field">
          <span>Файл рецепта ({selected.accept})</span>
          <input
            type="file"
            accept={selected.accept}
            disabled={loading}
            onChange={(e) => void onFile(e)}
          />
        </label>
        {fileName ? <p className="muted">{fileName}</p> : null}

        <h3 className="profile-wizard-title">Настройки BrewZilla</h3>
        <div className="switch-list">
          <Toggle
            icon="fa-solid fa-droplet"
            label="Шаг промывки (Sparge)"
            desc="Ручной шаг после затирания на температуре промывки."
            checked={includeSparge}
            disabled={loading}
            onChange={setIncludeSparge}
          />
          <Toggle
            icon="fa-solid fa-fire"
            label="Mash Out"
            desc="Финальная пауза 78 °C. Если она есть в рецепте, берётся оттуда."
            checked={includeMashOut}
            disabled={loading}
            onChange={setIncludeMashOut}
          />
          <Toggle
            icon="fa-solid fa-bell"
            label="Температурные алерты"
            desc="Напоминание о засыпи солода и о выходе на температуру."
            checked={includeTemperatureAlerts}
            disabled={loading}
            onChange={setIncludeTemperatureAlerts}
          />
          <Toggle
            icon="fa-solid fa-hourglass-end"
            label="Алерты на окончание пауз"
            desc="В конце каждой паузы, включая Mash Out. Текст называет паузу: «Пауза 64 °C завершена»."
            checked={restEndAlerts}
            disabled={loading}
            onChange={setRestEndAlerts}
          />
          <Toggle
            icon="fa-solid fa-sliders"
            label="PID-регулировка затирания"
            desc="Точное удержание температуры на паузах и на разгонах между ними."
            checked={pidEnabled}
            disabled={loading}
            onChange={setPidEnabled}
          />
          <Toggle
            icon="fa-solid fa-temperature-half"
            label="Своя температура засыпи"
            desc="По умолчанию — первая пауза плюс 3 °C."
            checked={mashInOverride}
            disabled={loading}
            onChange={setMashInOverride}
          />
        </div>

        {mashInOverride ? (
          <label className="field">
            <span>Температура засыпи, °C</span>
            <input
              type="number"
              value={mashInTemperature}
              disabled={loading}
              onChange={(e) => setMashInTemperature(e.target.value)}
            />
          </label>
        ) : null}

        <div className="field-row">
          <label className="field">
            <span>Мощность нагрева на переходах, %</span>
            <input
              type="number"
              min={0}
              max={100}
              value={heatPowerPct}
              disabled={loading}
              onChange={(e) => setHeatPowerPct(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Мощность в паузах, %</span>
            <input
              type="number"
              min={0}
              max={100}
              value={restPowerPct}
              disabled={loading}
              onChange={(e) => setRestPowerPct(e.target.value)}
            />
          </label>
        </div>
        <div className="info-note">
          <p>
            Разгон между паузами выделяется в отдельный шаг, пока мощности различаются: подъём идёт
            на мощности переходов, пауза удерживается на своей. Уравняйте их или очистите поле,
            чтобы отдельных шагов разгона не было.
          </p>
          <p>
            Алерты на внесение хмеля и других добавок на кипе и вирпуле/хопстенде собираются
            автоматически из таймингов рецепта.
          </p>
        </div>

        <div className="profile-wizard-actions">
          <button type="button" disabled={loading} onClick={() => navigate('/profiles')}>
            Отмена
          </button>
          <button
            type="button"
            className="btn-solid"
            disabled={loading || !content}
            onClick={() => void submit()}
          >
            <i
              className={`fa-solid ${loading ? 'fa-spinner fa-spin' : 'fa-file-import'}`}
              aria-hidden="true"
            />{' '}
            {loading ? 'Собираем…' : 'Собрать профиль'}
          </button>
        </div>
      </section>
    </div>
  )
}
