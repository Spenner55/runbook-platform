import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import {
  getApiErrorMessage,
  getApiFieldError,
} from '../../shared/api/client'
import { useCreateOrganization } from '../../features/organizations/hooks/useCreateOrganization'
import { useOrganizations } from '../../features/organizations/hooks/useOrganizations'

export function OrganizationsPage() {
  const organizationsQuery = useOrganizations()
  const createOrganization = useCreateOrganization()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await createOrganization.mutateAsync({
      name: name.trim(),
      slug: slug.trim(),
    })
    setName('')
    setSlug('')
  }

  return (
    <section className="page-grid">
      <article className="panel">
        <div className="panel__header">
          <p className="eyebrow">Step 1</p>
          <h2>Create an organization</h2>
          <p className="muted">
            Organizations anchor the rest of the Phase 1 flow.
          </p>
        </div>

        <form className="stack-md" onSubmit={handleSubmit}>
          <label className="field">
            <span className="field__label">Name</span>
            <input
              className="input"
              name="name"
              onChange={(event) => setName(event.target.value)}
              placeholder="Platform Operations"
              required
              value={name}
            />
            {getApiFieldError(createOrganization.error, 'name') ? (
              <span className="field__error">
                {getApiFieldError(createOrganization.error, 'name')}
              </span>
            ) : null}
          </label>

          <label className="field">
            <span className="field__label">Slug</span>
            <input
              className="input"
              name="slug"
              onChange={(event) => setSlug(event.target.value)}
              placeholder="platform-ops"
              required
              value={slug}
            />
            {getApiFieldError(createOrganization.error, 'slug') ? (
              <span className="field__error">
                {getApiFieldError(createOrganization.error, 'slug')}
              </span>
            ) : null}
          </label>

          {createOrganization.error ? (
            <p className="banner banner--error">
              {getApiErrorMessage(createOrganization.error)}
            </p>
          ) : null}

          <button
            className="button"
            disabled={createOrganization.isPending}
            type="submit"
          >
            {createOrganization.isPending ? 'Creating…' : 'Create organization'}
          </button>
        </form>
      </article>

      <article className="panel">
        <div className="panel__header">
          <p className="eyebrow">Inventory</p>
          <h2>Organizations</h2>
          <p className="muted">
            Continue the slice by jumping into runbooks for a selected tenant.
          </p>
        </div>

        {organizationsQuery.isLoading ? <p className="muted">Loading organizations…</p> : null}
        {organizationsQuery.error ? (
          <p className="banner banner--error">
            {getApiErrorMessage(organizationsQuery.error)}
          </p>
        ) : null}

        {organizationsQuery.data?.length ? (
          <ul className="list">
            {organizationsQuery.data.map((organization) => (
              <li className="list__item" key={organization.id}>
                <div>
                  <strong>{organization.name}</strong>
                  <p className="muted">
                    <code>{organization.slug}</code>
                  </p>
                </div>
                <Link
                  className="button button--ghost"
                  to={`/runbooks?organizationId=${organization.id}`}
                >
                  View runbooks
                </Link>
              </li>
            ))}
          </ul>
        ) : null}

        {!organizationsQuery.isLoading && !organizationsQuery.data?.length ? (
          <p className="muted">No organizations yet.</p>
        ) : null}
      </article>
    </section>
  )
}
