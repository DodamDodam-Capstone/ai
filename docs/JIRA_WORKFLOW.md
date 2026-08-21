# AI Jira·GitHub 업무 규칙

Jira 사이트는 `dodamdodam.atlassian.net`, 프로젝트 키는 `SCRUM`입니다.
AI 업무는 Jira와 GitHub 제목에 `[AI]`를 사용합니다.

## Epic과 Task

- 여러 저장소가 참여하는 Jira Epic: `[EPIC] <사용자 가치 또는 목표>`
- AI Jira Task: `[AI] <구현할 결과>`
- GitHub Issue: `SCRUM-<번호> [AI] <Jira Task와 같은 제목>`
- Jira Task 하나와 AI GitHub Issue 하나를 1:1로 연결합니다.

## GitHub Issue에서 Jira 자동 생성

`New issue`에서 `AI Task` 또는 `AI Bug` Form을 사용합니다. Issue가 열리면
`GitHub Issue to Jira` workflow가 다음을 자동 처리합니다.

1. Jira `SCRUM` 프로젝트에 `[AI]` Task 또는 Bug 생성
2. GitHub Issue 제목을 `SCRUM-<번호> [AI] ...`로 변경
3. Jira 링크 댓글과 `jira-linked` 레이블 추가
4. `#ai-actions`에 Source GitHub Issue와 Target Jira 업무 알림 전송

Epic 아래에 둘 업무는 Form의 `상위 Jira 키`에 `SCRUM-<번호>`를 입력합니다.
동기화가 실패하면 Actions의 `GitHub Issue to Jira`를 `Run workflow`로 열어 Issue
번호를 넣어 재시도합니다. 이미 Jira 키가 있거나 `jira-skip` 레이블이 있는
Issue는 생성하지 않습니다.

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
