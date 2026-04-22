import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useOrganizations } from '../../features/organizations/hooks/useOrganizations'
import { useCreateRunbook } from '../../features/runbooks/hooks/useCreateRunbook'
import { useRunbooks } from '../../features/runbooks/hooks/useRunbooks'
import {
  getApiErrorMessage,
  getApiFieldError,
} from '../../shared/api/client'

export function RunbooksPage() {
  const [searchParams] = useSearchParams()
  const organizationId = searchParams.get('organizationId')
  const organizationsQuery = useOrganizations()
  const runbooksQuery = useRunbooks(organizationId)
  const createRunbook = useCreateRunbook()
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [rawContent, setRawContent] = useState('')

  const selectedOrganization = useMemo(
    () =>
      organizationsQuery.data?.find(
        (organization) => organization.id === organizationId,
      ),
    [organizationId, organizationsQuery.data],
  )

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!organizationId) {
      return
    }

    await createRunbook.mutateAsync({
      organization_id: organizationId,
      title: title.trim(),
      slug: slug.trim(),
      raw_content: rawContent,
    })

    setTitle('')
    setSlug('')
    setRawContent('')
  }

  if (!organizationId) {
    return (
      <section className="panel">
        <div className="panel__header">
          <p className="eyebrow">Step 2</p>
          <h2>Select an organization first</h2>
          <p className="muted">
            Open runbooks from the organizations page so the route carries
            <code> organizationId</code> in the query string.
          </p>
        </div>
        <Link className="button" to="/organizations">
          Back to organizations
        </Link>
      </section>
    )
  }

  return (
    <section className="page-grid">
      <article className="panel">
        <div className="panel__header">
          <p className="eyebrow">Step 2</p>
          <h2>Create a runbook</h2>
          <p className="muted">
            Organization:{' '}
            <strong>{selectedOrganization?.name ?? organizationId}</strong>
          </p>
        </div>

        <form className="stack-md" onSubmit={handleSubmit}>
          <label className="field">
            <span className="field__label">Title</span>
            <input
              className="input"
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Deploy API service"
              required
              value={title}
            />
            {getApiFieldError(createRunbook.error, 'title') ? (
              <span className="field__error">
                {getApiFieldError(createRunbook.error, 'title')}
              </span>
            ) : null}
          </label>

          <label className="field">
            <span className="field__label">Slug</span>
            <input
              className="input"
              onChange={(event) => setSlug(event.target.value)}
              placeholder="deploy-api-service"
              required
              value={slug}
            />
            {getApiFieldError(createRunbook.error, 'slug') ? (
              <span className="field__error">
                {getApiFieldError(createRunbook.error, 'slug')}
              </span>
            ) : null}
          </label>

          <label className="field">
            <span className="field__label">Raw content</span>
            <textarea
              className="input input--textarea"
              onChange={(event) => setRawContent(event.target.value)}
              placeholder={'1. Verify deployment window\n2. Apply migrations\n3. Restart service'}
              rows={8}
              value={rawContent}
            />
          </label>

          {createRunbook.error ? (
            <p className="banner banner--error">
              {getApiErrorMessage(createRunbook.error)}
            </p>
          ) : null}

          <button className="button" disabled={createRunbook.isPending} type="submit">
            {createRunbook.isPending ? 'Creating…' : 'Create runbook'}
          </button>
        </form>
      </article>

      <article className="panel">
        <div className="panel__header">
          <p className="eyebrow">Source documents</p>
          <h2>Runbooks</h2>
          <p className="muted">
            Generate a workflow from any stored runbook.
          </p>
        </div>

        {runbooksQuery.isLoading ? <p className="muted">Loading runbooks…</p> : null}
        {runbooksQuery.error ? (
          <p className="banner banner--error">
            {getApiErrorMessage(runbooksQuery.error)}
          </p>
        ) : null}

        {runbooksQuery.data?.length ? (
          <ul className="list">
            {runbooksQuery.data.map((runbook) => (
              <li className="list__item" key={runbook.id}>
                <div>
                  <strong>{runbook.title}</strong>
                  <p className="muted">
                    <code>{runbook.slug}</code> · {runbook.status}
                  </p>
                </div>
                <Link
                  className="button button--ghost"
                  to={`/workflows/new?runbookId=${runbook.id}`}
                >
                  Generate workflow
                </Link>
              </li>
            ))}
          </ul>
        ) : null}

        {!runbooksQuery.isLoading && !runbooksQuery.data?.length ? (
          <p className="muted">No runbooks for this organization yet.</p>
        ) : null}
      </article>
    </section>
  )
}
