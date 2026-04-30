import { useState } from 'react'

import { useAuth } from '../../auth/context/useAuth'
import { getAccessToken } from '../../auth/authTokenStore'
import { buildApiUrl } from '../../../shared/api/env'
import { createArtifactDownloadUrl } from '../api/artifactsApi'

interface DownloadState {
  isLoading: boolean
  error: string | null
}

async function readDownloadError(response: Response) {
  try {
    const contentType = response.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) {
      const data = (await response.json()) as {
        errors?: Array<{ detail?: unknown }>
        detail?: unknown
      }
      const firstDetail = data.errors?.[0]?.detail
      if (typeof firstDetail === 'string') {
        return firstDetail
      }
      if (typeof data.detail === 'string') {
        return data.detail
      }
    }
  } catch {
    // Fall through to the generic status message below.
  }

  return `Download failed with status ${response.status}.`
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.rel = 'noopener noreferrer'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(objectUrl)
}

export function useArtifactDownload() {
  const { accessToken } = useAuth()
  const [state, setState] = useState<DownloadState>({ isLoading: false, error: null })

  async function download(artifactId: string, organizationId: string) {
    setState({ isLoading: true, error: null })
    try {
      if (!accessToken) {
        throw new Error('You must be signed in to download artifacts.')
      }

      const result = await createArtifactDownloadUrl(artifactId, organizationId)
      const contentAccessToken = getAccessToken() ?? accessToken
      const response = await fetch(buildApiUrl(result.download_url), {
        credentials: 'include',
        headers: {
          Accept: '*/*',
          Authorization: `Bearer ${contentAccessToken}`,
          'X-Organization-Id': organizationId,
        },
      })
      if (!response.ok) {
        throw new Error(await readDownloadError(response))
      }
      const blob = await response.blob()
      triggerBrowserDownload(blob, result.filename)
      setState({ isLoading: false, error: null })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Download failed'
      setState({ isLoading: false, error: message })
    }
  }

  return { ...state, download }
}
