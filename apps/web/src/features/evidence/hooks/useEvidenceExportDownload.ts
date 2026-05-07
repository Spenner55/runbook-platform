import { useMutation } from '@tanstack/react-query'

import { triggerExportDownload } from '../api/evidenceApi'

export function useEvidenceExportDownload() {
  return useMutation({
    mutationFn: ({ exportId, filename }: { exportId: string; filename?: string }) =>
      triggerExportDownload(exportId, filename),
  })
}
