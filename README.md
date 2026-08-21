# DodamDodam AI

DodamDodam 캡스톤 프로젝트의 AI 서비스 저장소입니다.

`pyproject.toml`, `uv.lock` 또는 `requirements.txt`와 `.python-version`이
추가되면 CI가 실제 프로젝트 검사를 자동으로 실행합니다. Python 버전은
프로젝트가 직접 관리하며 CI에는 특정 버전을 미리 고정하지 않았습니다.

Organization 전체 협업 흐름은
[integration 저장소 문서](https://github.com/DodamDodam-Capstone/integration/blob/main/docs/GITHUB_WORKFLOW.md)에서
관리합니다.

변경 사항은 보호된 `development` → `main` PR에서 사람의 승인을 받은 후
squash merge합니다. `main` 반영이 완료되면 Bot PR이 integration 저장소의
AI commit SHA를 자동으로 갱신합니다.
