import { useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { triggerPortalDataSync, triggerSync, triggerYeastSync } from '../api'
import { useTitle } from '../useTitle'

type SyncCardProps = {
  title: string
  description: string
  actionLabel: string
  disabled: boolean
  children?: ReactNode
  onRun: () => Promise<void>
}

function SyncCard({ title, description, actionLabel, disabled, children, onRun }: SyncCardProps) {
  return (
    <section className="sync-card">
      <div className="sync-card-body">
        <h3 className="panel-title">{title}</h3>
        <p className="muted">{description}</p>
        {children}
      </div>
      <button type="button" disabled={disabled} onClick={() => void onRun()}>
        {actionLabel}
      </button>
    </section>
  )
}

export default function SystemSyncs() {
  useTitle('Системные синки')
  const queryClient = useQueryClient()
  const [portalToken, setPortalToken] = useState('')
  const [forcePortalSync, setForcePortalSync] = useState(false)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)

  async function runSync(action: string, runner: () => Promise<void>) {
    setBusyAction(action)
    setSyncMessage(null)
    try {
      await runner()
      await queryClient.invalidateQueries({ queryKey: ['hydrometers'] })
      await queryClient.invalidateQueries({ queryKey: ['brewzillas'] })
      await queryClient.invalidateQueries({ queryKey: ['yeasts'] })
      setSyncMessage('Синк завершён.')
    } catch (error) {
      setSyncMessage(`Ошибка: ${String(error)}`)
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <>
      <div className="page-head">
        <h2>Системные синки</h2>
      </div>

      <section className="panel">
        <label className="field">
          <span>Portal token</span>
          <textarea
            className="sync-token"
            rows={4}
            value={portalToken}
            onChange={(event) => setPortalToken(event.target.value)}
            placeholder="Bearer eyJ..."
          />
        </label>
        <p className="muted">
          Используется для portal data sync и sync yeasts. На сервере не сохраняется.
        </p>
        {busyAction ? <p className="muted">Идёт синк…</p> : null}
        {syncMessage ? (
          <p className={syncMessage.startsWith('Ошибка:') ? 'error' : 'muted'}>{syncMessage}</p>
        ) : null}
      </section>

      <div className="sync-card-grid">
        <SyncCard
          title="Обычный sync"
          description="Базовый синк устройств и активных сессий через обычный RAPT API."
          actionLabel="Запустить"
          disabled={busyAction !== null}
          onRun={() => runSync('base', async () => void (await triggerSync()))}
        />

        <SyncCard
          title="Portal data sync"
          description="Подтягивает историю profile sessions из portal-only API и обновляет локальные сессии."
          actionLabel="Запустить"
          disabled={busyAction !== null || !portalToken.trim()}
          onRun={() =>
            runSync(
              'portal',
              async () => void (await triggerPortalDataSync(portalToken, forcePortalSync)),
            )
          }
        >
          <label className="sync-checkbox">
            <input
              type="checkbox"
              checked={forcePortalSync}
              onChange={(event) => setForcePortalSync(event.target.checked)}
            />
            <span>Force: перекачать telemetry для всех portal sessions</span>
          </label>
        </SyncCard>

        <SyncCard
          title="Sync yeasts"
          description="Обновляет локальный каталог дрожжей из portal inventory."
          actionLabel="Запустить"
          disabled={busyAction !== null || !portalToken.trim()}
          onRun={() => runSync('yeasts', async () => void (await triggerYeastSync(portalToken)))}
        />
      </div>
    </>
  )
}
