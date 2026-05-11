import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { BadCaseReportButton } from '../src/components/BadCaseReportButton'

const html = renderToStaticMarkup(
  <BadCaseReportButton
    imageStoragePath="rendered/submissions/1/pages/page-001.png"
    routeKey="vision_student_extraction"
    examId={1}
    submissionId={2}
    compact
  />,
)

assert.match(html, /报告 OCR/)
assert.match(html, /学生答题识别/)
assert.match(html, /rendered\/submissions\/1\/pages\/page-001\.png/)
