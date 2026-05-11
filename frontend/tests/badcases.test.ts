import assert from 'node:assert/strict'

import {
  badCaseKey,
  badCaseStatusTone,
  buildBadCaseQuery,
  formatBadCaseRoute,
  formatBadCaseStatus,
  isBadCaseExportable,
  renderedExamFilePagePath,
} from '../src/lib/badcases'

assert.equal(
  badCaseKey('rendered/submissions/1/pages/page-001.png', 'vision_student_extraction'),
  'vision_student_extraction::rendered/submissions/1/pages/page-001.png',
)
assert.equal(
  buildBadCaseQuery({ status: 'ready', route_key: 'vision_roster', search: '张三', page: 2, page_size: 25 }),
  '?route_key=vision_roster&status=ready&search=%E5%BC%A0%E4%B8%89&page=2&page_size=25',
)
assert.equal(buildBadCaseQuery({}), '')
assert.equal(formatBadCaseRoute('vision_split_header'), '拆分页眉')
assert.equal(formatBadCaseRoute('vision_student_extraction'), '学生答题识别')
assert.equal(formatBadCaseStatus('pending'), '待处理')
assert.equal(formatBadCaseStatus('exported'), '已导出')
assert.equal(badCaseStatusTone('ready'), 'bg-sage-100 text-sage-400 ring-sage-200')
assert.equal(isBadCaseExportable({ status: 'ready', ground_truth_text: ' 正确文本 ' }), true)
assert.equal(isBadCaseExportable({ status: 'ready', ground_truth_text: '   ' }), false)
assert.equal(isBadCaseExportable({ status: 'pending', ground_truth_text: '正确文本' }), false)
assert.equal(renderedExamFilePagePath(3, 'rubric', 9, 2), 'rendered/exams/3/rubric/9/page-002.png')
