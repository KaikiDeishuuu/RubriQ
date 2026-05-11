import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { BadCaseDrawer } from '../src/components/BadCaseDrawer'
import type { BadCase } from '../src/lib/types'

const caseItem: BadCase = {
  id: 7,
  route_key: 'vision_student_extraction',
  exam_id: 1,
  submission_id: 2,
  batch_id: null,
  batch_page_id: null,
  image_storage_path: 'rendered/submissions/2/pages/page-001.png',
  image_hash: 'a'.repeat(64),
  ocr_model: 'paddleocr',
  ocr_raw_text: '姓名 张三\n答案 A',
  ocr_error_message: null,
  trigger_reason: 'ocr_empty_text',
  trigger_source: 'auto',
  reporter_note: '需要人工确认',
  ground_truth_text: '姓名 张三\n答案 A',
  status: 'ready',
  redact_pii: true,
  last_seen_at: '2026-05-11T10:00:00Z',
  exported_at: null,
  created_at: '2026-05-11T09:00:00Z',
  updated_at: '2026-05-11T10:00:00Z',
}

const html = renderToStaticMarkup(
  <BadCaseDrawer
    caseItem={caseItem}
    saving={false}
    previewing={false}
    previewStoragePath={null}
    previewMethod={null}
    previewFailed={false}
    onClose={() => undefined}
    onSave={() => undefined}
    onPreview={() => undefined}
  />,
)

assert.match(html, /学生答题识别/)
assert.match(html, /可导出/)
assert.match(html, /OCR 原文/)
assert.match(html, /Ground truth/)
assert.match(html, /rendered\/submissions\/2\/pages\/page-001\.png/)
assert.match(html, /姓名 张三/)
