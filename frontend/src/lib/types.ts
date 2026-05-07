export type SubmissionStatus = 'uploaded' | 'processing' | 'graded' | 'needs_review' | 'failed'
export type ConfidenceLevel = 'high' | 'medium' | 'low'

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
  created_at: string
  updated_at: string
  files: ExamFile[]
  questions: Question[]
}

export interface SubmissionSummary {
  id: number
  exam_id: number
  student_name: string | null
  student_id: string | null
  original_pdf_path: string
  status: SubmissionStatus
  total_score: string | number
  raw_extraction_response: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface SubmissionPage {
  id: number
  submission_id: number
  page_no: number
  image_path: string
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

export interface ExamResultRow {
  submission_id: number
  student_name: string | null
  student_id: string | null
  status: SubmissionStatus
  total_score: number
  needs_human_review: boolean
  question_scores: Record<string, number>
  created_at: string
  updated_at: string
}

export interface ExamResultsResponse {
  exam: ExamDetail
  questions: Question[]
  rows: ExamResultRow[]
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
}
