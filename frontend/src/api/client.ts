type RequestOptions = {
  signal?: AbortSignal
}

export async function get<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const r = await fetch(path, { signal: options.signal })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export async function post<T>(
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}
