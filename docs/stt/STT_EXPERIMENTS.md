# STT: Qwen3-ASR 1.7B 아동 음성 인식 (SCRUM-120)

- Jira: [SCRUM-120 [AI] STT](https://dodamdodam.atlassian.net/browse/SCRUM-120) (상위: SCRUM-51 [AI] 음성 AI 대화)
- 목적: 7~10세 아동 음성을 텍스트로 바꾸는 STT 엔진 선정과 검증
- **선정 모델: Qwen3-ASR 1.7B** (`Qwen/Qwen3-ASR-1.7B`), STT 결과 후처리 없음
- 서비스 코드: [`stt/qwen.py`](../../stt/qwen.py) / 평가 코드: [`stt_eval/`](../../stt_eval/) / 연동 명세: [`docs/api/AI_HANDOFF.md`](../api/AI_HANDOFF.md)

## 1. 선정 근거

같은 연령별 400개 문장에서 후보를 비교했고, Qwen3-ASR 1.7B 가 가장 정확했다.

| 후보 | 문장 평균 Normalized CER (400개) | 비고 |
|---|---|---|
| **Qwen3-ASR 1.7B** | **4.53%** | 전 세트·전 연령 1위 |
| Qwen3-ASR 0.6B | 7.68% | 더 빠르지만 덜 정확 |
| CLOVA Speech | 11.58% | 외부 API |

- Whisper turbo 는 별도 100개 세트에서 Normalized Corpus CER 6.48%, 문장당 약 4초로 느렸다.
- STT 결과에 LLM 후처리를 일괄 적용하면 정답이던 문장까지 고쳐 CER 이 나빠졌다(CLOVA 기준 13.4% → 21.1%). 그래서 후처리는 하지 않는다.
- 위 비교 실험 코드와 결과는 PR #41 이력에 있고, 이 저장소에는 선정된 Qwen3-ASR 1.7B 의 재현 코드만 남겼다.

## 2. 데이터셋

AI-Hub `011.한국어 아동 음성 데이터`의 **Validation / kor_free** 를 쓴다.

| 평가 세트 | 구성 | 목록 |
|---|---|---|
| `age_400` | 7·8·9·10세 각 100개 (seed 42 무작위 추출) | [`stt_eval/eval_sets/age_400.csv`](../../stt_eval/eval_sets/age_400.csv) |
| `hard_100` | `age_400` 중 기존 상용 STT(CLOVA)가 틀린 문장을 연령별 CER 상위 25개씩 | [`stt_eval/eval_sets/hard_100.csv`](../../stt_eval/eval_sets/hard_100.csv) |

- 목록에는 파일 이름과 나이만 있다. AI-Hub 약관상 음성과 정답 전사문은 저장소에 올리지 않고, 각자 내려받은 원본에서 읽는다.
- 결과 CSV 에도 정답 전사문은 싣지 않는다.

## 3. 평가 지표

| 지표 | 설명 |
|---|---|
| Normalized CER | 띄어쓰기·문장부호를 지우고 한글 소수("삼 점 오")·단위 표기를 통일한 뒤의 글자 오류율 |
| 문장 평균 / Corpus | 문장별 CER 의 평균 / 전체 편집 거리 ÷ 전체 정답 글자 수 |
| 정확 일치 | 정규화 후 정답과 완전히 같은 문장 |
| Semantic | `jhgan/ko-sroberta-multitask` 임베딩 유사도. 0.85 이상이고 부정어·숫자 차이가 없으면 MATCH, 0.70 미만 MISMATCH, 그 사이 REVIEW |
| 처리 시간 | 문장 1개 인식 시간 (디코딩 포함) |

정의는 [`stt_eval/metrics.py`](../../stt_eval/metrics.py). 선정 실험 때 쓴 함수와 500개 문장 전부에서 같은 값이 나오는 것을 확인했다.

## 4. 결과 (Qwen3-ASR 1.7B)

`stt_eval/evaluate.py` 로 다시 돌린 결과다. 선정 실험 때의 수치와 문장 단위까지 같게 재현됐다.
Apple Silicon(MPS), bfloat16 기준이다.

**age_400 (7~10세 각 100개)**

| 나이 | 문장 평균 CER | Corpus CER | 정확 일치 | Semantic MATCH / REVIEW / MISMATCH | 처리 시간 중간값 |
|---|---|---|---|---|---|
| **전체** | **4.53%** | **4.44%** | **265 / 400** | **358 / 31 / 11** | **1.72초** |
| 7세 | 5.42% | 4.64% | 60 | 87 / 11 / 2 | 1.79초 |
| 8세 | 4.45% | 4.97% | 68 | 90 / 5 / 5 | 1.60초 |
| 9세 | 4.12% | 3.84% | 71 | 93 / 5 / 2 | 1.39초 |
| 10세 | 4.13% | 4.27% | 66 | 88 / 10 / 2 | 1.84초 |

**hard_100 (어려운 문장)**

| 나이 | 문장 평균 CER | Corpus CER | 정확 일치 | Semantic MATCH / REVIEW / MISMATCH |
|---|---|---|---|---|
| **전체** | **8.03%** | **7.54%** | **46 / 100** | **78 / 18 / 4** |
| 7세 | 6.66% | 6.49% | 11 | 18 / 7 / 0 |
| 8세 | 8.76% | 7.79% | 12 | 21 / 3 / 1 |
| 9세 | 6.44% | 5.66% | 14 | 23 / 1 / 1 |
| 10세 | 10.27% | 9.82% | 9 | 16 / 7 / 2 |

- 처리 시간은 최소 0.56초, 최대 4.48초다.
- 같은 hard_100 에서 기존 상용 STT(CLOVA)는 문장 평균 CER 32.67%, 정확 일치 0개였다.
- 의미가 틀린 문장(MISMATCH)은 주로 고유명사·드문 단어 오인식이다(예: 고로케 → 코르케). 일부는 출력이 잘리거나 깨졌다(예: 할머니! 어서 오세요 → 해머니어 C U C U).
- 문장별 결과: [`stt_eval/results/`](../../stt_eval/results/)

## 5. 백엔드 연동 형식 검증

백엔드가 보내는 것과 같은 WebM(Opus) 음성을 [AI_HANDOFF](../api/AI_HANDOFF.md) 1장 형식(`POST /internal/ai/turns`, multipart `metadata` JSON + `audio`)으로 보내 확인했다.

`stt_eval/be_format_check.py --limit-per-age 25` (age_400 의 나이별 앞 25개, 총 100개):

| 항목 | 결과 |
|---|---|
| 명세 형식 검증 통과 | **100 / 100** |
| 응답 status | SUCCEEDED 100 |
| STT 문장 평균 CER (WebM 입력) | **2.97%** (정확 일치 73) |
| 같은 100개를 WAV 로 넣었을 때 | 3.15% (정확 일치 74) |
| B안 오디오 다운로드 (`GET /internal/ai/audio/{ref}`) | 100 / 100 성공 |
| 요청 1건 처리 시간 | 중간값 1.98초, 최대 9.21초 (첫 요청의 준비 시간 포함) |

- WebM(Opus) 압축을 거쳐도 STT 정확도는 떨어지지 않았다.
- 검사 항목: 응답 필드 구성, 식별자 3개 반환, `visibility` 와 `text`·허용값 일치, `tts` 필드(`expiresAt` 시간대 포함), 실패 시 `error`·`expressionCode` 규칙.
- 이 검증에서 LLM 은 고정 답변, TTS 는 가짜 엔진을 썼다. 대상은 STT 와 응답 형식이다.

## 6. 재현 방법

### 6.1 준비

```bash
# Python 3.12
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-stt.txt
```

- AI-Hub `011.한국어 아동 음성 데이터` Validation 원천·라벨링 데이터를 내려받아 압축을 푼다.
- 기본 위치는 저장소 상위 폴더(`~/Desktop/DodamDodam`)다. 다른 곳이면 `AIHUB_CHILD_SPEECH_ROOT` 로 지정한다.

```
$AIHUB_CHILD_SPEECH_ROOT/
├── 011.한국어_아동_음성_데이터_원천/01.데이터/2.Validation/원천데이터/kor_free/...
└── 011.한국어_아동_음성_데이터_라벨링/01.데이터/2.Validation/라벨링데이터/kor_free/...
```

- 모델(`Qwen/Qwen3-ASR-1.7B`, 약 4.4GB)과 Semantic 모델은 첫 실행 때 Hugging Face 에서 자동으로 받는다.

### 6.2 STT 정확도 평가

```bash
.venv/bin/python -m stt_eval.evaluate --set age_400
.venv/bin/python -m stt_eval.evaluate --set hard_100
# 빠른 확인: 나이별 5개씩
.venv/bin/python -m stt_eval.evaluate --set age_400 --limit-per-age 5
```

결과는 `stt_eval/results/qwen3-asr-1.7b_<세트>.csv`(문장별)와 `_summary.txt`(요약)에 남는다.
중간에 멈춰도 다시 실행하면 이어서 돈다. 처음부터 다시 하려면 CSV 를 지운다.

### 6.3 백엔드 연동 형식 검증

```bash
.venv/bin/python -m stt_eval.be_format_check                  # 나이별 5개씩
.venv/bin/python -m stt_eval.be_format_check --limit-per-age 25
```

`GEMINI_API_KEY` 가 있으면 LLM 답변도 Gemini 로 만든다. 없으면 고정 답변을 쓴다. 결과는 `stt_eval/results/be_format_check.txt`.

### 6.4 서버 실행

```bash
.venv/bin/uvicorn api.server:app --port 8000
```

`GEMINI_API_KEY` 가 필요하다. 서버 간 인증은 `AI_SERVER_TOKEN` 으로 켠다.

## 7. 알려진 한계

- 평가 데이터는 조용한 곳에서 또박또박 읽은 문장이다. 생활 소음·즉흥 발화가 섞인 실제 녹음에서는 정확도가 떨어질 수 있다.
- AI-Hub 는 공개 데이터라 모델 학습에 포함됐을 가능성이 있다.
- 무음 입력에도 "그렇죠." 같은 문장을 만들어 낸다. 무음·잘못 누름은 STT 전에 걸러야 한다.
- 처리 시간은 Apple Silicon(MPS) 기준이다. 배포 서버(GPU)에서 다시 재야 한다.
