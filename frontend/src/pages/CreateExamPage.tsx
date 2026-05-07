import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { createExam } from '../lib/api'
import { SectionCard } from '../components/SectionCard'

export function CreateExamPage() {
  const navigate = useNavigate()
  const [title, setExamTitle] = useState('')
  const [description, setExamDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const exam = await createExam({ title, description: description || null })
      navigate(`/exams/${exam.id}/rubric`)
    } catch (error) {
      setError(error instanceof Error ? error.message : '创建考试失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <SectionCard title="新建考试" description="先填写考试名称和简要说明，再上传评分标准 PDF。">
        <form className="space-y-5" onSubmit={handleSubmit}>
          <label className="block space-y-2">
            <span className="text-sm font-semibold text-ink-800">考试名称</span>
            <input
              value={title}
              onChange={(event) => setExamTitle(event.target.value)}
              required
              placeholder="例如：热力学期中小测"
              className="w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 outline-none ring-0 transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
            />
          </label>
          <label className="block space-y-2">
            <span className="text-sm font-semibold text-ink-800">考试说明</span>
            <textarea
              value={description}
              onChange={(event) => setExamDescription(event.target.value)}
              rows={5}
              placeholder="填写课程、考试范围或特殊说明，帮助 AI 更准确解析评分标准。"
              className="w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
            />
          </label>
          {error ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
          <div className="flex flex-wrap gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? '正在创建...' : '创建考试'}
            </button>
            <button
              type="button"
              onClick={() => navigate('/exams')}
              className="rounded-full border border-ink-900/10 bg-white px-5 py-3 text-sm font-semibold text-ink-950 transition hover:bg-paper"
            >
              取消
            </button>
          </div>
        </form>
      </SectionCard>

      <SectionCard
        title="推荐流程"
        description="按下面顺序操作，可以快速完成一次从建考试到复核分数的流程。"
      >
        <ol className="space-y-4 text-sm leading-6 text-ink-700">
          <li className="rounded-2xl border border-ink-900/10 bg-white/80 p-4">1. 创建考试。</li>
          <li className="rounded-2xl border border-ink-900/10 bg-white/80 p-4">2. 上传评分标准 PDF。</li>
          <li className="rounded-2xl border border-ink-900/10 bg-white/80 p-4">3. 解析并编辑评分标准。</li>
          <li className="rounded-2xl border border-ink-900/10 bg-white/80 p-4">4. 上传学生答卷并复核 AI 预评分。</li>
        </ol>
      </SectionCard>
    </div>
  )
}
