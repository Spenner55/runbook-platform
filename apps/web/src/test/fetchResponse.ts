export function createJsonResponse(body: unknown, init?: { status?: number }) {
  const status = init?.status ?? 200

  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
  } as Response
}
