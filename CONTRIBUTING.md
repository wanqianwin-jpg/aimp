# Contributing to AIMP

First off, thank you for considering contributing to AIMP! It's people like you that make AIMP such a great tool.

## Code of Conduct

This project and everyone participating in it is governed by the [AIMP Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

This section guides you through submitting a bug report for AIMP. Following these guidelines helps maintainers and the community understand your report, reproduce the behavior, and find related reports.

- **Use a clear and descriptive title** for the issue to identify the problem.
- **Describe the exact steps which reproduce the problem** in as many details as possible.
- **Provide specific examples to demonstrate the steps**. Include copy/pasteable snippets, which you use in those examples.

### Suggesting Enhancements

This section guides you through submitting an enhancement suggestion for AIMP, including completely new features and minor improvements to existing functionality.

- **Use a clear and descriptive title** for the issue to identify the suggestion.
- **Provide a step-by-step description of the suggested enhancement** in as many details as possible.
- **Explain why this enhancement would be useful** to most AIMP users.

### Pull Requests

The process described here has several goals:

- Maintain AIMP's quality
- Fix problems that are important to users
- Engage the community in working toward the best possible AIMP

Please follow these steps to have your contribution considered by the maintainers:

1.  Follow all instructions in the template
2.  Follow the style guides
3.  After you submit your pull request, verify that all status checks are passing

## Styleguides

### Python Styleguide

- Use [Black](https://github.com/psf/black) for code formatting.
- Use [Ruff](https://github.com/astral-sh/ruff) for linting.
- Write docstrings for all public modules, functions, classes, and methods.

### Git Commit Messages

- Use the present tense ("Add feature" not "Added feature")
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit the first line to 72 characters or less
- Reference issues and pull requests liberally after the first line

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
