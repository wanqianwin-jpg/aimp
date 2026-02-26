# Contributing to AIMP

First off, thank you for considering contributing to AIMP! It's people like you that make AIMP such a great tool.

## Code of Conduct

This project and everyone participating in it is governed by the [AIMP Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

Found a bug? No worries, we're here to help!

- **Give it a clear title** so we know what's up.
- **Tell us how to reproduce it** step-by-step. The more details, the better!
- **Show us what happened**. Screenshots or code snippets are super helpful.

### Suggesting Enhancements

Have a cool idea? We'd love to hear it!

- **Title it clearly**.
- **Describe your idea** in detail.
- **Tell us why it's awesome** and how it helps everyone.

### Pull Requests

Ready to share your code? Awesome!

1.  **Fork the repo** and create your branch from `main`.
2.  **Make your changes** (and don't forget the tests!).
3.  **Submit a Pull Request** to our `main` branch.

## Styleguides

### Python Styleguide

- We love **[Black](https://github.com/psf/black)** for formatting.
- We use **[Ruff](https://github.com/astral-sh/ruff)** to keep things tidy.
- Please add docstrings so others know what your code does!

### Git Commit Messages

- Keep it present tense ("Add feature" not "Added feature").
- Be concise (under 72 chars for the first line).

## Setting Up Your Development Environment

1.  Clone the repository
    -   **GitHub**: `git clone https://github.com/wanqianwin-jpg/aimp.git`
    -   **Gitee**: `git clone https://gitee.com/wanqianwin/aimp.git`
    ```bash
    cd aimp
    ```

2.  Create a virtual environment
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  Install dependencies
    ```bash
    pip install -r requirements.txt
    ```

4.  Run tests (if available)
    ```bash
    pytest
    ```

Thank you for your contribution!
