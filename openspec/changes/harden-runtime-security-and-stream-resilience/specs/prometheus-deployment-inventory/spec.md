## ADDED Requirements

### Requirement: Monitoring deployment defines scrape ownership
The deployment resources SHALL identify the application, PostgreSQL, Redis, node, backup, and TLS metric sources required by alert rules, and SHALL validate rule syntax and scrape configuration without embedding operational credentials.

#### Scenario: Staging monitoring validation
- **WHEN** the monitoring deployment inventory is validated in staging
- **THEN** every required target has an explicit scrape owner and expected job label before alert rules are accepted
