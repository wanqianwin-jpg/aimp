# Documentation Maintenance Checklist

Use this checklist when releasing new versions or updating documentation.

## 1. Version Consistency
- [ ] Update version number in `agent.py` / `__init__.py`.
- [ ] Update version mentions in `README.md` and `README_zh.md`.
- [ ] Update version in `SKILL.md`.

## 2. Content Synchronization
- [ ] **README vs README_zh**: Ensure Chinese docs reflect the latest English changes.
- [ ] **Installation Instructions**: Verify commands in `README.md` match `SKILL.md`.
- [ ] **Feature List**: If a new feature (like Hub Mode) is added, ensure it's in:
    - [ ] `README.md`
    - [ ] `CLAUDE.md`
    - [ ] `openclaw-skill/SKILL.md`

## 3. "Fork" & Repository Checks
- [ ] **Clone URLs**: Ensure all `git clone` commands point to `wanqianwin-jpg/aimp` (GitHub) or `wanqianwin/aimp` (Gitee).
- [ ] **Branch References**: Ensure links point to `main` (not `master` or old dev branches).
- [ ] **No Fork Instructions**: Ensure users aren't told to fork unless they are contributing code.

## 4. Quality & Tone
- [ ] **Tone Check**: Read through changes. Is it friendly?
- [ ] **Link Check**: Click all new links to ensure they work.
- [ ] **Typos**: Run a quick spell check.

## 5. Technical Verification
- [ ] **Commands**: Copy-paste installation commands into a clean terminal to verify they run.
- [ ] **Config Examples**: Ensure `references/config-example.yaml` matches the current code structure.
