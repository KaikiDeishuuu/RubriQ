import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { DropZone } from '../components/DropZone'
import { ExamWizardSteps, WizardNav, emptyWizardStatus } from '../components/ExamWizard'
import { SectionCard } from '../components/SectionCard'
import { confirmRubric, createRubricItem, deleteRubricItem, fetchStorageBlob, getExam, parseRubricPdf, reopenRubric, updateQuestion, updateRubricItem, uploadRubricPdf } from '../lib/api'
import { formatScore, toClassNames } from '../lib/format'
import type { ExamDetail, Question, RubricItem } from '../lib/types'

export function RubricReviewPage() {
	const { examId } = useParams()
	const numericExamId = Number(examId)
	const navigate = useNavigate()
	const [exam, setExam] = useState<ExamDetail | null>(null)
	const [loading, setLoading] = useState(true)
	const [error, setError] = useState<string | null>(null)
	const [feedback, setFeedback] = useState<string | null>(null)
	const [selectedFile, setSelectedFile] = useState<File | null>(null)
	const [busy, setBusy] = useState(false)
	const [parsing, setParsing] = useState(false)
	const [confirming, setConfirming] = useState(false)

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
		setParsing(true)
		setError(null)
		setFeedback('正在解析评分标准 PDF，通常需要几十秒，请不要关闭页面。')
		try {
			const parsed = await parseRubricPdf(numericExamId, latestFile?.id)
			setExam(parsed)
			setFeedback('评分标准解析成功，请在下方检查识别出的题目和评分项。')
		} catch (error) {
			setFeedback(null)
			setError(error instanceof Error ? error.message : '解析评分标准 PDF 失败')
		} finally {
			setParsing(false)
			setBusy(false)
		}
	}

	async function handleOpenRubricFile(storagePath: string, originalFilename: string | null) {
		setError(null)
		try {
			const blob = await fetchStorageBlob(storagePath)
			const objectUrl = URL.createObjectURL(blob)
			const newWindow = window.open(objectUrl, '_blank', 'noopener,noreferrer')
			if (!newWindow) {
				const link = document.createElement('a')
				link.href = objectUrl
				link.download = originalFilename || 'rubric.pdf'
				document.body.appendChild(link)
				link.click()
				link.remove()
			}
			window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
		} catch (err) {
			setError(err instanceof Error ? err.message : '无法打开评分标准 PDF')
		}
	}

	async function handleConfirmRubric(advance: boolean) {
		if (!Number.isFinite(numericExamId)) {
			return
		}
		setConfirming(true)
		setError(null)
		try {
			const updated = await confirmRubric(numericExamId)
			setExam(updated)
			setFeedback('评分标准已确认。')
			if (advance) {
				navigate(`/exams/${numericExamId}/roster`)
			}
		} catch (error) {
			setError(error instanceof Error ? error.message : '确认评分标准失败')
		} finally {
			setConfirming(false)
		}
	}

	async function handleReopenRubric() {
		if (!Number.isFinite(numericExamId)) {
			return
		}
		setConfirming(true)
		setError(null)
		try {
			const updated = await reopenRubric(numericExamId)
			setExam(updated)
			setFeedback('已重新打开评分标准，可以继续编辑。')
		} catch (error) {
			setError(error instanceof Error ? error.message : '重新打开评分标准失败')
		} finally {
			setConfirming(false)
		}
	}

	function parseNonNegativeNumber(value: FormDataEntryValue | null, label: string): number | null {
		const parsed = Number(value)
		if (!Number.isFinite(parsed) || parsed < 0) {
			setError(`${label}必须是非负数字`)
			return null
		}
		return parsed
	}

	function parseOptionalNonNegativeNumber(value: FormDataEntryValue | null, label: string): number | null {
		const text = String(value ?? '').trim()
		if (!text) {
			return 0
		}
		return parseNonNegativeNumber(text, label)
	}

	function parseNonNegativeInteger(value: FormDataEntryValue | null, label: string): number | null {
		const parsed = Number(value)
		if (!Number.isInteger(parsed) || parsed < 0) {
			setError(`${label}必须是非负整数`)
			return null
		}
		return parsed
	}

	async function handleSaveQuestion(question: Question, event: FormEvent<HTMLFormElement>) {
		event.preventDefault()
		const formData = new FormData(event.currentTarget)
		const maxScore = parseNonNegativeNumber(formData.get('max_score'), '题目满分')
		const orderIndex = parseNonNegativeInteger(formData.get('order_index'), '题目排序')
		if (maxScore === null || orderIndex === null) {
			return
		}
		setBusy(true)
		try {
			await updateQuestion(question.id, {
				question_no: String(formData.get('question_no') ?? question.question_no),
				title: String(formData.get('title') ?? question.title),
				max_score: maxScore,
				order_index: orderIndex,
			})
			setFeedback(`题目 ${question.question_no} 已更新。`)
			await loadExam()
		} catch (error) {
			setError(error instanceof Error ? error.message : '更新题目失败')
		} finally {
			setBusy(false)
		}
	}

	async function handleSaveRubricItem(questionId: number, item: RubricItem, event: FormEvent<HTMLFormElement>) {
		event.preventDefault()
		const formData = new FormData(event.currentTarget)
		const maxScore = parseOptionalNonNegativeNumber(formData.get('max_score'), '评分项满分')
		const orderIndex = parseNonNegativeInteger(formData.get('order_index'), '评分项排序')
		if (maxScore === null || orderIndex === null) {
			return
		}
		setBusy(true)
		try {
			await updateRubricItem(item.id, {
				description: String(formData.get('description') ?? item.description),
				max_score: maxScore,
				keywords: parseKeywords(String(formData.get('keywords') ?? item.keywords.join(', '))),
				order_index: orderIndex,
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
		const form = event.currentTarget
		const formData = new FormData(form)
		const maxScore = parseOptionalNonNegativeNumber(formData.get('max_score'), '评分项满分')
		const orderIndex = parseNonNegativeInteger(formData.get('order_index'), '评分项排序')
		if (maxScore === null || orderIndex === null) {
			return
		}
		setBusy(true)
		try {
			await createRubricItem(questionId, {
				description: String(formData.get('description') ?? ''),
				max_score: maxScore,
				keywords: parseKeywords(String(formData.get('keywords') ?? '')),
				order_index: orderIndex,
			})
			form.reset()
			setFeedback(maxScore === 0 ? '补充评分说明已添加。' : '评分项已添加。')
			await loadExam()
		} catch (error) {
			setError(error instanceof Error ? error.message : '添加评分项失败')
		} finally {
			setBusy(false)
		}
	}

	async function handleDeleteRubricItem(questionId: number, itemId: number) {
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
			<ExamWizardSteps
				current="rubric"
				examId={Number.isFinite(numericExamId) ? numericExamId : null}
				status={{
					...emptyWizardStatus(),
					rubricDone: Boolean(exam && !exam.needs_rubric_review && exam.questions.length > 0),
					rosterDone: Boolean(exam && exam.roster_status === 'confirmed'),
				}}
			/>
			<WizardNav
				examId={Number.isFinite(numericExamId) ? numericExamId : null}
				prev={{ label: '考试列表', to: '/exams' }}
				next={Number.isFinite(numericExamId) ? {
					label: '考试名单',
					to: `/exams/${numericExamId}/roster`,
					disabledReason: exam && !exam.needs_rubric_review && exam.questions.length > 0
						? null
						: '请先在下方点击「确认并进入下一步」',
				} : null}
			/>
			<SectionCard
				title={exam ? `${exam.title} 评分标准复核` : '评分标准复核'}
				description="第 2 步：上传 PDF → AI 解析 → 检查每道题与评分项 → 确认。确认后才能进入下一步「考试名单」。"
				action={
					<span
						className={toClassNames(
							'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset',
							exam && !exam.needs_rubric_review
								? 'bg-sage-100 text-sage-500 ring-sage-200'
								: 'bg-gold-50 text-amber-800 ring-gold-200',
						)}
					>
						{exam && !exam.needs_rubric_review ? '已确认' : '待确认'}
					</span>
				}
			>
				<div className="grid gap-4 md:grid-cols-3">
					<Metric label="评分标准文件" value={String(exam?.files.filter((file) => file.file_type === 'rubric_pdf').length ?? 0)} />
					<Metric label="已解析题目" value={String(exam?.questions.length ?? 0)} />
					<Metric label="总分" value={formatScore(exam?.total_score ?? 0)} />
				</div>
			</SectionCard>

			{loading ? <Message message="正在加载评分标准..." /> : null}
			{parsing ? <ParsingProgress /> : null}
			{error ? <Message message={error} tone="error" /> : null}
			{feedback ? <Message message={feedback} tone={parsing ? 'neutral' : 'success'} /> : null}

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
								{busy && !parsing ? '正在上传...' : '上传评分标准 PDF'}
							</button>
							<button
								type="button"
								onClick={handleParse}
								disabled={busy || !latestRubricFile}
								className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-5 py-3 text-sm font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100 disabled:cursor-not-allowed disabled:opacity-50"
							>
								{parsing ? '正在解析...' : '解析最新评分标准'}
							</button>
						</div>
						{latestRubricFile ? (
							<button
								type="button"
								onClick={() => void handleOpenRubricFile(latestRubricFile.storage_path, latestRubricFile.original_filename)}
								className="inline-flex cursor-pointer rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
							>
								打开最新评分标准 PDF
							</button>
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
									onSaveQuestion={handleSaveQuestion}
									onSaveRubricItem={handleSaveRubricItem}
									onDeleteRubricItem={handleDeleteRubricItem}
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

				<SectionCard
					title="确认评分标准"
					description="所有题目和评分项都已检查无误后，点击「确认并进入下一步」。确认后才能继续上传考试名单。"
					className="xl:col-span-2"
				>
					<div className="flex flex-wrap items-center gap-3">
						{exam && !exam.needs_rubric_review ? (
							<>
								<span className="inline-flex items-center rounded-full bg-sage-100 px-3 py-1 text-xs font-semibold text-sage-500 ring-1 ring-inset ring-sage-200">
									评分标准已确认
								</span>
								<button
									type="button"
									onClick={() => navigate(Number.isFinite(numericExamId) ? `/exams/${numericExamId}/roster` : '/exams')}
									className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800"
								>
									进入下一步：考试名单
								</button>
								<button
									type="button"
									onClick={() => void handleReopenRubric()}
									disabled={confirming || busy}
									className="rounded-full border border-ink-900/10 bg-white px-5 py-3 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
								>
									重新打开编辑
								</button>
							</>
						) : (
							<>
								<button
									type="button"
									onClick={() => void handleConfirmRubric(true)}
									disabled={confirming || busy || parsing || !exam || exam.questions.length === 0}
									className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
								>
									{confirming ? '正在确认...' : '确认并进入下一步'}
								</button>
								<button
									type="button"
									onClick={() => void handleConfirmRubric(false)}
									disabled={confirming || busy || parsing || !exam || exam.questions.length === 0}
									className="rounded-full border border-ink-900/10 bg-white px-5 py-3 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
								>
									仅确认，不跳转
								</button>
								{!exam || exam.questions.length === 0 ? (
									<span className="text-xs text-ink-700">提示：至少要有一道已解析的题目才能确认。</span>
								) : null}
							</>
						)}
					</div>
				</SectionCard>
			</div>
		</div>
	)
}

function QuestionEditorCard({
	question,
	onSaveQuestion,
	onSaveRubricItem,
	onDeleteRubricItem,
	onCreateRubricItem,
	disabled,
}: {
	question: Question
	onSaveQuestion: (question: Question, event: FormEvent<HTMLFormElement>) => Promise<void>
	onSaveRubricItem: (questionId: number, item: RubricItem, event: FormEvent<HTMLFormElement>) => Promise<void>
	onDeleteRubricItem: (questionId: number, itemId: number) => Promise<void>
	onCreateRubricItem: (questionId: number, event: FormEvent<HTMLFormElement>) => Promise<void>
	disabled: boolean
}) {
	return (
		<article className="rounded-3xl border border-ink-900/10 bg-white/90 p-4 shadow-soft">
			<form
				className="space-y-4"
				onSubmit={async (event) => {
					await onSaveQuestion(question, event)
				}}
			>
				<div className="flex flex-wrap items-center justify-between gap-3">
					<div>
						<h3 className="font-display text-3xl text-ink-950">题目 {question.question_no}</h3>
						<p className="mt-1 text-sm text-ink-700">编辑题目和评分项，后续评分证据会按这些规则追溯。</p>
					</div>
					<span className="rounded-full bg-slateBlue-50 px-3 py-1 text-xs font-semibold text-slateBlue-500 ring-1 ring-inset ring-slateBlue-100">
						{question.rubric_items.length} 个评分项
					</span>
				</div>

				<div className="grid gap-3 lg:grid-cols-12">
					<label className="block space-y-2 lg:col-span-2">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">题号</span>
						<input
							name="question_no"
							defaultValue={question.question_no}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2 lg:col-span-10">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">题目标题</span>
						<input
							name="title"
							defaultValue={question.title}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2 lg:col-span-2">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">满分</span>
						<input
							name="max_score"
							type="number"
							step="0.1"
							defaultValue={String(question.max_score)}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2 lg:col-span-2">
						<span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-700">排序</span>
						<input
							name="order_index"
							type="number"
							defaultValue={String(question.order_index)}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<div className="flex items-end justify-end lg:col-span-8">
						<button
							type="submit"
							disabled={disabled}
							className="rounded-full bg-ink-950 px-5 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
						>
							保存题目设置
						</button>
					</div>
				</div>
			</form>

			<div className="mt-5 space-y-3">
				{question.rubric_items.map((item) => (
					<form
						key={item.id}
						className="space-y-3 rounded-2xl border border-ink-900/10 bg-paper p-4"
						onSubmit={async (event) => {
							await onSaveRubricItem(question.id, item, event)
						}}
					>
						<label className="block space-y-2">
							<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">
								{item.max_score === 0 ? '补充评分说明 · 不计分' : '评分说明'}
							</span>
							<textarea
								name="description"
								defaultValue={item.description}
								rows={2}
								className="w-full resize-y rounded-2xl border border-ink-900/10 bg-white px-3 py-2 leading-6 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
							/>
						</label>
						<div className="grid gap-3 lg:grid-cols-12">
							<label className="block space-y-2 lg:col-span-2">
								<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">分值（可留空）</span>
								<input
									name="max_score"
									type="number"
									step="0.1"
									defaultValue={String(item.max_score)}
									className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
								/>
							</label>
							<label className="block space-y-2 lg:col-span-7">
								<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">关键词（逗号分隔）</span>
								<input
									name="keywords"
									defaultValue={item.keywords.join(', ')}
									className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
								/>
							</label>
							<label className="block space-y-2 lg:col-span-3">
								<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">排序</span>
								<input
									name="order_index"
									type="number"
									defaultValue={String(item.order_index)}
									className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
								/>
							</label>
						</div>
						<div className="flex flex-wrap justify-end gap-2">
							<button
								type="button"
								disabled={disabled}
								onClick={async () => {
									await onDeleteRubricItem(question.id, item.id)
								}}
								className="rounded-full border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
							>
								删除
							</button>
							<button
								type="submit"
								disabled={disabled}
								className="rounded-full bg-slateBlue-400 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slateBlue-500 disabled:cursor-not-allowed disabled:opacity-50"
							>
								保存评分项
							</button>
						</div>
					</form>
				))}
			</div>

			<form
				className="mt-5 space-y-3 rounded-2xl border border-dashed border-ink-900/15 bg-white p-4"
				onSubmit={async (event) => {
					await onCreateRubricItem(question.id, event)
				}}
			>
				<label className="block space-y-2">
					<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">新增评分项 / 补充评分说明</span>
					<textarea
						name="description"
						placeholder="例如：公式写出即可，不要求最终数值"
						rows={2}
						className="w-full resize-y rounded-2xl border border-ink-900/10 bg-white px-3 py-2 leading-6 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
					/>
				</label>
				<div className="grid gap-3 lg:grid-cols-12">
					<label className="block space-y-2 lg:col-span-2">
						<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">分值（可选）</span>
						<input
							name="max_score"
							type="number"
							step="0.1"
							placeholder="留空=不计分说明"
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2 lg:col-span-7">
						<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">关键词（逗号分隔）</span>
						<input
							name="keywords"
							placeholder="关键词1, 关键词2"
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
					<label className="block space-y-2 lg:col-span-3">
						<span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">排序</span>
						<input
							name="order_index"
							type="number"
							defaultValue={String(question.rubric_items.length)}
							className="w-full rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
						/>
					</label>
				</div>
				<div className="flex justify-end">
					<button
						type="submit"
						disabled={disabled}
						className="rounded-full bg-ink-950 px-5 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
					>
						添加评分项/说明
					</button>
				</div>
			</form>
		</article>
	)
}

function ParsingProgress() {
	return (
		<div className="rounded-2xl border border-slateBlue-200 bg-slateBlue-50 px-4 py-4 text-sm text-slateBlue-500">
			<div className="flex items-center gap-3 font-semibold">
				<span className="h-3 w-3 animate-pulse rounded-full bg-slateBlue-400" />
				正在调用视觉模型解析评分标准
			</div>
			<div className="mt-2 text-xs leading-5 text-ink-700">
				正在渲染 PDF 页面、识别题目和评分项。大文件或模型响应较慢时可能需要几十秒到数分钟，完成后页面会自动显示解析结果。
			</div>
		</div>
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

function parseKeywords(input: string): string[] {
	return input
		.split(',')
		.map((part) => part.trim())
		.filter(Boolean)
}