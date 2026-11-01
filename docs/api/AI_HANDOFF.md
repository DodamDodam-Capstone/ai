# AI_Handoff: BE–AI 연동 API

> 백엔드에서 받은 협의용 API 제안서(AI_Handoff.pdf)를 그대로 옮긴 문서다.
> AI 쪽 구현 현황과 임시로 정한 값은 맨 아래 [AI 구현 현황](#ai-구현-현황)에 따로 적는다.

# 1. 음성 대화 API

> **상태: BE–AI 협의용 API 제안서**
>
> 본 문서의 엔드포인트, 필드명, 오류 코드, 오디오 전달 방식 및 제한 수치는 AI팀과 협의 후 확정한다. 기존 P0 백엔드 정책을 기준으로 작성하되, `expressionCode`는 추가 협의된 기능이다.

## 1.1 BE → AI 요청

### 기본 정보

| 항목 | 내용 |
| --- | --- |
| Method | `POST` |
| Endpoint | `/internal/ai/turns` |
| Content-Type | `multipart/form-data` |
| 요청 주체 | BE (Spring Boot) |
| 처리 주체 | AI (FastAPI) |
| 용도 | STT → LLM 답변 생성 → 표정 결정 → TTS 생성 |

### 요청 데이터

`multipart/form-data`에 다음 두 Part를 포함한다.

| Part 이름 | Content-Type | 내용 | 필수 여부 |
| --- | --- | --- | --- |
| `audio` | `audio/webm` (Opus) | 아이의 음성 파일 바이너리 | 필수 |
| `metadata` | `application/json` | 대화 및 처리에 필요한 메타데이터 | 필수 |

**metadata JSON 예시**

```json
{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "turnId": "44444444-4444-4444-8444-444444444444",
  "locale": "ko-KR",
  "child": {
    "nickname": "도담",
    "interests": ["공룡", "우주"]
  },
  "previousTurns": [
    {
      "role": "child",
      "text": "나는 공룡을 좋아해."
    },
    {
      "role": "assistant",
      "text": "어떤 공룡이 가장 좋아?"
    }
  ],
  "deadline": "2026-10-31T22:00:30+09:00"
}
```

| 필드 | 필수 여부 (제안) | 설명 |
| --- | --- | --- |
| `requestId` | 필수 | BE가 생성하는 AI 호출 추적용 ID |
| `conversationId` | 필수 | 대화 식별자 |
| `turnId` | 필수 | 현재 발화 턴 식별자 |
| `locale` | 필수 | STT 및 AI 답변 언어 설정 |
| `child.nickname` | 필수 | 아이를 부를 호칭 |
| `child.interests` | 선택 | 답변 개인화에 필요한 관심사 |
| `previousTurns` | 필수, 빈 배열 가능 | AI 문맥에 사용할 이전 대화 |
| `previousTurns[].role` | 이전 대화가 있을 때 필수 | `child` 또는 `assistant` |
| `previousTurns[].text` | 이전 대화가 있을 때 필수 | 사용이 허용된 텍스트 |
| `deadline` | 필수 | BE에서 계산한 턴 처리 기한 |

### 요청 처리 규칙

- BE는 WebM(Opus) 음성 원본을 AI에 전달한다.
- `metadata`는 실제 JSON Part로 전송하며, 음성 파일은 Base64가 아닌 바이너리로 전송한다.
- `requestId`, `conversationId`, `turnId`는 BE에서 생성하며 AI는 응답에 동일한 값을 반환한다.
- `previousTurns`에는 안전성 정책상 AI 문맥 재사용이 허용된 텍스트만 포함한다.
- `OMITTED`로 처리된 원문이나 전송이 허용되지 않은 개인정보는 포함하지 않는다.
- `previousTurns`의 최대 길이·개수 및 대화 문맥 선택 기준은 별도 협의한다.
- 음성 크기·길이·MIME Type·코덱 지원 범위는 AI팀과 확정한다.

## 1.2 AI → BE 성공 응답

AI가 STT, LLM, 표정 결정 및 TTS 작업을 완료한 후 결과를 반환한다.

TTS 오디오 전달 방식은 다음 두 가지 중 하나를 선택한다.

| 구분 | A. 오디오 직접 전달 | B. 오디오 참조 전달 |
| --- | --- | --- |
| 전달 방식 | JSON + 오디오 바이너리 | JSON + 오디오 참조 |
| HTTP 응답 형식 | `multipart/mixed` | `application/json` |
| BE → AI 호출 수 | 1회 | 2회 (대화 요청 + 오디오 다운로드) |
| 추가 오디오 API | 불필요 | 필요 |
| 장점 | 한 번의 호출로 결과 확보 | JSON과 파일 처리 분리 |
| 단점 | Multipart 응답 파싱 필요 | 임시 파일 관리와 추가 다운로드 필요 |

### A. 오디오 직접 전달

AI는 하나의 HTTP 응답에 JSON 결과와 실제 TTS 바이너리를 함께 포함한다.

**성공 응답**

```
HTTP/1.1 200 OK
Content-Type: multipart/mixed; boundary=ai-result

--ai-result
Content-Type: application/json
Content-Disposition: attachment; name="result"

{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "turnId": "44444444-4444-4444-8444-444444444444",
  "status": "SUCCEEDED",
  "stt": {
    "text": "오늘 친구랑 놀았어!",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "reply": {
    "text": "정말 재미있었겠다!",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "expressionCode": "HAPPY",
  "tts": {
    "contentType": "audio/wav",
    "allowed": true
  },
  "error": null
}

--ai-result
Content-Type: audio/wav
Content-Disposition: attachment; name="audio"; filename="reply.wav"

[WAV 바이너리 데이터]

--ai-result--
```

`[WAV 바이너리 데이터]`는 설명용 표기이며 실제 응답에는 음성 파일 바이트가 포함된다.

**응답 Part 정의**

| Part 이름 | Content-Type | 내용 |
| --- | --- | --- |
| `result` | `application/json` | STT, AI 답변, 표정, 안전성 및 TTS 메타데이터 |
| `audio` | `audio/wav` | AI가 생성한 TTS 음성 바이너리 |

**A안 처리 규칙**

- 성공 응답에는 `result` Part가 포함되어야 한다.
- `tts.allowed=true`로 음성 제공이 허용된 성공 응답에는 유효한 `audio` Part가 포함되어야 한다.
- JSON의 `tts.contentType`과 실제 오디오 Part의 Content-Type은 일치해야 한다.
- BE는 JSON과 오디오를 모두 검증한 뒤 원래 deadline 이전에 턴 성공을 확정한다.
- 실패 응답은 `multipart/mixed`가 아닌 `application/json`으로 통일하는 것을 제안한다.

### B. 오디오 참조 전달

AI는 먼저 STT·LLM·표정·TTS 생성 결과를 JSON으로 반환하며, 실제 오디오는 별도 API로 제공한다.

**1단계. AI → BE 성공 응답**

```
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "turnId": "44444444-4444-4444-8444-444444444444",
  "status": "SUCCEEDED",
  "stt": {
    "text": "오늘 친구랑 놀았어!",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "reply": {
    "text": "정말 재미있었겠다!",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "expressionCode": "HAPPY",
  "tts": {
    "audioReference": "audio-001",
    "contentType": "audio/wav",
    "allowed": true,
    "expiresAt": "2026-10-31T22:03:00+09:00"
  },
  "error": null
}
```

**2단계. BE → AI 오디오 다운로드 요청**

```
GET /internal/ai/audio/audio-001 HTTP/1.1
Authorization: Bearer <server-token>
```

인증 헤더는 예시이며 실제 서버 간 인증 방식은 별도 협의한다.

**3단계. AI → BE 오디오 바이너리 응답**

```
HTTP/1.1 200 OK
Content-Type: audio/wav
Content-Length: 482044

[WAV 바이너리 데이터]
```

`Content-Length`는 예시값이며 실제 파일 크기에 따라 달라진다.

**B안 오디오 다운로드 규칙**

| 항목 | 제안 규칙 |
| --- | --- |
| Endpoint | `GET /internal/ai/audio/{audioReference}` |
| 요청 주체 | BE |
| 인증 | 서버 간 인증 필수 |
| 정상 응답 | HTTP 200 + 오디오 바이너리 |
| 참조 없음 | `404 Not Found` |
| 참조 만료 | `410 Gone` |
| AI 서버 오류 | `5xx` |
| 오디오 MIME Type | AI·BE 협의 후 확정 |
| 참조 TTL | AI·BE 협의 후 확정 |

- `audioReference`는 AI가 관리하는 임시 오디오 식별자이며, FE에 그대로 전달하지 않는다.
- AI가 성공 JSON을 반환하는 시점에는 해당 오디오를 다운로드할 수 있어야 한다.
- `expiresAt`은 AI 측 오디오 참조의 다운로드 만료 시각이다.
- BE는 원래 `deadline` 이전에 오디오 다운로드·검증·최종 저장을 완료해야 한다.
- `expiresAt`이 남아 있어도 원래 `deadline`이 지나면 턴을 성공 처리할 수 없다.
- 오디오 다운로드 실패는 AI 측 작업 실패로 처리하되, 원래 deadline이 초과된 경우에는 BE의 Timeout 정책을 적용한다.
- 동일 참조의 다운로드 재시도 허용 여부는 협의하되, 동일 턴의 STT·LLM·TTS 생성을 재실행해서는 안 된다.
- 다운로드 후 BE는 자체 임시 음성 저장소에 보관하고 FE에는 BE의 인증된 음성 조회 API만 제공한다.

### 성공 응답 필드 설명

| 필드 | 의미 | BE 처리 |
| --- | --- | --- |
| `requestId` | AI 호출 식별자 | 기존 요청과 일치하는지 검증 |
| `conversationId` | 대화 식별자 | 기존 대화와 일치하는지 검증 |
| `turnId` | 턴 식별자 | 기존 턴과 일치하는지 검증 |
| `status` | AI 처리 결과 | AI 작업 완료 여부 확인 |
| `stt` | 음성 인식 텍스트·안전성 정보 | 허용된 텍스트만 저장 |
| `reply` | AI 답변 텍스트·안전성 정보 | 허용된 텍스트만 저장 |
| `expressionCode` | 도담이 캐릭터 표정 코드 | 검증 후 아이용 FE에 제공 |
| `tts` | TTS 음성 정보 | 음성 확보·검증 및 임시 저장 |
| `error` | 오류 정보 | 성공 시 `null` |

**AI 성공과 BE 성공의 구분**

AI의 `status=SUCCEEDED`는 AI 측 STT·LLM·TTS 생성이 성공했다는 의미이다.

BE는 응답의 식별자·안전성·오디오를 검증하고 원래 deadline 이전에 최종 저장할 수 있는 경우에만 턴 상태를 `SUCCEEDED`로 확정한다.

특히 B안은 AI가 `SUCCEEDED`를 반환했더라도 BE가 오디오를 확보하지 못했다면 턴을 성공 처리하지 않는다.

## 1.3 AI → BE 공통 실패 응답

A안과 B안 모두 실패 응답은 동일한 JSON 구조를 사용하는 것을 제안한다.

- Content-Type: `application/json`
- JSON `status`: `FAILED`
- 오류 위치: `error.stage`
- 오류 코드: `error.code`
- 구체적인 HTTP 실패 상태 코드 사용 여부는 AI팀과 별도 합의한다.

### STT 무음 실패 예시

```json
{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "turnId": "44444444-4444-4444-8444-444444444444",
  "status": "FAILED",
  "stt": null,
  "reply": null,
  "expressionCode": null,
  "tts": null,
  "error": {
    "stage": "STT",
    "code": "NO_SPEECH"
  }
}
```

### LLM 답변 생성 실패 예시

```json
{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "turnId": "44444444-4444-4444-8444-444444444444",
  "status": "FAILED",
  "stt": {
    "text": "오늘 친구랑 놀았어!",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "reply": null,
  "expressionCode": null,
  "tts": null,
  "error": {
    "stage": "LLM",
    "code": "GENERATION_FAILED"
  }
}
```

### TTS 생성 실패 예시

```json
{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "turnId": "44444444-4444-4444-8444-444444444444",
  "status": "FAILED",
  "stt": {
    "text": "오늘 친구랑 놀았어!",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "reply": {
    "text": "정말 재미있었겠다!",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "expressionCode": null,
  "tts": null,
  "error": {
    "stage": "TTS",
    "code": "TTS_GENERATION_FAILED"
  }
}
```

### 부분 결과 유지 정책

- AI는 실패가 발생하더라도 이전 단계에서 생성한 STT·AI 답변이 있고 해당 텍스트의 저장·표시가 허용된다면 이를 포함해 반환할 수 있다.
- BE는 실패 응답을 받으면 턴 전체를 `FAILED`로 처리한다.
- 단, 저장이 허용된 STT·AI 답변 텍스트는 정책 범위 내에서 보존할 수 있다.
- 실패한 턴에는 정상 TTS 음성을 제공하지 않는다.
- 실패 응답에서 `expressionCode`는 `null`로 반환하는 것을 권장한다.
- 실패 응답의 JSON이 누락되거나 파싱할 수 없는 경우에도 BE에서 자체 실패 처리가 가능해야 한다.

## 1.4 오류 코드

AI 내부 오류 코드는 AI팀에서 정의하고, BE는 이를 기존 서비스 오류 코드로 매핑한다.

| 실패 상황 | `error.stage` | `error.code` (제안) | BE → FE |
| --- | --- | --- | --- |
| STT 무음 | `STT` | `NO_SPEECH` | `422 STT_NO_SPEECH` |
| LLM 생성 실패 | `LLM` | `GENERATION_FAILED` | `502 AI_UPSTREAM_FAILED` |
| TTS 생성 실패 | `TTS` | `TTS_GENERATION_FAILED` | `502 AI_UPSTREAM_FAILED` |
| 오디오 다운로드 실패 | 다운로드 단계에서 BE 판정 | 별도 협의 | `502 AI_UPSTREAM_FAILED` 등 기존 정책에 따른 매핑 |
| 전체 처리 기한 초과 | BE 자체 판단 | AI 응답 불필요 | `504 AI_TIMEOUT` |

### 오류 처리 규칙

- AI 측 오류 코드명은 예시이며 실제 코드 목록을 AI팀과 확정한다.
- AI의 내부 처리 실패와 BE의 전체 Timeout은 구분한다.
- BE는 원래 `processing_deadline_at`을 기준으로 전체 Timeout을 판정한다.
- AI가 응답하지 않더라도 BE는 `AI_TIMEOUT`으로 실패 상태를 확정할 수 있어야 한다.
- deadline 도달 후 성공 응답이 도착해도 최종 성공으로 반영하지 않는다.
- 동일 턴의 AI 작업을 자동으로 재실행하지 않는다.
- 알 수 없는 오류를 근거 없이 `STT_NO_SPEECH`으로 분류하지 않는다.

**FE에 전달하는 HTTP 상태 코드 주의**

위 `422`, `502`, `504`는 최초 음성 대화 POST 요청에서 실패가 동기적으로 확정된 경우의 서비스 응답 코드이다.

BE가 이미 FE에 `202 PROCESSING`을 반환한 경우에는 기존 HTTP 응답을 변경할 수 없으므로, 이후 권한이 확인된 조회 요청에서 HTTP 200과 `FAILED` 상태로 결과를 제공한다.

## 1.5 공통 처리 정책

### 1.5.1 안전성 판정

AI는 STT 텍스트와 AI 답변 텍스트에 대해 각각 독립적인 안전성 판정 정보를 반환한다.

| `visibility` | `text` | `saveAllowed` | `displayAllowed` | BE 처리 |
| --- | --- | --- | --- | --- |
| `VISIBLE` | 허용된 원문 | `true` | `true` | 원문 저장·표시 가능 |
| `REDACTED` | 허용된 가공문 | `true` | `true` | 가공문만 저장·표시 가능 |
| `OMITTED` | `null` | `false` | `false` | 텍스트 저장·표시 금지 |

**예시: 가공문만 허용**

```json
{
  "stt": {
    "text": "친구와 있었던 일을 이야기했어.",
    "visibility": "REDACTED",
    "saveAllowed": true,
    "displayAllowed": true
  }
}
```

**예시: 텍스트 제공 불가**

```json
{
  "stt": {
    "text": null,
    "visibility": "OMITTED",
    "saveAllowed": false,
    "displayAllowed": false
  }
}
```

**판정 규칙**

- `VISIBLE`: 원문의 저장·표시가 모두 허용된 경우에만 사용한다.
- `REDACTED`: 원문이 아닌, 허용된 가공문을 전달하는 경우에만 사용한다.
- `OMITTED`: 저장·표시 가능한 텍스트가 없는 경우에 사용한다.
- `REDACTED`의 `text`에는 금지된 원문이 아니라 허용된 가공문만 포함해야 한다.
- `visibility`와 허용 정보가 충돌하거나 필수 안전성 정보가 누락되면 BE는 해당 텍스트를 저장·표시하지 않는다.
- 텍스트 안전성 판정과 TTS 오디오의 `allowed` 판정은 별개이다.
- 최종 저장·표시 허용 여부는 BE에서 검증한다.
- 금지된 원문은 DB나 일반 애플리케이션 로그에 남기지 않는다.

### 1.5.2 캐릭터 표정 코드 (`expressionCode`)

`expressionCode`는 아이의 감정 자체가 아니라 **도담이 캐릭터가 FE에서 표현할 표정**을 나타낸다.

**표정 코드 목록 (협의용 예시)**

| 코드 | 의미 |
| --- | --- |
| `HAPPY` | 기쁨 |
| `NEUTRAL` | 기본 |
| `CARING` | 위로 |
| `SURPRISED` | 놀람 |
| `SAD` | 슬픔 |

**처리 규칙**

- AI는 턴별로 캐릭터 표정 코드를 결정한다.
- 표정 코드 목록은 AI팀의 분류 기준과 FE의 캐릭터 구현 범위에 맞춰 확정한다.
- 감정 분류에 실패한 경우 `expressionCode=null`을 반환하고 FE에서 기본 표정을 표시하는 방식을 제안한다.
- 표정 결정 실패만으로 STT·LLM·TTS가 성공한 전체 턴을 실패 처리하지 않는 방식을 제안한다.
- BE는 허용된 표정 코드인지 검증한 후 아이용 FE에 제공한다.
- 보호자 기록 API에는 `expressionCode`를 제공하지 않는다.
- 향후 감정 리포트에서 사용할 아이의 감정 분석 결과는 `expressionCode`와 별도 데이터로 관리한다.

### 1.5.3 Deadline 및 Timeout

BE는 턴 최초 접수 시점에 전체 처리 기한을 결정한다.

**기준**

```
processing_deadline_at
= BE의 DB 접수 시각 + TURN_PROCESSING_TIMEOUT
```

AI에는 이 기한을 `deadline` 필드로 전달한다.

**처리 규칙**

- AI는 deadline 이전에 결과를 반환하도록 처리한다.
- A안은 JSON·음성 검증 및 성공 확정까지 원래 기한 내에 완료해야 한다.
- B안은 JSON 수신 이후 오디오 다운로드·검증 및 성공 확정까지 원래 기한 내에 완료해야 한다.
- BE의 현재 DB 시각이 `processing_deadline_at` 이상이면 성공으로 확정할 수 없다.
- deadline 도달 시 BE는 턴을 `FAILED / AI_TIMEOUT`으로 확정한다.
- deadline 이후 도착한 결과는 턴 상태를 변경하지 않는다.
- Timeout 이후 같은 턴의 AI 처리를 자동 재실행하지 않는다.
- `TURN_PROCESSING_TIMEOUT`의 실제 수치는 AI팀의 처리 성능 측정 결과를 바탕으로 협의한다.
- FE에 처음 응답하는 동기 대기 시간과 전체 처리 deadline은 별도로 관리한다.

### 1.5.4 식별자 및 중복 실행 방지

- BE에서 `requestId`, `conversationId`, `turnId`를 생성한다.
- AI는 수신한 식별자를 응답에 동일하게 반환한다.
- BE는 기존 요청 및 DB 레코드와 세 식별자의 일치 여부를 확인한다.
- 식별자가 일치하지 않는 결과는 해당 턴에 반영하지 않는다.
- 중복 FE 요청 또는 네트워크 오류가 발생하더라도 동일 논리 턴에 대한 AI 실행은 최대 1회 시도한다.
- 오디오 참조 다운로드는 기존 생성 결과의 조회이며, 새 STT·LLM·TTS 생성 요청과 구분한다.

### 1.5.5 파일 제한·보관 및 서버 간 인증

다음 값은 AI팀과 최종 협의해야 한다.

| 항목 | 협의 사항 |
| --- | --- |
| 입력 오디오 | WebM(Opus) 지원 MIME Type 및 코덱 |
| 입력 제한 | 최대 파일 크기·길이·채널·샘플레이트 |
| 출력 오디오 | WAV 등 TTS 출력 형식·크기 |
| 음성 검증 | MIME Type, 파일 크기, 유효한 바이너리 여부 |
| 서버 간 인증 | 인증 방식, 인증정보 관리 및 통신 보안 |
| AI 오디오 TTL | B안의 임시 참조 만료 시간 |
| BE 오디오 TTL | FE 재생용 임시 음성의 보관 시간 |
| AI 측 파일 삭제 | 음성 원본·TTS 및 임시 파일의 삭제 기준 |
| AI 측 로그 | 아동 개인정보·대화 원문·음성 정보의 로그 기록 제한 |
| 부분 실패 | TTS 실패, 응답 손상, 다운로드 실패 시 처리 |
| AI 응답 HTTP 코드 | 성공 및 실패 JSON의 HTTP 상태 코드 규칙 |

### 최종 합의가 필요한 항목

- [ ] A안과 B안 중 TTS 응답 전달 방식 선택
- [ ] 요청·응답 JSON 및 Multipart Part 명칭 확정
- [ ] STT·답변 안전성 판정 스키마 확정
- [ ] `expressionCode` enum 및 실패 정책 확정
- [ ] AI 단계별 오류 코드 확정
- [ ] AI 응답의 HTTP 상태 코드 확정
- [ ] 처리 Timeout 및 파일 제한 수치 확정
- [ ] B안 선택 시 오디오 다운로드 인증·만료·오류 규칙 확정
- [ ] 서버 간 보안 및 임시 파일 보관·삭제 정책 확정

# 2. 대화 요약 API

> **상태: BE–AI 협의용 API 제안서**
>
> 대화가 종료되면 BE가 허용된 대화 텍스트를 AI에 전달하고, AI는 `title`, `topic`, `summary`를 생성한다.
>
> 엔드포인트, JSON 필드명, AI 내부 오류 코드 및 처리 제한 수치는 AI팀과 협의 후 확정한다.

## 2.1 BE → AI 요청

### 기본 정보

| 항목 | 내용 |
| --- | --- |
| Method | `POST` |
| Endpoint | `/internal/ai/summaries` |
| Content-Type | `application/json` |
| 요청 주체 | BE (Spring Boot) |
| 처리 주체 | AI (FastAPI) |
| 용도 | 종료된 대화의 제목·주제·요약 생성 |

### 요청 JSON 예시

```json
{
  "requestId": "660e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "locale": "ko-KR",
  "turns": [
    {
      "sequence": 1,
      "childText": "오늘 친구랑 축구했어!",
      "replyText": null
    },
    {
      "sequence": 2,
      "childText": "우리 팀이 이겼어!",
      "replyText": "정말 신났겠네!"
    }
  ],
  "deadline": "2026-10-31T22:05:00+09:00"
}
```

### 요청 필드 설명

| 필드 | 필수 여부 (제안) | 설명 |
| --- | --- | --- |
| `requestId` | 필수 | BE가 생성한 요약 작업 추적 ID |
| `conversationId` | 필수 | 요약 대상 대화 식별자 |
| `locale` | 필수 | 요약 생성 언어 |
| `turns` | 필수 | 요약에 사용할 허용된 대화 텍스트 배열 |
| `turns[].sequence` | 필수 | 원래 대화에서의 턴 순서 |
| `turns[].childText` | 필수 키, null 가능 | 아이 발화의 허용된 텍스트 |
| `turns[].replyText` | 필수 키, null 가능 | AI 답변의 허용된 텍스트 |
| `deadline` | 필수 | BE가 정한 요약 처리 기한 |

### 요청 데이터 처리 규칙

- BE는 대화가 완전히 종료된 후 요약 요청을 수행한다.
- `turns`에는 저장 및 요약 사용이 허용된 텍스트만 포함한다.
- `childText`와 `replyText`는 각각 `string | null`이다.
- 허용되지 않은 텍스트는 `null`로 전달하며, 금지된 원문을 복원하거나 전달하지 않는다.
- 두 값이 모두 `null`인 턴은 요청 배열에서 제외한다.
- `turns`는 원래 대화 순서대로 정렬한다.
- `sequence`는 원래 턴의 순서값을 유지하며, 일부 턴이 제외되더라도 다시 번호를 매기지 않는다.
- `FAILED` 턴이라도 저장 및 요약 사용이 허용된 텍스트가 있다면 요약 입력에 포함할 수 있다.
- 요약에 사용할 수 있는 텍스트가 하나도 없다면 AI를 호출하지 않고 BE 요약 상태를 `EMPTY`로 처리한다.
- `requestId`는 음성 대화 요청과 별도로 생성한 요약 작업 전용 ID를 사용한다.
- 전송 가능한 최대 턴 수 및 총 텍스트 길이는 AI팀과 협의한다.

## 2.2 AI → BE 성공 응답

AI는 대화 내용을 바탕으로 제목, 주제, 요약을 생성하고 각 결과의 저장·표시 허용 정보를 함께 반환한다.

### 성공 응답

**HTTP 200 OK**

Content-Type: `application/json`

```json
{
  "requestId": "660e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "status": "SUCCEEDED",
  "title": {
    "text": "친구와 즐거운 축구",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "topic": {
    "text": "친구 관계와 운동",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "summary": {
    "text": "아이가 친구들과 축구한 경험과 자신의 팀이 승리했던 일을 이야기했습니다.",
    "visibility": "VISIBLE",
    "saveAllowed": true,
    "displayAllowed": true
  },
  "error": null
}
```

`visibility`는 음성 대화 API와 안전성 표현을 통일하기 위해 추가한 제안 필드이다. AI팀과 실제 사용 여부를 확정한다.

### 성공 응답 필드 설명

| 필드 | 의미 | BE 처리 |
| --- | --- | --- |
| `requestId` | 요약 작업 식별자 | 요청과 응답 일치 검증 |
| `conversationId` | 대화 식별자 | 요약 대상 대화와 일치 검증 |
| `status` | AI 요약 생성 결과 | AI 작업 완료 여부 확인 |
| `title` | 대화 제목 및 안전성 정보 | 허용 여부 검증 후 저장 |
| `topic` | 대화 전체 주제 및 안전성 정보 | 허용 여부 검증 후 저장 |
| `summary` | 대화 요약 본문 및 안전성 정보 | 허용 여부 검증 후 저장 |
| `error` | 오류 정보 | 성공 시 `null` |

### AI 성공과 BE 요약 완료의 구분

AI의 `status=SUCCEEDED`는 **AI 측 요약 생성이 완료되었다는 의미**이다.

BE는 다음 조건을 모두 만족하는 경우에만 요약 상태를 `READY`로 확정한다.

- `requestId`, `conversationId`가 원래 요청과 일치한다.
- `title`, `topic`, `summary` 세 필드가 모두 존재한다.
- 세 필드의 `text`가 유효한 비어 있지 않은 문자열이다.
- 세 필드 각각의 `saveAllowed`, `displayAllowed`가 모두 `true`이다.
- 세 필드의 안전성 판정 정보가 유효하고 서로 모순되지 않는다.
- 원래 요약 deadline 이전에 결과 검증 및 저장이 완료된다.

**세 필드 중 하나라도 조건을 충족하지 못하면 BE는 요약을 `FAILED`로 처리하고 `title`, `topic`, `summary`를 모두 `null`로 유지한다.**

## 2.3 AI → BE 실패 응답

AI가 요약 생성에 실패하면 `status=FAILED`와 오류 정보를 반환한다.

### 요약 생성 실패 예시

Content-Type: `application/json`

```json
{
  "requestId": "660e8400-e29b-41d4-a716-446655440000",
  "conversationId": "33333333-3333-4333-8333-333333333333",
  "status": "FAILED",
  "title": null,
  "topic": null,
  "summary": null,
  "error": {
    "stage": "SUMMARY",
    "code": "SUMMARY_GENERATION_FAILED"
  }
}
```

### 실패 응답 처리 규칙

- `status=FAILED`인 경우 `error` 객체를 포함한다.
- `error.stage`는 실패한 AI 처리 단계를 나타낸다.
- `error.code`는 AI팀에서 정의한 내부 오류 코드이다.
- `SUMMARY_GENERATION_FAILED`는 제안 코드이며 AI팀과 협의 후 확정한다.
- AI가 실패 응답을 반환하면 BE는 요약 상태를 `FAILED`로 확정한다.
- `FAILED` 상태에서 `title`, `topic`, `summary`는 모두 `null`로 유지한다.
- 요약 실패가 이미 종료된 대화의 상태를 변경하지는 않는다.
- AI 서버 장애·네트워크 오류 등으로 정상 JSON을 받지 못하더라도 BE는 자체 실패 처리를 수행할 수 있어야 한다.
- AI 처리 실패를 HTTP 200 + `FAILED`로 반환할지, 별도 4xx·5xx를 사용할지는 AI팀과 협의한다.

## 2.4 오류 코드

AI 내부 오류 코드는 AI팀에서 정의하며, BE는 이를 요약 작업의 실패 상태로 변환한다.

| 실패 상황 | `error.stage` | `error.code` (제안) | BE 처리 |
| --- | --- | --- | --- |
| 요약 생성 실패 | `SUMMARY` | `SUMMARY_GENERATION_FAILED` | `FAILED` |
| 결과 누락·형식 오류 | BE 검증 | AI 코드 불필요 | `FAILED` |
| 저장·표시 허용 조건 불충족 | BE 검증 | AI 코드 불필요 | `FAILED` |
| AI 서버 또는 통신 장애 | 응답 없을 수 있음 | 별도 협의 | `FAILED` |
| 요약 처리 기한 초과 | BE 자체 판단 | AI 응답 불필요 | `FAILED` |
| 허용된 요약 입력 없음 | AI 호출 없음 | 해당 없음 | `EMPTY` |

### 오류 처리 원칙

- AI의 오류 코드와 BE의 요약 상태는 구분한다.
- AI의 성공 응답을 받았더라도 BE 검증에 실패하면 요약 상태는 `FAILED`이다.
- AI가 응답하지 않아도 BE가 자체 Timeout을 판단한다.
- 요약 실패 후 자동 재요청하지 않는다.
- 요약 실패 때문에 대화를 다시 `ACTIVE`나 `CLOSING`으로 변경하지 않는다.

## 2.5 공통 처리 정책

### 2.5.1 요약 실행 조건

BE는 대화 종료 절차가 완료된 후 요약을 실행한다.

**대화 상태 흐름**

```
ACTIVE
   ↓ 대화 종료 요청
CLOSING
   ↓ 기존에 접수된 모든 턴 처리 완료
ENDED
   ↓ 허용된 요약 입력 확인
PENDING → READY / FAILED
   또는
EMPTY
```

`PENDING`, `READY`, `FAILED`, `EMPTY`는 대화 상태가 아니라 **별도의 요약 상태**이다.

**실행 규칙**

- 대화가 `ENDED` 상태가 된 후 요약 작업을 실행한다.
- 종료 이전에 접수된 턴은 모두 `SUCCEEDED` 또는 `FAILED`로 확정되어 있어야 한다.
- 허용된 요약 입력이 없는 경우 `EMPTY`로 처리하고 AI를 호출하지 않는다.
- 허용된 요약 입력이 있는 경우 `PENDING`에서 요약 작업을 시작한다.
- 대화별 AI 요약 생성은 최대 1회만 시도한다.
- 요약 중복 호출을 막기 위해 BE에서 작업의 최초 실행 여부를 관리한다.
- 요약이 `PENDING`이거나 `FAILED`이더라도 새로운 대화 시작을 차단하지 않는다.
- 요약 결과는 반드시 원래 `conversationId`에 연결해 저장한다.

### 2.5.2 안전성 판정

AI는 `title`, `topic`, `summary`를 각각 독립적으로 검증하고 저장·표시 허용 정보를 반환한다.

음성 대화 API와의 일관성을 위해 다음 표현을 제안한다.

| `visibility` | `text` | `saveAllowed` | `displayAllowed` | 의미 |
| --- | --- | --- | --- | --- |
| `VISIBLE` | 허용된 원문 결과 | `true` | `true` | 결과 그대로 저장·표시 가능 |
| `REDACTED` | 허용된 가공 결과 | `true` | `true` | 가공된 결과만 저장·표시 가능 |
| `OMITTED` | `null` | `false` | `false` | 저장·표시 불가 |

**가공된 요약 결과 예시**

```json
{
  "summary": {
    "text": "아이가 친구들과 있었던 경험을 이야기했습니다.",
    "visibility": "REDACTED",
    "saveAllowed": true,
    "displayAllowed": true
  }
}
```

**처리 규칙**

- `VISIBLE`은 생성된 결과를 그대로 저장·표시할 수 있을 때 사용한다.
- `REDACTED`는 민감하거나 허용되지 않은 표현을 제거한 가공 결과에 사용한다.
- `REDACTED`의 `text`에는 원래 금지된 내용을 포함하지 않는다.
- `OMITTED`는 저장·표시 가능한 결과가 없을 때 사용한다.
- `visibility`와 `saveAllowed`, `displayAllowed`가 서로 모순되면 해당 응답을 유효한 결과로 인정하지 않는다.
- 제목·주제·요약 중 하나라도 비허용이라면 부분 저장하지 않고 전체 요약을 `FAILED`로 처리한다.
- 금지된 원문 및 비허용 요약 데이터는 DB나 일반 로그에 남기지 않는다.
- 최종 저장·표시 허용 여부는 BE에서 검증한다.

### 2.5.3 Deadline 및 Timeout

요약 작업에는 음성 대화 턴과 별도의 처리 기한을 적용한다.

**기준**

```
summary_deadline_at
= 요약 작업 시작 시각 + SUMMARY_PROCESSING_TIMEOUT
```

BE는 계산한 절대 시각을 요청 JSON의 `deadline`에 포함한다.

**처리 규칙**

- 요약 작업의 시작 시각과 처리 기한은 BE에서 관리한다.
- AI는 전달받은 deadline을 기준으로 요약 처리를 수행한다.
- BE는 deadline 이전에 수신·검증·저장이 완료된 결과만 `READY`로 확정한다.
- DB 현재 시각이 요약 deadline 이상이면 성공으로 확정하지 않는다.
- deadline에 도달했는데 요약이 완료되지 않았다면 `FAILED`로 처리한다.
- deadline 이후 도착한 AI 성공 응답은 반영하지 않는다.
- Timeout 또는 실패 후 같은 대화의 AI 요약을 자동 재실행하지 않는다.
- `SUMMARY_PROCESSING_TIMEOUT`의 실제 수치는 AI팀 처리 성능을 확인한 후 확정한다.

### 2.5.4 식별자 및 중복 실행 방지

- `requestId`는 BE가 생성하는 요약 작업별 고유 ID이다.
- `conversationId`는 요약할 대화의 기존 ID를 사용한다.
- AI는 두 식별자를 응답에 그대로 반환한다.
- BE는 요청·응답 식별자가 일치하는지 검증한다.
- 다른 대화나 다른 요약 작업의 결과를 저장해서는 안 된다.
- 동일 대화에 대한 중복 종료 요청이 발생해도 요약을 중복 실행하지 않는다.
- 요약 실행 시작 여부는 BE에서 원자적으로 관리하여 동시 요청으로 인한 중복 호출을 방지한다.
- 네트워크 오류, 서버 재시작, Timeout 등으로 호출 결과가 불명확하더라도 AI 요약 생성의 자동 재실행을 수행하지 않는다.

### 2.5.5 입력·출력 제한 및 서버 간 보안

다음 사항은 AI팀과 협의하여 확정한다.

| 항목 | 협의 사항 |
| --- | --- |
| 입력 턴 수 | 요약 요청에 포함할 최대 턴 수 |
| 입력 텍스트 길이 | 전체 입력의 최대 글자·토큰 수 |
| 출력 길이 | `title`, `topic`, `summary` 각각의 최대 길이 |
| 주제 형식 | 자유 문자열 또는 사전에 정의한 주제 코드 |
| 응답 형식 | JSON 필드명·필수 여부·null 허용 규칙 |
| 안전성 판정 | `visibility` 사용 여부 및 필드별 허용 기준 |
| 오류 코드 | 요약 생성 실패 코드 및 HTTP 상태 코드 |
| 처리 시간 | `SUMMARY_PROCESSING_TIMEOUT` 값 |
| 서버 간 인증 | 인증 방식 및 HTTPS/TLS 적용 |
| 로그·보관 | 아동 대화 원문·요약 입력의 기록 및 삭제 정책 |

### 최종 합의가 필요한 항목

- 요약 API 엔드포인트 및 요청·응답 필드명 확정
- `childText`, `replyText`의 null 처리 규칙 확정
- 요약 입력 최대 턴 수 및 텍스트 길이 제한 확정
- `title`, `topic`, `summary`의 결과 형식·최대 길이 확정
- 요약 결과의 안전성 판정 스키마 확정
- AI 측 요약 실패 오류 코드 및 HTTP 상태 코드 확정
- `SUMMARY_PROCESSING_TIMEOUT` 수치 확정
- 서버 간 인증 및 로그·개인정보 삭제 정책 확정

> **핵심 원칙:** AI는 허용된 대화 텍스트를 바탕으로 제목·주제·요약 및 안전성 정보를 생성한다. BE는 요약 호출 시점과 횟수, 식별자 검증, 처리 기한, 저장 허용 여부 및 최종 요약 상태를 관리한다.

---

# AI 구현 현황

명세 중 AI 쪽이 지금 구현한 범위와, 협의 전이라 임시로 정한 값이다. 코드는 `api/` 에 있다.

| 항목 | 현재 구현 |
| --- | --- |
| 1장 음성 대화 API | 구현 (`api/turn_service.py`, `api/server.py`) |
| TTS 전달 방식 | B안 (오디오 참조). `GET /internal/ai/audio/{ref}` → 200 / 404 / 410 |
| TTS 엔진 | 없음. 지금은 항상 `FAILED / TTS / TTS_UNAVAILABLE` (stt·reply 는 실림) |
| 2장 대화 요약 API | 미구현 |
| AI 응답 HTTP 코드 | 성공·실패 모두 200, `status` 로 구분 |
| 서버 간 인증 | `AI_SERVER_TOKEN` 환경변수가 있으면 `Authorization: Bearer <토큰>` 필수 (불일치 401) |
| 입력 음성 | WebM(Opus) 외 m4a·wav 도 읽음. 최대 10MB |
| 오디오 참조 TTL | 10분 |
| deadline 여유 | B안 다운로드 시간을 위해 deadline 1초 전까지 처리 |

**`visibility` 판정**

| 대상 | 조건 | 결과 |
| --- | --- | --- |
| `stt` | 입력 안전 검사 L4(보호 필요) 또는 BLOCK | `OMITTED` |
| `reply` | 해당 턴이 L4 | `OMITTED` (아이는 TTS 음성으로 보호 응답을 듣는다) |
| 그 외 | | `VISIBLE` |
| `REDACTED` | 가공(마스킹) 기능이 없어 아직 쓰지 않음 | |

**`expressionCode` (임시)**

| 조건 | 코드 |
| --- | --- |
| 위험 단계 L2 이상 | `CARING` |
| 아이 감정 기쁨 | `HAPPY` |
| 아이 감정 슬픔·화남·두려움 | `CARING` |
| 중립 | `NEUTRAL` |
| 감정 분류 실패 / 실패 응답 | `null` |

**AI 오류 코드**

| `stage` | `code` | 상황 |
| --- | --- | --- |
| `REQUEST` | `INVALID_REQUEST` | metadata·audio Part 누락, 필수 필드 누락, 형식 오류 |
| `REQUEST` | `UNSUPPORTED_LOCALE` | `ko-KR` 외 locale |
| `REQUEST` | `AUDIO_TOO_LARGE` | 10MB 초과 |
| `REQUEST` | `NOT_READY` | 서버 시작 중 (모델 로딩 전) |
| `REQUEST` 등 진행 단계 | `DEADLINE_EXCEEDED` | AI 쪽에서 deadline 초과를 감지 |
| `STT` | `NO_SPEECH` | 인식 결과가 비어 있음 |
| `STT` | `UNSUPPORTED_AUDIO` | 읽을 수 없거나 손상된 음성 |
| `STT` | `STT_FAILED` | STT 모델 오류 |
| `LLM` | `GENERATION_FAILED` | 답변 생성 실패 |
| `TTS` | `TTS_UNAVAILABLE` | TTS 엔진 미설정 |
| `TTS` | `TTS_GENERATION_FAILED` | 음성 생성 실패 |
| 진행 단계 | `INTERNAL_ERROR` | 그 밖의 오류 |

**알려진 한계**

- Qwen3-ASR 는 무음 입력에도 "그렇죠." 같은 문장을 만들어 `NO_SPEECH` 가 거의 나오지 않는다. 무음·잘못 누름은 STT 전에 BE 에서 거르는 것을 권한다.
- 위험 단계(L0~L4)는 응답에 싣지 않는다. 별도 저장(테이블 A)이 생기기 전까지 어디에도 남지 않는다.
