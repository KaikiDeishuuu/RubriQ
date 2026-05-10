import type {
  Answer,
  AnswerRubricResult,
  BatchCandidateUpdatePayload,
  BatchConfirmResponse,
  BatchStartGradingResponse,
  BatchUploadMode,
  BatchUploadResponse,
  ConfidenceLevel,
  DeductionSummaryUpdatePayload,
  ExamCreatePayload,
  ExamDetail,
  ExamListItem,
  ExamResultsResponse,
  PageUploadResponse,
  ProcessResponse,
  Question,
  QuestionUpdatePayload,
  RosterDetail,
  RosterReplaceRequest,
  RubricItemCreatePayload,
  RubricItemUpdatePayload,
  SubmissionBatchDetail,
  SubmissionDetail,
  SubmissionOverridePayload,
  SubmissionSummary,
  SubmissionUploadResponse,
  TeacherFinalizedUpdatePayload,
} from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const TOKEN_STORAGE_KEY = 'quizocr_admin_token'

export class AuthRequiredError extends Error {
  constructor(message = '未登录或登录已失效') {
    super(message)
    this.name = 'AuthRequiredError'
  }
}

let _onAuthExpired: (() => void) | null = null

export function setAdminToken(token: string | null): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {}
  try {
    if (token) {
      window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
    } else {
      window.sessionStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch {}
}

export function getAdminToken(): string | null {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {}
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setAuthExpiredHandler(handler: (() => void) | null): void {
  _onAuthExpired = handler
}

function applyAuthHeader(init: RequestInit): RequestInit {
  const token = getAdminToken()
  if (!token) {
    return init
  }
  const headers = new Headers(init.headers ?? {})
  if (!headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return { ...init, headers }
}

async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(input, applyAuthHeader(init))
  if (response.status === 401 || response.status === 403) {
    if (_onAuthExpired) {
      _onAuthExpired()
    }
    throw new AuthRequiredError()
  }
  return response
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await authedFetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(errorText || response.statusText)
  }
  if (response.status === 204) {
    return undefined as T
  }
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    return (await response.json()) as T
  }
  return (await response.text()) as T
}

async function fetchBlob(path: string): Promise<Blob> {
  const response = await authedFetch(`${API_BASE_URL}${path}`)
  if (!response.ok) {
    throw new Error(await response.text())
  }
  return response.blob()
}

export async function fetchStorageBlob(storagePath: string): Promise<Blob> {
  return fetchBlob(`/storage/${encodePath(storagePath)}`)
}

export async function checkAuthToken(): Promise<{ ok: boolean; auth_required: boolean }> {
  return request<{ ok: boolean; auth_required: boolean }>('/auth/check')
}

export async function getAuthStatus(): Promise<{ auth_required: boolean }> {
  const response = await fetch(`${API_BASE_URL}/auth/status`, applyAuthHeader({}))
  if (!response.ok) {
    throw new Error('无法读取认证状态')
  }
  return response.json()
}

function encodePath(storagePath: string): string {
  return storagePath
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/')
}

/**
 * @deprecated Browsers cannot send Authorization headers with `<img src>`.
 * Use {@link fetchStorageBlob} + URL.createObjectURL or the AuthenticatedImage component.
 */
export function buildStorageUrl(storagePath: string): string {
  return `${API_BASE_URL}/storage/${encodePath(storagePath)}`
}

export async function listExams(): Promise<ExamListItem[]> {
  return request<ExamListItem[]>('/exams')
}

export async function createExam(payload: ExamCreatePayload): Promise<ExamDetail> {
  return request<ExamDetail>('/exams', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function getExam(examId: number): Promise<ExamDetail> {
  return request<ExamDetail>(`/exams/${examId}`)
}

export async function uploadRubricPdf(examId: number, file: File): Promise<PageUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  return request<PageUploadResponse>(`/exams/${examId}/rubric/upload`, {
    method: 'POST',
    body: formData,
  })
}

export async function parseRubricPdf(examId: number, examFileId?: number): Promise<ExamDetail> {
  const searchParams = new URLSearchParams()
  if (examFileId !== undefined) {
    searchParams.set('exam_file_id', String(examFileId))
  }
  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : ''
  return request<ExamDetail>(`/exams/${examId}/rubric/parse${suffix}`, {
    method: 'POST',
  })
}

export async function confirmRubric(examId: number): Promise<ExamDetail> {
  return request<ExamDetail>(`/exams/${examId}/rubric/confirm`, { method: 'POST' })
}

export async function reopenRubric(examId: number): Promise<ExamDetail> {
  return request<ExamDetail>(`/exams/${examId}/rubric/reopen`, { method: 'POST' })
}

export async function getQuestions(examId: number): Promise<Question[]> {
  return request<Question[]>(`/exams/${examId}/questions`)
}

export async function updateQuestion(questionId: number, payload: QuestionUpdatePayload): Promise<Question> {
  return request<Question>(`/exams/questions/${questionId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function createRubricItem(questionId: number, payload: RubricItemCreatePayload): Promise<Question> {
  return request<Question>(`/exams/questions/${questionId}/rubric-items`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function updateRubricItem(itemId: number, payload: RubricItemUpdatePayload): Promise<Question> {
  return request<Question>(`/exams/rubric-items/${itemId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteRubricItem(itemId: number): Promise<void> {
  await request<void>(`/exams/rubric-items/${itemId}`, {
    method: 'DELETE',
  })
}

export async function uploadBatch(
  examId: number,
  mode: BatchUploadMode,
  file: File,
  pagesPerSubmission?: number,
): Promise<BatchUploadResponse> {
  const formData = new FormData()
  formData.append('mode', mode)
  formData.append('file', file)
  if (pagesPerSubmission !== undefined) {
    formData.append('pages_per_submission', String(pagesPerSubmission))
  }
  return request<BatchUploadResponse>(`/exams/${examId}/batches/upload`, {
    method: 'POST',
    body: formData,
  })
}

export async function listBatches(examId: number): Promise<SubmissionBatchDetail[]> {
  return request<SubmissionBatchDetail[]>(`/exams/${examId}/batches`)
}

export async function getBatch(examId: number, batchId: number): Promise<SubmissionBatchDetail> {
  return request<SubmissionBatchDetail>(`/exams/${examId}/batches/${batchId}`)
}

export async function updateBatchCandidates(
  examId: number,
  batchId: number,
  candidates: BatchCandidateUpdatePayload[],
): Promise<SubmissionBatchDetail> {
  return request<SubmissionBatchDetail>(`/exams/${examId}/batches/${batchId}/candidates`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ candidates }),
  })
}

export async function confirmBatchSplit(examId: number, batchId: number): Promise<BatchConfirmResponse> {
  return request<BatchConfirmResponse>(`/exams/${examId}/batches/${batchId}/confirm-split`, {
    method: 'POST',
  })
}

export async function startBatchGrading(examId: number, batchId: number): Promise<BatchStartGradingResponse> {
  return request<BatchStartGradingResponse>(`/exams/${examId}/batches/${batchId}/start-grading`, {
    method: 'POST',
  })
}

export async function uploadSubmissions(
  examId: number,
  files: File[],
  studentName?: string,
  studentId?: string,
): Promise<SubmissionUploadResponse> {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  if (studentName) {
    formData.append('student_name', studentName)
  }
  if (studentId) {
    formData.append('student_id', studentId)
  }
  return request<SubmissionUploadResponse>(`/exams/${examId}/submissions/upload`, {
    method: 'POST',
    body: formData,
  })
}

export async function processSubmission(submissionId: number): Promise<ProcessResponse> {
  return request<ProcessResponse>(`/submissions/${submissionId}/process`, {
    method: 'POST',
  })
}

export async function getSubmission(submissionId: number): Promise<SubmissionDetail> {
  return request<SubmissionDetail>(`/submissions/${submissionId}`)
}

export async function overrideAnswer(answerId: number, payload: SubmissionOverridePayload): Promise<Answer> {
  return request<Answer>(`/answers/${answerId}/override`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function getResults(examId: number): Promise<ExamResultsResponse> {
  return request<ExamResultsResponse>(`/exams/${examId}/results`)
}

export async function exportResultsCsv(examId: number): Promise<Blob> {
  return fetchBlob(`/exams/${examId}/export.csv`)
}

export async function exportResultsXlsx(examId: number): Promise<Blob> {
  return fetchBlob(`/exams/${examId}/export.xlsx`)
}

export async function exportResultsPdf(examId: number): Promise<Blob> {
  return fetchBlob(`/exams/${examId}/export.pdf`)
}

export async function exportSubmissionPdf(submissionId: number): Promise<Blob> {
  return fetchBlob(`/submissions/${submissionId}/export.pdf`)
}

export async function exportExamSubmissionsZip(examId: number): Promise<Blob> {
  return fetchBlob(`/exams/${examId}/export-submissions.zip`)
}

export async function exportDeductionsCsv(examId: number): Promise<Blob> {
  return fetchBlob(`/exams/${examId}/export-deductions.csv`)
}

export async function exportDeductionsXlsx(examId: number): Promise<Blob> {
  return fetchBlob(`/exams/${examId}/export-deductions.xlsx`)
}

export async function updateDeductionSummary(
  submissionId: number,
  payload: DeductionSummaryUpdatePayload,
): Promise<SubmissionDetail> {
  return request<SubmissionDetail>(`/submissions/${submissionId}/deduction-summary`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function updateSubmissionTeacherFinalized(
  submissionId: number,
  payload: TeacherFinalizedUpdatePayload,
): Promise<SubmissionDetail> {
  return request<SubmissionDetail>(`/submissions/${submissionId}/teacher-finalized`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function deleteExam(examId: number): Promise<void> {
  await request<void>(`/exams/${examId}`, { method: 'DELETE' })
}

export async function deleteRubricFile(examId: number, fileId: number): Promise<void> {
  await request<void>(`/exams/${examId}/rubric/files/${fileId}`, { method: 'DELETE' })
}

export async function deleteSubmission(submissionId: number): Promise<void> {
  await request<void>(`/submissions/${submissionId}`, { method: 'DELETE' })
}

export async function getRoster(examId: number): Promise<RosterDetail> {
  return request<RosterDetail>(`/exams/${examId}/roster`)
}

export async function uploadRoster(
  examId: number,
  file: File,
  sourceKind?: 'pdf' | 'csv' | 'xlsx',
): Promise<ExamDetail> {
  const formData = new FormData()
  formData.append('file', file)
  if (sourceKind) {
    formData.append('source_kind', sourceKind)
  }
  return request<ExamDetail>(`/exams/${examId}/roster/upload`, {
    method: 'POST',
    body: formData,
  })
}

export async function parseRoster(examId: number, examFileId?: number): Promise<ExamDetail> {
  const searchParams = new URLSearchParams()
  if (examFileId !== undefined) {
    searchParams.set('exam_file_id', String(examFileId))
  }
  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : ''
  return request<ExamDetail>(`/exams/${examId}/roster/parse${suffix}`, {
    method: 'POST',
  })
}

export async function putRoster(examId: number, payload: RosterReplaceRequest): Promise<ExamDetail> {
  return request<ExamDetail>(`/exams/${examId}/roster`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

export async function confirmRoster(examId: number): Promise<ExamDetail> {
  return request<ExamDetail>(`/exams/${examId}/roster/confirm`, { method: 'POST' })
}

export async function deleteRoster(examId: number): Promise<ExamDetail> {
  return request<ExamDetail>(`/exams/${examId}/roster`, { method: 'DELETE' })
}

export async function downloadBlob(blob: Blob, filename: string): Promise<void> {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}
