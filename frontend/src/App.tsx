import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { BatchResultsPage } from './pages/BatchResultsPage'
import { CreateExamPage } from './pages/CreateExamPage'
import { ExamListPage } from './pages/ExamListPage'
import { RubricReviewPage } from './pages/RubricReviewPage'
import { SubmissionReviewPage } from './pages/SubmissionReviewPage'
import { SubmissionUploadPage } from './pages/SubmissionUploadPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Navigate to="/exams" replace />} />
        <Route path="/exams" element={<ExamListPage />} />
        <Route path="/exams/new" element={<CreateExamPage />} />
        <Route path="/exams/:examId/rubric" element={<RubricReviewPage />} />
        <Route path="/exams/:examId/submissions" element={<SubmissionUploadPage />} />
        <Route path="/exams/:examId/results" element={<BatchResultsPage />} />
        <Route path="/exams/:examId/review/:submissionId" element={<SubmissionReviewPage />} />
        <Route path="*" element={<Navigate to="/exams" replace />} />
      </Route>
    </Routes>
  )
}
