# AIMP Documentation Style Guide

This guide helps maintain consistency and quality across all AIMP documentation.

## 1. Tone and Voice
- **Friendly & Welcoming**: Use warm, conversational language.
  - *Bad*: "User must configure the file."
  - *Good*: "You'll need to set up your config file."
- **Inclusive**: Use "We" and "Let's".
- **Clear & Concise**: Avoid jargon where simple words work.

## 2. Language & Translation
- **Primary Language**: English (International).
- **Secondary Language**: Chinese (Simplified).
- **Bilingual Files**: For code comments, put English first, then Chinese.
  ```python
  def connect(self):
      """
      Connect to the server.
      连接到服务器。
      """
      pass
  ```
- **Separate Files**: For large docs (like README), use `FILENAME.md` (English) and `FILENAME_zh.md` (Chinese).

## 3. Formatting
- **Headers**: Use Title Case.
- **Code Blocks**: Always specify the language (e.g., ```python, ```bash).
- **Links**: Use relative links for internal files.

## 4. Key Terminology
- **AIMP**: Always uppercase.
- **Agent**: Capitalized when referring to the AI entity.
- **Hub Mode**: Capitalized.
- **Standalone Mode**: Capitalized.
- **OpenClaw**: Correct spelling (not Openclaw).

## 5. Branching Strategy
- **Default Branch**: `main`.
- **Development**: Contributors should fork and PR to `main`.
- **Avoid**: Do not instruct users to clone a specific fork unless necessary. Always point to the official repo.
