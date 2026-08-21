# DodamDodam AI

AI service for the DodamDodam capstone project.

CI automatically becomes active when `pyproject.toml`, `uv.lock`, or
`requirements.txt` and `.python-version` are added. The project owns its Python
version; CI does not hardcode one in advance.

Organization workflow documentation is maintained in the
[integration repository](https://github.com/DodamDodam-Capstone/integration/blob/main/docs/GITHUB_WORKFLOW.md).

Changes are promoted from `development` to `main` through a protected,
human-approved squash pull request. A successful `main` promotion then updates
the immutable AI SHA in the integration repository through a bot PR.
