import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { BadCasesPageView } from '../src/pages/BadCasesPage'
import type { BadCase, BadCaseStatsItem } from '../src/lib/types'

const caseItem: BadCase = {
  id: 11,
  route_key: 'vision_roster',
  exam_id: 3,
  submission_id: null,
  batch_id: null,
  batch_page_id: null,
  image_storage_path: 'rendered/exams/3/roster/page-001.png',
  image_hash: 'b'.repeat(64),
  ocr_model: 'paddleocr',
  ocr_raw_text: '李四 20240001',
  ocr_error_message: null,
  trigger_reason: 'manual_report',
  trigger_source: 'manual',
  reporter_note: null,
  ground_truth_text: null,
  status: 'pending',
  redact_pii: true,
  last_seen_at: '2026-05-11T10:00:00Z',
  exported_at: null,
  created_at: '2026-05-11T09:00:00Z',
  updated_at: '2026-05-11T10:00:00Z',
}

const stats: BadCaseStatsItem[] = [
  { route_key: 'vision_roster', status: 'pending', count: 2 },
  { route_key: 'vision_student_extraction', status: 'ready', count: 1 },
]

const html = renderToStaticMarkup(
  <BadCasesPageView
    cases={[caseItem]}
    stats={stats}
    total={1}
    page={1}
    pageSize={20}
    loading={false}
    error={null}
    filters={{ route_key: '', status: '', search: '', page: 1, page_size: 20 }}
    exporting={false}
    onFiltersChange={() => undefined}
    onSelectCase={() => undefined}
    onExport={() => undefined}
    onRefresh={() => undefined}
  />,
)

assert.match(html, /PaddleOCR Bad Cases/)
assert.match(html, /名单识别/)
assert.match(html, /待处理/)
assert.match(html, /manual_report/)
assert.match(html, /rendered\/exams\/3\/roster\/page-001\.png/)
assert.match(html, /可导出样本/)
assert.match(html, /导出 ZIP/)
