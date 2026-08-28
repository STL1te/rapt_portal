type RequestOptions = {
  signal?: AbortSignal
}

/** Throw with the reason the server gave, not just its status code.
 *
 * FastAPI puts it in `detail` — a string for our own HTTPExceptions, a list of
 * per-field objects when request validation fails. Without reading the body the
 * caller only ever sees "422 Unprocessable Entity" and has to invent a message. */
async function fail(response: Response): Promise<never> {
  let detail = ''
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') detail = body.detail
    else if (Array.isArray(body?.detail))
      detail = body.detail
        .map((e: { loc?: unknown[]; msg?: string }) =>
          [e.loc?.slice(1).join('.'), e.msg].filter(Boolean).join(': '),
        )
        .filter(Boolean)
        .join('; ')
  } catch {
    // empty or non-JSON body — fall back to the status line
  }
  throw new Error(detail || `${response.status} ${response.statusText}`)
}

export async function get<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const r = await fetch(path, { signal: options.signal })
  if (!r.ok) await fail(r)
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
  if (!r.ok) await fail(r)
  return r.json()
}
