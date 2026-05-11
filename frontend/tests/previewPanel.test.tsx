import assert from 'node:assert/strict'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { PreviewPanel } from '../src/components/PreviewPanel'

const html = renderToStaticMarkup(
  <PreviewPanel
    title="页面预览"
    description="检查每页 OCR 结果。"
    pages={[{ label: '第 1 页', storagePath: 'rendered/submissions/1/pages/page-001.png' }]}
    activeIndex={0}
    onChange={() => undefined}
    action={<button type="button">报告 OCR</button>}
  />,
)

const headerStart = html.indexOf('<div class="mb-4 flex items-start justify-between gap-4">')
const imageStart = html.indexOf('点击放大查看')
const buttonIndex = html.indexOf('报告 OCR')

assert.notEqual(headerStart, -1)
assert.notEqual(imageStart, -1)
assert.notEqual(buttonIndex, -1)
assert.ok(buttonIndex > headerStart)
assert.ok(buttonIndex < imageStart)
