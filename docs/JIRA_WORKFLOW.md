# AI Jira·GitHub 업무 규칙

Jira 사이트는 `dodamdodam.atlassian.net`, 프로젝트 키는 `SCRUM`입니다.
AI 업무는 Jira와 GitHub 제목에 `[AI]`를 사용합니다.

## Epic과 Task

- 여러 저장소가 참여하는 Jira Epic: `[EPIC] <사용자 가치 또는 목표>`
- AI Jira Task: `[AI] <구현할 결과>`
- GitHub Issue: `SCRUM-<번호> [AI] <Jira Task와 같은 제목>`
- Jira Task 하나와 AI GitHub Issue 하나를 1:1로 연결합니다.

예시:

```text
Jira Epic  SCRUM-1 [EPIC] GitHub·Jira 협업 흐름 검증
Jira Task  SCRUM-4 [AI] GitHub·Jira 연동 및 문서 검증
GitHub     ai#8 SCRUM-4 [AI] GitHub·Jira 연동 및 문서 검증
```

## 개발 식별자

GitHub for Atlassian이 개발 정보를 Jira에 연결할 수 있도록 모든 식별자에
정확한 Jira 키를 포함합니다.

```text
branch: feature/SCRUM-4-jira-workflow-docs
commit: 📝 docs: SCRUM-4 [AI] Jira 협업 규칙 추가
PR:     📝 docs: SCRUM-4 [AI] Jira 협업 규칙 추가
```

PR 본문에는 다음 항목을 작성합니다.

```text
Jira: https://dodamdodam.atlassian.net/browse/SCRUM-4
Resolves #8
```

일반 작업 PR의 대상은 `development`입니다. `development` 반영과 검증이 끝난
뒤 sprint 승격 PR로 `main`에 반영합니다.

## 완료 조건

- Jira Task와 GitHub Issue가 서로 연결되어 있습니다.
- branch, commit, PR 제목에 같은 Jira 키가 있습니다.
- Gitmoji PR 제목 검사와 `ai-quality`가 통과합니다.
- 리뷰 승인과 모든 검토 대화 해결을 완료합니다.
- PR merge 후 GitHub Issue와 Jira Task가 완료되고 Slack 알림이 성공합니다.

전체 Epic·하위 이슈·Team Board 운영 규칙은
[integration 문서](https://github.com/DodamDodam-Capstone/integration/blob/main/docs/JIRA_GITHUB_INTEGRATION.md)를
기준으로 합니다.
