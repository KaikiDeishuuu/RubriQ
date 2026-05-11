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

const labelledHtml = renderToStaticMarkup(
  <BadCaseReportButton
    imageStoragePath="rendered/exams/3/rubric/9/page-003.png"
    routeKey="vision_rubric"
    examId={3}
    label="报告第 3 页 OCR"
    compact
  />,
)

assert.match(labelledHtml, /报告第 3 页 OCR/)

const openHtml = renderToStaticMarkup(
  <BadCaseReportButton
    imageStoragePath="rendered/exams/3/rubric/9/page-001.png"
    routeKey="vision_rubric"
    examId={3}
    initialOpen
  />,
)

assert.match(openHtml, /报告 OCR Bad Case/)
assert.doesNotMatch(openHtml, /fixed inset-0/)
assert.match(openHtml, /absolute left-0 top-full/)
