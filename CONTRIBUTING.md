# 기여 가이드

PR 제목은 `<gitmoji> <type>(optional-scope): <description>` 형식을 사용합니다.

예시:

```text
✨ feat: 추천 endpoint 추가
🐛 fix(model): 빈 입력 batch 처리
✅ test: 잘못된 inference 요청 검사 추가
```

`main`과 `development`의 모든 변경은 PR을 사용해야 합니다. 필수 검사를
통과하고 모든 review conversation을 해결한 후 squash merge합니다. 자동
브랜치 삭제는 사용하지 않으며 작업 브랜치는 sprint 정리 시 수동으로
삭제합니다.
