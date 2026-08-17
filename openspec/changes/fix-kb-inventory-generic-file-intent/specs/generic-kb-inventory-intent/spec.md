## ADDED Requirements

### Requirement: Generic knowledge-base inventory wording
The system SHALL treat unqualified Chinese inventory nouns including `文件`, `资料`, and `文档` as an all-type knowledge-base inventory request when the query also contains a knowledge-base object and a quantity intent.

#### Scenario: Video-only knowledge base file count
- **WHEN** a caller asks "这个知识库包含多少个文件" for a knowledge base containing only video records
- **THEN** the deterministic answer SHALL report the all-type total and include the video type in its type breakdown

#### Scenario: Explicit Word document count
- **WHEN** a caller asks for the number of Word, doc, or docx documents in a knowledge base
- **THEN** the deterministic answer SHALL report only the document-format inventory bucket

#### Scenario: Content count question
- **WHEN** a caller asks "视频中有多少个零件"
- **THEN** the request SHALL not enter the deterministic inventory branch
