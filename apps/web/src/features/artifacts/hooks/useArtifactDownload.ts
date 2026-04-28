import { useState } from 'react'

import { createArtifactDownloadUrl } from '../api/artifactsApi'

interface DownloadState {
  isLoading: boolean
  error: string | null
}

export function useArtifactDownload() {
  const [state, setState] = useState<DownloadState>({ isLoading: false, error: null })

  async function download(artifactId: string) {
    setState({ isLoading: true, error: null })
    try {
      const result = await createArtifactDownloadUrl(artifactId)
      window.open(result.download_url, '_blank', 'noopener,noreferrer')
      setState({ isLoading: false, error: null })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Download failed'
      setState({ isLoading: false, error: message })
    }
  }

  return { ...state, download }
}
