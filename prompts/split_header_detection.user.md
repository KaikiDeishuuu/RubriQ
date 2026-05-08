Analyze only the top header region of page ${page_no}.

Extract:
- student_name
- student_id
- quiz_title
- page_number
- confidence for each field from 0 to 1
- is_first_page_confidence from 0 to 1
- overall_confidence from 0 to 1

Rules:
- Do not guess student_name or student_id from body text, footers, page numbers, dates, question numbers, scores, or decorative labels.
- Prefer null with low confidence when a field is unclear or only weakly implied.
- Treat OCR reference text only as supporting evidence; if it conflicts with the image, trust the image.
- Set is_first_page_confidence high only when the header clearly indicates a new student's first page, such as explicit page 1/reset evidence or a fresh student information block.
- If the page looks like a continuation page for the same student, keep is_first_page_confidence low even if a footer says page 1/x.

${ocr_reference_text}

Return JSON only.
