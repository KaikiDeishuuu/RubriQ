import { confirmAllCandidateDrafts } from '../src/lib/batchCandidates'
import type { BatchCandidateUpdatePayload } from '../src/lib/types'

function assert(condition: boolean, message: string): asserts condition {
  if (!condition) {
    throw new Error(message)
  }
}

const drafts: BatchCandidateUpdatePayload[] = [
  {
    id: 1,
    candidate_index: 1,
    start_page: 1,
    end_page: 2,
    student_name: 'Alice',
    student_id: '1001',
    confirmed: false,
    excluded: false,
    roster_entry_id: null,
  },
  {
    id: 2,
    candidate_index: 2,
    start_page: 3,
    end_page: 4,
    student_name: 'Bob',
    student_id: '1002',
    confirmed: false,
    excluded: true,
    roster_entry_id: null,
  },
]

const confirmedDrafts = confirmAllCandidateDrafts(drafts)

assert(confirmedDrafts !== drafts, 'returns a new draft list')
assert(confirmedDrafts[0] !== drafts[0], 'clones changed candidate drafts')
assert(confirmedDrafts[0].confirmed === true, 'confirms active candidates')
assert(confirmedDrafts[0].excluded === false, 'keeps active candidates included')
assert(confirmedDrafts[1].confirmed === false, 'keeps ignored candidates unconfirmed')
assert(confirmedDrafts[1].excluded === true, 'keeps ignored candidates excluded')
assert(drafts[0].confirmed === false, 'does not mutate the original draft list')
