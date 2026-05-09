export type SubmissionStatus = 'uploaded' | 'processing' | 'rendering' | 'extracting' | 'grading' | 'graded' | 'needs_review' | 'failed'
export type ConfidenceLevel = 'high' | 'medium' | 'low'
export type BatchUploadMode = 'zip' | 'combined_fixed' | 'combined_auto'
export type BatchStatus = 'uploaded' | 'splitting' | 'needs_split_review' | 'split_ready' | 'materializing' | 'ready_for_grading' | 'grading' | 'completed' | 'completed_with_errors' | 'failed'

export interface ExamListItem {
  id: number
  title: string
  description: string | null
  total_score: string | number
  needs_rubric_review: boolean
  created_at: string
  updated_at: string
  question_count: number
  submission_count: number
}

export interface ExamFile {
  id: number
  exam_id: number
  file_type: string
  original_filename: string
  storage_path: string
  page_count: number | null
  parsed_json: Record<string, unknown> | null
  raw_ai_response: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface RubricItem {
  id: number
  question_id: number
  description: string
  max_score: string | number
  keywords: string[]
  order_index: number
  created_at: string
  updated_at: string
}

export interface Question {
  id: number
  exam_id: number
  question_no: string
  title: string
  max_score: string | number
  order_index: number
  rubric_items: RubricItem[]
  created_at: string
  updated_at: string
}

export interface ExamDetail {
  id: number
  title: string
  description: string | null
  total_score: string | number
  needs_rubric_review: boolean
  roster_status: RosterStatus
  roster_error_message: string | null
  created_at: string
  updated_at: string
  files: ExamFile[]
  questions: Question[]
  roster_entries: RosterEntry[]
}

export type RosterStatus = 'not_uploaded' | 'parsing' | 'needs_review' | 'confirmed'

export interface RosterEntry {
  id: number
  exam_id: number
  order_index: number
  student_name: string | null
  student_id: string | null
  source: string
  created_at: string
  updated_at: string
}

export interface RosterDetail {
  exam_id: number
  roster_status: RosterStatus
  roster_error_message: string | null
  entries: RosterEntry[]
}

export interface RosterEntryInput {
  student_name?: string | null
  student_id?: string | null
}

export interface RosterReplaceRequest {
  entries: RosterEntryInput[]
  source?: string
}

export interface SubmissionSummary {
  id: number
  exam_id: number
  batch_id: number | null
  batch_candidate_id: number | null
  student_name: string | null
  student_id: string | null
  original_pdf_path: string
  status: SubmissionStatus
  total_score: string | number
  raw_extraction_response: string | null
  error_message: string | null
  source_mode: string | null
  split_confidence: number | null
  split_confirmed: boolean
  deduction_summary: string | null
  deduction_summary_edited: boolean
  teacher_finalized: boolean
  created_at: string
  updated_at: string
}

export interface SubmissionPage {
  id: number
  submission_id: number
  page_no: number
  image_path: string
  page_hash: string | null
  extracted_text: string | null
  raw_ai_response: string | null
  created_at: string
  updated_at: string
}

export interface AnswerRubricResult {
  id: number
  answer_id: number
  rubric_item_id: number
  awarded_score: string | number
  evidence: string
  reason: string
  created_at: string
  updated_at: string
}

export interface Answer {
  id: number
  submission_id: number
  question_id: number
  source_page: number | null
  extracted_answer: string
  score: string | number
  max_score: string | number
  confidence: ConfidenceLevel
  ai_comment: string | null
  missing_points: string[]
  needs_human_review: boolean
  teacher_override_score: string | number | null
  teacher_comment: string | null
  raw_ai_response: string | null
  fast_score: string | number | null
  fast_confidence: ConfidenceLevel | null
  fast_ai_comment: string | null
  fast_missing_points: string[] | null
  fast_raw_ai_response: string | null
  review_score: string | number | null
  review_confidence: ConfidenceLevel | null
  review_ai_comment: string | null
  review_missing_points: string[] | null
  review_raw_ai_response: string | null
  review_triggers: string[]
  review_decision: string
  review_model: string | null
  question: Question
  rubric_results: AnswerRubricResult[]
  created_at: string
  updated_at: string
  effective_score: number
}

export interface SubmissionDetail extends SubmissionSummary {
  exam: ExamDetail
  pages: SubmissionPage[]
  answers: Answer[]
}

export interface BatchPage {
  id: number
  batch_id: number
  page_no: number
  image_path: string
  page_hash: string
  extracted_text: string | null
  header_extraction_json: Record<string, unknown> | null
  raw_ai_response: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface BatchSplitCandidate {
  id: number
  batch_id: number
  candidate_index: number
  start_page: number
  end_page: number
  student_name: string | null
  student_id: string | null
  split_confidence: number
  needs_review: boolean
  review_notes: string | null
  confirmed: boolean
  excluded: boolean
  source_filename: string | null
  source_storage_path: string | null
  error_message: string | null
  submission_id: number | null
  roster_entry_id: number | null
  created_at: string
  updated_at: string
}

export interface SubmissionBatchDetail {
  id: number
  exam_id: number
  mode: BatchUploadMode
  status: BatchStatus
  source_filename: string
  source_storage_path: string
  pages_per_submission: number | null
  total_pages: number | null
  split_version: number
  raw_split_extraction_response: Record<string, unknown> | null
  error_message: string | null
  ai_review_status: string
  ai_review_error_message: string | null
  created_at: string
  updated_at: string
  pages: BatchPage[]
  candidates: BatchSplitCandidate[]
  submissions: SubmissionSummary[]
}

export interface BatchUploadResponse {
  batch: SubmissionBatchDetail
}

export interface BatchCandidateUpdatePayload {
  id?: number | null
  candidate_index?: number | null
  start_page: number
  end_page: number
  student_name?: string | null
  student_id?: string | null
  review_notes?: string | null
  confirmed: boolean
  excluded?: boolean
  roster_entry_id?: number | null
}

export interface BatchConfirmResponse {
  batch: SubmissionBatchDetail
  created_submission_count: number
  failed_candidate_count: number
}

export interface BatchStartGradingResponse {
  batch_id: number
  queued_submission_count: number
  status: BatchStatus
}

export interface ExamResultRow {
  submission_id: number
  student_name: string | null
  student_id: string | null
  status: SubmissionStatus
  total_score: number
  needs_human_review: boolean
  ai_reviewed_answer_count: number
  pending_review_answer_count: number
  source_mode?: string | null
  split_confidence?: number | null
  split_confirmed?: boolean
  teacher_finalized: boolean
  question_scores: Record<string, number>
  created_at: string
  updated_at: string
}

export interface ExamResultsResponse {
  exam: ExamDetail
  questions: Question[]
  rows: ExamResultRow[]
  ai_review_active: boolean
  ai_review_statuses: string[]
}

export interface PageUploadResponse {
  message: string
  exam_file: ExamFile | null
}

export interface SubmissionUploadResponse {
  submissions: SubmissionSummary[]
}

export interface ProcessResponse {
  submission_id: number
  status: SubmissionStatus
}

export interface ExamCreatePayload {
  title: string
  description?: string | null
}

export interface ExamUpdatePayload {
  title?: string | null
  description?: string | null
}

export interface QuestionUpdatePayload {
  question_no?: string | null
  title?: string | null
  max_score?: number | null
  order_index?: number | null
}

export interface RubricItemCreatePayload {
  description: string
  max_score: number
  keywords: string[]
  order_index: number
}

export interface RubricItemUpdatePayload {
  description?: string | null
  max_score?: number | null
  keywords?: string[] | null
  order_index?: number | null
}

export interface SubmissionOverridePayload {
  teacher_override_score?: number | null
  teacher_comment?: string | null
  reviewed?: boolean | null
}

export interface DeductionSummaryUpdatePayload {
  summary?: string | null
  reset?: boolean
}

export interface TeacherFinalizedUpdatePayload {
  teacher_finalized: boolean
}
