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
동기화가 실패하면 Actions의 `GitHub Issue to Jira`에서 `main`을 선택하고 Issue
번호를 넣어 재시도합니다. `jira-skip` 레이블이 있는 Issue는 생성하지 않습니다.
제목에 Jira 키가 있더라도 이 GitHub Issue의 고유 Jira 레이블과 일치할 때만 기존
업무를 재사용합니다.

저장소가 public이므로 자동 생성은 GitHub의 `OWNER`, `MEMBER`, `COLLABORATOR`가
연 Issue에만 실행됩니다. 외부 사용자가 등록한 Issue는 팀원이 내용을 검토한 뒤
`Run workflow`로 승인·동기화합니다. 재실행해도 Jira 업무와 링크 댓글은 중복
생성되지 않으며 Slack 성공 알림 완료는 `jira-notified` 레이블로 표시됩니다.
secret을 사용하는 중앙 helper는 CI를 통과한 integration commit 전체 SHA로
고정합니다. Task·Bug 유형 레이블이 충돌하면 잘못된 유형을 만들지 않고 실패
알림을 보냅니다.

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
- Jira 업무는 삭제하지 않고 `완료` 상태로 전환하며 Team Board의
  `Show completed tickets`에서 완료 기록을 확인할 수 있습니다.

## 장기 브랜치 병합 원칙

- `feature/*`, `fix/*` → `development`: squash merge로 작업 단위를 정리합니다.
- `development` → `main`: merge commit으로 두 장기 브랜치의 계보를 보존합니다.
- 두 보호 브랜치에는 직접 push와 force push를 사용하지 않습니다.
- 초기 독립 squash로 갈라진 계보는 commit을 삭제하지 않고 보호된 동기화 PR로
  한 번 연결합니다.

전체 Epic·하위 이슈·Team Board 운영 규칙은
[integration 문서](https://github.com/DodamDodam-Capstone/integration/blob/main/docs/JIRA_GITHUB_INTEGRATION.md)를
기준으로 합니다.

## 팀 적용 시점

팀원 초대 후 GitHub visible Team `ai`에 AI 담당자를 넣고 이 저장소에
`Write`를 부여합니다. 팀원이 2명 이상일 때만 CODEOWNERS와 리뷰 자동 배정을
사용합니다. Jira에는 `AI` Team을 연결하되 `Assignee`는 실제 담당 개인으로
유지합니다. 빈 팀을 미리 만들거나 Team filter부터 적용하지 않습니다.

## 초기 자동화 검증

- 2026-08-22: `development` 병합 후 GitHub Issue 종료, Jira Task 완료 및
  `#ai-actions` Slack 알림을 확인합니다.
