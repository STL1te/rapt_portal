import { useState } from 'react'
import type { BatchInput } from '@/types'
import { today } from '@/lib/batch'

const EMPTY: BatchInput = {
  name: '',
  bottled_on: '',
  volume_l: 0,
  carbonation_until: '',
  conditioning_until: '',
  finished_on: null,
  notes: null,
}

export default function BatchForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: BatchInput
  submitLabel: string
  onSubmit: (input: BatchInput) => Promise<unknown>
  onCancel: () => void
}) {
  const [form, setForm] = useState<BatchInput>(initial ?? { ...EMPTY, bottled_on: today() })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof BatchInput>(key: K, value: BatchInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit({ ...form, notes: form.notes?.trim() || null })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <form className="panel profile-wizard-panel" onSubmit={(e) => void submit(e)}>
      <label className="field">
        <span>Название</span>
        <input
          required
          value={form.name}
          placeholder="Клон Короны Экстра"
          onChange={(e) => set('name', e.target.value)}
        />
      </label>
      <div className="batch-form-grid">
        <label className="field">
          <span>Дата розлива</span>
          <input
            type="date"
            required
            value={form.bottled_on}
            onChange={(e) => set('bottled_on', e.target.value)}
          />
        </label>
        <label className="field">
          <span>Объём, л</span>
          <input
            type="number"
            required
            min={0.1}
            step={0.1}
            value={form.volume_l || ''}
            onChange={(e) => set('volume_l', Number(e.target.value))}
          />
        </label>
        <label className="field">
          <span>Конец газации</span>
          <input
            type="date"
            required
            min={form.bottled_on}
            value={form.carbonation_until}
            onChange={(e) => set('carbonation_until', e.target.value)}
          />
        </label>
        <label className="field">
          <span>Конец созревания</span>
          <input
            type="date"
            required
            min={form.carbonation_until || form.bottled_on}
            value={form.conditioning_until}
            onChange={(e) => set('conditioning_until', e.target.value)}
          />
        </label>
        {initial?.finished_on ? (
          <label className="field">
            <span>Дата окончания</span>
            <input
              type="date"
              min={form.bottled_on}
              value={form.finished_on ?? ''}
              onChange={(e) => set('finished_on', e.target.value || null)}
            />
          </label>
        ) : null}
      </div>
      <label className="field">
        <span>Заметки</span>
        <textarea
          rows={3}
          value={form.notes ?? ''}
          onChange={(e) => set('notes', e.target.value)}
        />
      </label>
      {error ? <p className="error">{error}</p> : null}
      <div className="profile-wizard-actions">
        <button type="button" disabled={busy} onClick={onCancel}>
          Отмена
        </button>
        <button type="submit" className="btn-solid" disabled={busy}>
          {busy ? 'Сохранение…' : submitLabel}
        </button>
      </div>
    </form>
  )
}
