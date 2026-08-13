## ADDED Requirements

### Requirement: Public demo citations use controlled previews
The public demo interface SHALL render answer citations and media only from the public demo stream payload. It MUST NOT offer local-document opening, ordinary document downloads, or authenticated media URLs.

#### Scenario: Demo answer includes citations
- **WHEN** a public demo answer contains citations or controlled media metadata
- **THEN** the interface displays the safe document name and requests media through the share-authenticated preview API

#### Scenario: Demo answer has no citations
- **WHEN** a public demo answer contains no citations
- **THEN** the interface renders the answer without an empty citation panel
