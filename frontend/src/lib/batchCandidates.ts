import type { BatchCandidateUpdatePayload } from './types'

export function confirmAllCandidateDrafts(drafts: BatchCandidateUpdatePayload[]): BatchCandidateUpdatePayload[] {
  return drafts.map((draft) => (draft.excluded ? { ...draft, confirmed: false } : { ...draft, confirmed: true }))
}
