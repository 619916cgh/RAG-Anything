## ADDED Requirements

### Requirement: Upload Worker termination reaps descendant processes
The system SHALL start each upload Worker in an independent OS process group or session and SHALL use a common termination helper for cancellation, watchdog timeout, and KB deletion. Cleanup SHALL wait for the group root to exit before removing task residue.

#### Scenario: Cancelled Worker owns a parser child
- **WHEN** a processing upload is cancelled while a parser child is running
- **THEN** the Worker and its descendant processes are terminated before task cleanup proceeds

#### Scenario: Worker survives the termination deadline
- **WHEN** the Worker group does not exit within the configured termination window
- **THEN** the task remains in its durable cancelling state for later recovery rather than reporting deletion complete
