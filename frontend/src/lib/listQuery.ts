/**
 * R2 Batch R2e — list state in URL query parameters (search text and page),
 * so returning from a detail page restores the list exactly.
 */
export interface ListQuery {
  q: string
  page: number
}

export function readListQuery(params: URLSearchParams): ListQuery {
  const page = Number.parseInt(params.get('page') ?? '1', 10)
  return { q: params.get('q') ?? '', page: Number.isFinite(page) && page >= 1 ? page : 1 }
}

export function listQueryParams(query: ListQuery): URLSearchParams {
  const params = new URLSearchParams()
  if (query.q) params.set('q', query.q)
  if (query.page > 1) params.set('page', String(query.page))
  return params
}

/** The list URL to return to from a detail page. */
export function listHref(base: string, query: ListQuery): string {
  const search = listQueryParams(query).toString()
  return search ? `${base}?${search}` : base
}
