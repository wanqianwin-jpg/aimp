# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-03-01

### Changed
- **Refactored `hub_agent.py`** from a 1943-line monolith into a thin orchestrator (~520 lines).
  - `HubNegotiator` extracted to `lib/hub_negotiator.py`.
  - `RoomNegotiator` extracted to `lib/room_negotiator.py`.
  - `AIMPHubAgent` methods split into four mixin classes under a new `handlers/` package:
    - `handlers/session_handler.py` — `SessionMixin` (Phase 1 scheduling)
    - `handlers/room_handler.py` — `RoomMixin` (Phase 2 room lifecycle)
    - `handlers/command_handler.py` — `CommandMixin` (member command parsing)
    - `handlers/registration_handler.py` — `RegistrationMixin` (invite code registration)
  - `AIMPHubAgent` now inherits: `SessionMixin, RoomMixin, CommandMixin, RegistrationMixin, AIMPAgent`.
  - All external interfaces unchanged — no test structural changes required.
- **CI**: Added `pytest` step to `.github/workflows/ci.yml` (87 tests, runs after lint).

## [0.2.1] - 2026-02-28

### Changed
- Bump version to 0.2.1

## [0.2.0] - 2026-02-28

### Added
- **Phase 2: The Room**: Implemented asynchronous content negotiation with deadlines.
- **RoomNegotiator**: A new engine for managing document-based discussions.
- **Artifact System**: Standardized data structure for negotiating any content (text, budgets, etc.).
- **Veto Flow**: Support for human participants to confirm or reject finalized minutes.
- **BaseTransport**: Abstract base class for transport layer, allowing future expansion to Telegram/Slack.
- **EmailTransport**: Refactored email logic into a dedicated transport module.

### Fixed
- Fixed internal meeting auto-confirmation bug; now Hub properly requests votes from internal members.
- Improved error handling in email polling.
- Optimized LLM prompt templates for better consensus extraction.

### Changed
- Refactored `agent.py` and `hub_agent.py` to use the new `BaseTransport` interface.
- Updated `CLAUDE.md` and `README.md` with comprehensive Phase 2 documentation.
- Enhanced `.gitignore` to exclude temporary development files.
