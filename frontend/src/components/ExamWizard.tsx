import { Link } from 'react-router-dom'

import { toClassNames } from '../lib/format'

export type WizardStepKey = 'create' | 'rubric' | 'roster' | 'submissions' | 'results'

export interface WizardStepStatus {
  rubricDone: boolean
  rosterDone: boolean
  submissionsReady: boolean
  hasResults: boolean
}

interface WizardStepDef {
  key: WizardStepKey
  index: number
  label: string
  description: string
}

const STEPS: WizardStepDef[] = [
  { key: 'create', index: 1, label: '创建考试', description: '填写考试名称与说明。' },
  { key: 'rubric', index: 2, label: '评分标准', description: '解析并确认 rubric。' },
  { key: 'roster', index: 3, label: '考试名单', description: '上传并确认学生名单。' },
  { key: 'submissions', index: 4, label: '学生答卷', description: '上传答卷、确认拆分、启动批改。' },
  { key: 'results', index: 5, label: '批改与导出', description: '复核成绩并导出。' },
]

interface WizardStepsProps {
  current: WizardStepKey
  examId: number | null
  status: WizardStepStatus
}

function stepCompletion(step: WizardStepKey, status: WizardStepStatus, examId: number | null): boolean {
  switch (step) {
    case 'create':
      return examId !== null
    case 'rubric':
      return status.rubricDone
    case 'roster':
      return status.rosterDone
    case 'submissions':
      return status.submissionsReady
    case 'results':
      return status.hasResults
  }
}

function stepLocked(step: WizardStepKey, status: WizardStepStatus, examId: number | null): boolean {
  if (step === 'create') return false
  if (examId === null) return true
  if (step === 'rubric') return false
  if (step === 'roster') return !status.rubricDone
  if (step === 'submissions') return !status.rubricDone || !status.rosterDone
  if (step === 'results') return !status.rubricDone || !status.rosterDone
  return false
}

function stepHref(step: WizardStepKey, examId: number | null): string {
  if (examId === null && step !== 'create') {
    return '/exams'
  }
  switch (step) {
    case 'create':
      return '/exams/new'
    case 'rubric':
      return `/exams/${examId}/rubric`
    case 'roster':
      return `/exams/${examId}/roster`
    case 'submissions':
      return `/exams/${examId}/submissions`
    case 'results':
      return `/exams/${examId}/results`
  }
}

export function ExamWizardSteps({ current, examId, status }: WizardStepsProps) {
  return (
    <nav aria-label="向导步骤" className="rounded-full border border-ink-900/10 bg-white/85 px-3 py-2 shadow-sm backdrop-blur">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-sm">
        {STEPS.map((step, idx) => {
          const isCurrent = step.key === current
          const completed = stepCompletion(step.key, status, examId)
          const locked = stepLocked(step.key, status, examId)
          const href = stepHref(step.key, examId)

          const pillClass = toClassNames(
            'inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold transition',
            isCurrent
              ? 'bg-ink-950 text-paper'
              : completed
                ? 'bg-sage-100 text-sage-500 ring-1 ring-inset ring-sage-200'
                : locked
                  ? 'text-ink-700/60 ring-1 ring-inset ring-ink-900/10'
                  : 'text-ink-950 ring-1 ring-inset ring-ink-900/10 hover:bg-paper',
          )

          const numberClass = toClassNames(
            'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold',
            isCurrent
              ? 'bg-paper text-ink-950'
              : completed
                ? 'bg-sage-200 text-sage-500'
                : 'bg-ink-900/5 text-ink-700',
          )

          const pill = (
            <span className={pillClass} aria-current={isCurrent ? 'step' : undefined}>
              <span className={numberClass}>{step.index}</span>
              <span className="whitespace-nowrap">{step.label}</span>
            </span>
          )

          return (
            <li key={step.key} className="flex items-center gap-1">
              {locked || isCurrent ? (
                <span title={locked ? '请按顺序完成上一步后再访问' : step.description}>{pill}</span>
              ) : (
                <Link to={href} title={step.description} className="rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-slateBlue-200">
                  {pill}
                </Link>
              )}
              {idx < STEPS.length - 1 ? (
                <span aria-hidden className="text-ink-700/40 select-none">·</span>
              ) : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

interface WizardNavProps {
  examId: number | null
  prev?: { label: string; to: string } | null
  next?: {
    label: string
    to: string
    disabledReason?: string | null
  } | null
}

export function WizardNav({ examId, prev, next }: WizardNavProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-ink-900/10 bg-white/70 p-3 backdrop-blur">
      <div className="flex flex-wrap gap-2">
        <Link
          to="/exams"
          className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
        >
          ← 返回考试列表
        </Link>
        {prev ? (
          <Link
            to={prev.to}
            className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
          >
            上一步：{prev.label}
          </Link>
        ) : null}
      </div>
      {next ? (
        next.disabledReason ? (
          <button
            type="button"
            disabled
            title={next.disabledReason}
            className="rounded-full bg-ink-950/40 px-4 py-2 text-xs font-semibold text-paper cursor-not-allowed"
          >
            下一步：{next.label}（{next.disabledReason}）
          </button>
        ) : (
          <Link
            to={next.to}
            className="rounded-full bg-ink-950 px-4 py-2 text-xs font-semibold text-paper transition hover:bg-ink-800"
          >
            下一步：{next.label} →
          </Link>
        )
      ) : null}
    </div>
  )
}

export function emptyWizardStatus(): WizardStepStatus {
  return {
    rubricDone: false,
    rosterDone: false,
    submissionsReady: false,
    hasResults: false,
  }
}
