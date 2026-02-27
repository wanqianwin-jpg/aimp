# Changelog

All notable changes to this project will be documented in this file.

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
