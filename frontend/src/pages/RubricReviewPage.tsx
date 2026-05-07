import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { DropZone } from '../components/DropZone'
import { SectionCard } from '../components/SectionCard'
import { buildStorageUrl, createRubricItem, deleteRubricItem, getExam, parseRubricPdf, updateQuestion, updateRubricItem, uploadRubricPdf } from '../lib/api'
import { formatScore, toClassNames } from '../lib/format'
import type { ExamDetail, Question, RubricItem } from '../lib/types'

export function RubricReviewPage() {
	const { examId } = useParams()
	const numericExamId = Number(examId)
	const [exam, setExam] = useState<ExamDetail | null>(null)
	const [loading, setLoading] = useState(true)
	const [error, setError] = useState<string | null>(null)
	const [feedback, setFeedback] = useState<string | null>(null)
	const [selectedFile, setSelectedFile] = useState<File | null>(null)
	const [busy, setBusy] = useState(false)

	useEffect(() => {
		void loadExam()
	}, [numericExamId])

	async function loadExam() {
		if (!Number.isFinite(numericExamId)) {
			setError('考试 ID 无效')
			setLoading(false)
			return
		}
		try {
			setLoading(true)
			setError(null)
			setExam(await getExam(numericExamId))
		} catch (error) {
			setError(error instanceof Error ? error.message : '加载考试失败')
		} finally {
			setLoading(false)
		}
	}

	async function handleUpload() {
		if (!selectedFile || !Number.isFinite(numericExamId)) {
			return
		}
		setBusy(true)
		setFeedback(null)
		try {
			await uploadRubricPdf(numericExamId, selectedFile)
			setFeedback('评分标准 PDF 已上传，现在可以开始解析。')
			setSelectedFile(null)
			await loadExam()
		} catch (error) {
			setError(error instanceof Error ? error.message : '上传评分标准 PDF 失败')
		} finally {
			setBusy(false)
		}
	}

	async function handleParse() {
		if (!Number.isFinite(numericExamId) || !exam) {
			return
		}
		const rubricFiles = exam.files.filter((file) => file.file_type === 'rubric_pdf')
		const latestFile = rubricFiles[rubricFiles.length - 1]
		setBusy(true)
		setFeedback(null)
		try {
			const parsed = await parseRubricPdf(numericExamId, latestFile?.id)
			setExam(parsed)
			setFeedback('评分标准解析成功，请在下方检查识别出的题目和评分项。')
		} catch (error) {
			setError(error instanceof Error ? error.message : '解析评分标准 PDF 失败')
		} finally {
			setBusy(false)
		}
	}

	async function handle保存Question(question: Question, event: FormEvent<HTMLFormElement>) {
		event.preventDefault()
		const formData = new FormData(event.currentTarget)
		setBusy(true)
		try {
			await updateQuestion(question.id, {
				question_no: String(formData.get('question_no') ?? question.question_no),
				title: String(formData.get('title') ?? question.title),
				max_score: Number(formData.get('max_score') ?? question.max_score),
				order_index: Number(formData.get('order_index') ?? question.order_index),
			})
			setFeedback(`题目 ${question.question_no} 已更新。`)
			await loadExam()
		} catch (error) {
			setError(error instanceof Error ? error.message : '更新题目失败')
		} finally {
			setBusy(false)
		}
	}

	async function handle保存RubricItem(questionId: number, item: RubricItem, event: FormEvent<HTMLFormElement>) {
		event.preventDefault()
		const formData = new FormData(event.currentTarget)
		setBusy(true)
		try {
			await updateRubricItem(item.id, {
				description: String(formData.get('description') ?? item.description),
				max_score: Number(formData.get('max_score') ?? item.max_score),
				keywords: parse关键词(String(formData.get('keywords') ?? item.keywords.join(', '))),
				order_index: Number(formData.get('order_index') ?? item.order_index),
			})
			setFeedback('评分项已更新。')
			await loadExam()
		} catch (error) {
			setError(error instanceof Error ? error.message : '更新评分项失败')
		} finally {
			setBusy(false)
		}
	}

	async function handleCreateRubricItem(questionId: number, event: FormEvent<HTMLFormElement>) {
		event.preventDefault()
		const formData = new FormData(event.currentTarget)
		setBusy(true)
		try {
			await createRubricItem(questionId, {
				description: String(formData.get('description') ?? ''),
				max_score: Number(formData.get('max_score') ?? 0),
				keywords: parse关键词(String(formData.get('keywords') ?? '')),
				order_index: Number(formData.get('order_index') ?? 0),
			})
			event.currentTarget.reset()
			setFeedback('评分项已添加。')
			await loadExam()
		} catch (error) {
			setError(error instanceof Error ? error.message : '添加评分项失败')
		} finally {
			setBusy(false)
		}
	}

	async function handle删除RubricItem(questionId: number, itemId: number) {
		if (!window.confirm('确定要删除这个评分项吗？')) {
			return
		}
		setBusy(true)
		try {
			await deleteRubricItem(itemId)
			setFeedback('评分项已删除。')
			await loadExam()
		} catch (error) {
			setError(error instanceof Error ? error.message : '删除评分项失败')
		} finally {
			setBusy(false)
		}
	}

	const latestRubricFile = useMemo(() => {
		if (!exam) {
			return null
		}
		const rubricFiles = exam.files.filter((file) => file.file_type === 'rubric_pdf')
		return rubricFiles[rubricFiles.length - 1] ?? null
	}, [exam])

	return (
		<div className="space-y-6">
			<SectionCard
				title={exam ? `${exam.title} 评分标准复核` : '评分标准复核'}
				description="上传标准答案或评分标准 PDF，解析成结构化题目和评分项后再人工确认。"
				action={
					<div className="flex flex-wrap gap-2">
						<Link
							to={Number.isFinite(numericExamId) ? `/exams/${numericExamId}/submissions` : '/exams'}
							className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
						>
							学生答卷
						</Link>
						<Link
							to={Number.isFinite(numericExamId) ? `/exams/${numericExamId}/results` : '/exams'}
							className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-4 py-2 text-sm font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100"
						>
							批量结果
						</Link>
					</div>
				}
			>
				<div className="grid gap-4 md:grid-cols-3">
					<Metric label="评分标准文件" value={String(exam?.files.filter((file) => file.file_type === 'rubric_pdf').length ?? 0)} />
					<Metric label="已解析题目" value={String(exam?.questions.length ?? 0)} />
					<Metric label="总分" value={formatScore(exam?.total_score ?? 0)} />
				</div>
			</SectionCard>

			{loading ? <Message message="正在加载评分标准..." /> : null}
			{error ? <Message message={error} tone="error" /> : null}
			{feedback ? <Message message={feedback} tone="success" /> : null}

			<div className="grid gap-6 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
				<SectionCard title="上传并解析" description="先上传评分标准 PDF，解析后会生成可编辑的题目和评分项。">
					<div className="space-y-4">
						<DropZone
							title="拖拽评分标准 PDF 到这里"
							description="可上传标准答案、评分细则或批改说明 PDF，文件会保存在后端存储目录中。"
							onFilesSelected={(files) => setSelectedFile(files[0] ?? null)}
						/>
						{selectedFile ? (
							<div className="rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 text-sm text-ink-700">
								已选择文件： <span className="font-semibold text-ink-950">{selectedFile.name}</span>
							</div>
						) : null}
						<div className="flex flex-wrap gap-3">
							<button
								type="button"
								onClick={handleUpload}
								disabled={!selectedFile || busy}
								className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
							>
								上传评分标准 PDF
							</button>
							<button
								type="button"
								onClick={handleParse}
								disabled={busy || !latestRubricFile}
								className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-5 py-3 text-sm font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100 disabled:cursor-not-allowed disabled:opacity-50"
							>
								解析最新评分标准
							</button>
						</div>
						{latestRubricFile ? (
							<a
								href={buildStorageUrl(latestRubricFile.storage_path)}
								target="_blank"
								rel="noreferrer"
								className="inline-flex rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
							>
								打开最新评分标准 PDF
							</a>
						) : null}
						<div className="rounded-2xl border border-ink-900/10 bg-white px-4 py-3 text-sm leading-6 text-ink-700">
							解析完成后，请先检查并调整每道题和评分项，再处理学生答卷。
						</div>
					</div>
				</SectionCard>

				<SectionCard title="已解析的评分标准" description="逐题检查题目、总分和每条评分项，确认无误后再进入学生答卷处理。">
					{exam?.questions.length ? (
						<div className="space-y-4">
							{exam.questions.map((question) => (
								<QuestionEditorCard
									key={question.id}
									question={question}
									on保存Question={handle保存Question}
									on保存RubricItem={handle保存RubricItem}
									on删除RubricItem={handle删除RubricItem}
									onCreateRubricItem={handleCreateRubricItem}
									disabled={busy}
								/>
							))}
						</div>
					) : (
						<div className="rounded-2xl border border-dashed border-ink-900/15 bg-paper px-4 py-10 text-center text-sm text-ink-700">
							暂无已解析题目。请先上传并解析评分标准 PDF。
						</div>
					)}
				</SectionCard>
			</div>
		</div>
	)
}

function QuestionEditorCard({
	question,
	on保存Question,
	on保存RubricItem,
	on删除RubricItem,
	onCreateRubricItem,
	disabled,
}: {
	question: Question
	on保存Question: (question: Question, event: FormEvent<HTMLFormElement>) => Promise<void>
	on保存RubricItem: (questionId: number, item: RubricItem, event: FormEvent<HTMLFormElement>) => Promise<void>
	on删除RubricItem: (questionId: number, itemId: number) => Promise<void>
	onCreateRubricItem: (questionId: number, event: FormEvent<HTMLFormElement>) => Promise<void>
	disabled: boolean
}) {
	return (
		<article className="rounded-3xl border border-ink-900/10 bg-white/90 p-4 shadow-soft">
			<form
				className="space-y-4"
				onSubmit={async (event) => {
					await on保存Question(question, event)
				}}
			>
				<div className="flex flex-wrap items-center justify-between gap-3">
					<div>
						<h3 className="font-display text-3xl text-ink-950">题目{question.question_no}</h3>
						<p className="mt-1 text-sm text-ink-700">编辑题目和评分项，后续评分证据会按这些规则追溯。</p>
					</div>
					<span className="rounded-full bg-slateBlue-50 px-3 py-1 text-xs font-semibold text-slateBlue-500 ring-1 ring-inset ring-slateBlue-100">
						{question.rubric_items.length} 个评分项
					</span>
				</div>

				<div className="grid gap-3 md:grid-cols-[1.1fr_2fr_0.6fr_0.6fr_auto]">
					<label className="block space-y-2">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">题号</span>
						<input
							name="question_no"
							defaultValue={question.question_no}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">题目标题</span>
						<input
							name="title"
							defaultValue={question.title}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">满分</span>
						<input
							name="max_score"
							type="number"
							step="0.1"
							defaultValue={String(question.max_score)}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">排序</span>
						<input
							name="order_index"
							type="number"
							defaultValue={String(question.order_index)}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<div className="flex items-end">
						<button
							type="submit"
							disabled={disabled}
							className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
						>
							保存
						</button>
					</div>
				</div>
			</form>

			<div className="mt-5 space-y-3">
				{question.rubric_items.map((item) => (
					<form
						key={item.id}
						className="grid gap-3 rounded-2xl border border-ink-900/10 bg-paper p-4 md:grid-cols-[2fr_0.55fr_1fr_0.45fr_auto_auto]"
						onSubmit={async (event) => {
							await on保存RubricItem(question.id, item, event)
						}}
					>
						<label className="block space-y-2 md:col-span-1">
							<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">评分说明</span>
							<input
								name="description"
								defaultValue={item.description}
								className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
							/>
						</label>
						<label className="block space-y-2">
							<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">分值</span>
							<input
								name="max_score"
								type="number"
								step="0.1"
								defaultValue={String(item.max_score)}
								className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
							/>
						</label>
						<label className="block space-y-2 md:col-span-1">
							<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">关键词</span>
							<input
								name="keywords"
								defaultValue={item.keywords.join(', ')}
								className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
							/>
						</label>
						<label className="block space-y-2">
							<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">排序</span>
							<input
								name="order_index"
								type="number"
								defaultValue={String(item.order_index)}
								className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
							/>
						</label>
						<div className="flex items-end">
							<button
								type="submit"
								disabled={disabled}
								className="rounded-full bg-slateBlue-400 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slateBlue-500 disabled:cursor-not-allowed disabled:opacity-50"
							>
								保存
							</button>
						</div>
						<div className="flex items-end">
							<button
								type="button"
								disabled={disabled}
								onClick={async () => {
									await on删除RubricItem(question.id, item.id)
								}}
								className="rounded-full border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
							>
								删除
							</button>
						</div>
					</form>
				))}
			</div>

			<form
				className="mt-5 grid gap-3 rounded-2xl border border-dashed border-ink-900/15 bg-white p-4 md:grid-cols-[2fr_0.55fr_1fr_0.45fr_auto]"
				onSubmit={async (event) => {
					await onCreateRubricItem(question.id, event)
				}}
			>
				<label className="block space-y-2">
					<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">新增评分项</span>
					<input
						name="description"
						placeholder="例如：写出关键公式或核心依据"
						className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
					/>
				</label>
				<label className="block space-y-2">
					<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">分值</span>
					<input
						name="max_score"
						type="number"
						step="0.1"
						defaultValue="1"
						className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
					/>
				</label>
				<label className="block space-y-2 md:col-span-1">
					<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">关键词</span>
					<input
						name="keywords"
						placeholder="关键词1, 关键词2"
						className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
					/>
				</label>
				<label className="block space-y-2">
					<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">排序</span>
					<input
						name="order_index"
						type="number"
						defaultValue={String(question.rubric_items.length)}
						className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
					/>
				</label>
				<div className="flex items-end">
					<button
						type="submit"
						disabled={disabled}
						className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
					>
						添加评分项
					</button>
				</div>
			</form>
		</article>
	)
}

function Metric({ label, value }: { label: string; value: string }) {
	return (
		<div className="rounded-2xl border border-ink-900/10 bg-white px-4 py-4 shadow-sm">
			<div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">{label}</div>
			<div className="mt-2 font-display text-3xl text-ink-950">{value}</div>
		</div>
	)
}

function Message({ message, tone = 'neutral' }: { message: string; tone?: 'neutral' | 'error' | 'success' }) {
	return (
		<div
			className={toClassNames(
				'rounded-2xl border px-4 py-3 text-sm',
				tone === 'error'
					? 'border-red-200 bg-red-50 text-red-700'
					: tone === 'success'
						? 'border-sage-100 bg-sage-50 text-sage-400'
						: 'border-ink-900/10 bg-white/80 text-ink-700',
			)}
		>
			{message}
		</div>
	)
}

function parse关键词(input: string): string[] {
	return input
		.split(',')
		.map((part) => part.trim())
		.filter(Boolean)
}