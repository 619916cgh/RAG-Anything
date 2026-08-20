## ADDED Requirements

### Requirement: Container liveness is independent of dependency readiness
The application container healthcheck SHALL use the dependency-independent live endpoint. Readiness SHALL continue to report dependency availability, and the Compose application service SHALL not publish its API port to host interfaces by default.

#### Scenario: PostgreSQL is temporarily unavailable
- **WHEN** PostgreSQL becomes temporarily unavailable while the application process remains alive
- **THEN** liveness remains successful, readiness is unsuccessful, and Docker does not restart the application solely for that dependency outage
