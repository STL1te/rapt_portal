import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { generateProfile, type ProfileGenerationStage } from '@/api'
import { useTitle } from '@/hooks/useTitle'

const STAGE_LABEL: Record<ProfileGenerationStage, string> = {
  generating: 'Модель собирает профиль…',
  checking_structure: 'Проверяем шаги и параметры…',
  checking_recipe: 'Сверяем профиль с исходным описанием…',
  repairing: 'Исправляем найденные несоответствия…',
  checking_fixed_structure: 'Проверяем исправленные шаги…',
  checking_fixed_recipe: 'Повторно сверяем с описанием…',
}

export default function ProfileWizard() {
  useTitle('AI-мастер профилей')
  const navigate = useNavigate()
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState<ProfileGenerationStage | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)
    const trimmed = description.trim()
    if (trimmed.length < 8) {
      setError('Опишите варку минимум в 8 символах')
      return
    }
    setLoading(true)
    setStage('generating')
    try {
      const profile = await generateProfile(trimmed, setStage)
      // hand the unsaved profile to the editor; nothing is persisted until saved there
      navigate('/profiles/new', { state: { generated: profile } })
    } catch {
      setError('Не удалось собрать профиль через AI-мастер')
      setLoading(false)
      setStage(null)
    }
  }

  return (
    <div>
      <a className="back" onClick={() => navigate('/profiles')}>
        <i className="fa-solid fa-arrow-left" /> Профили
      </a>

      <div className="page-head">
        <div>
          <h2>AI-мастер профилей</h2>
          <p className="editor-subtitle">
            Опишите варку обычным текстом — мастер соберёт профиль BrewZilla и откроет его в
            редакторе. Ничего не сохранится, пока вы не нажмёте «Сохранить черновик».
          </p>
        </div>
      </div>

      <section className="panel profile-wizard-panel">
        <h3 className="profile-wizard-title">
          <i className="fa-solid fa-wand-magic-sparkles" /> Описание варки
        </h3>
        {error ? <p className="error">{error}</p> : null}
        <label className="field">
          <span>Описание варки</span>
          <textarea
            rows={10}
            placeholder="Американский pale ale, 23 литра. Одноступенчатое затирание 67 °C 60 минут, mash-out 78 °C 10 минут, кип 60 минут. Алерт на добавление хмеля за 15 минут до конца кипа."
            value={description}
            disabled={loading}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        {loading && stage ? (
          <div className="profile-wizard-progress" role="status" aria-live="polite">
            <i className="fa-solid fa-spinner fa-spin" aria-hidden="true" />
            <div>
              <strong>{STAGE_LABEL[stage]}</strong>
              <span>Это может занять несколько минут.</span>
            </div>
            <span className="profile-wizard-progress-bar" aria-hidden="true" />
          </div>
        ) : null}
        <div className="profile-wizard-actions">
          <button type="button" disabled={loading} onClick={() => navigate('/profiles')}>
            Отмена
          </button>
          <button
            type="button"
            className="btn-solid"
            disabled={loading}
            onClick={() => void submit()}
          >
            <i
              className={`fa-solid ${loading ? 'fa-spinner fa-spin' : 'fa-wand-magic-sparkles'}`}
              aria-hidden="true"
            />{' '}
            {loading ? 'Собираем…' : 'Собрать профиль'}
          </button>
        </div>
      </section>
    </div>
  )
}
