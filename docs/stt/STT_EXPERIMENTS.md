# STT 모델 비교 실험 결과 (SCRUM-120)

- Jira: [SCRUM-120 [AI] STT](https://dodamdodam.atlassian.net/browse/SCRUM-120) (상위: SCRUM-51 [AI] 음성 AI 대화)
- 목적: 7~10세 아동 음성에 가장 적합한 STT 엔진 선정
- 비교 대상: CLOVA Speech, Whisper turbo, Qwen3-ASR(1.7B / 0.6B / 0.6B-4bit), CLOVA + Llama 후처리

## 1. 데이터셋

AI-Hub `011.한국어 아동 음성 데이터`의 **Validation / kor_free** 세트를 사용했다.

| 세트 | 구성 | 생성 방법 | 사용 실험 |
|---|---|---|---|
| 초기 1000개 | 1000개 (연령 구분 없음) | - | CLOVA 초기 평가 |
| 연령별 400개 | 7·8·9·10세 각 100개 (seed 42) | `make_age_samples.py` | CLOVA, Qwen3-ASR |
| 연령별 100개 | 7·8·9·10세 각 25개 | - | CLOVA, Whisper, Llama 후처리 |
| Hard test 100개 | 400개 중 CLOVA 오답을 연령별 CER 상위 25개씩 | `make_hard_test_set.py` | Qwen3-ASR |

- 연령별 100개 세트는 CLOVA·Whisper·Llama 실험에서 **동일한 100개 샘플**을 사용했다.
- manifest CSV(`stt_age_*_manifest.csv`, `hard_test_100.csv`)는 로컬 절대경로가 포함되어 저장소에 올리지 않았다. 위 스크립트로 재생성한다.
- 나이별 데이터 분포는 `check_age_distribution.py`로 확인했다.

## 2. 평가 지표

| 지표 | 설명 |
|---|---|
| Raw CER | 원문 그대로 비교한 글자 오류율 |
| Normalized CER | 띄어쓰기·문장부호·숫자 표기를 정규화한 뒤 비교한 글자 오류율 |
| 문장 평균 CER / Corpus CER | 문장별 CER의 평균 / 전체 글자 기준 CER |
| 정확 일치 | 정규화 후 정답과 완전히 같은 문장 수 |
| Semantic 유사도 | `jhgan/ko-sroberta-multitask` 임베딩 유사도. 0.85 이상 MATCH, 0.70 이상 REVIEW, 미만 MISMATCH |
| 처리 시간 | 문장 1개당 평균 인식 시간 |

CLOVA·Qwen3-ASR 평가는 `smoke_stt_batch.py`의 동일한 정규화·CER·Semantic 함수를 사용해 같은 기준으로 비교했다.

## 3. 실험별 결과

### 3.1 CLOVA 초기 평가 (1000개)

| 평균 CER | 완전 일치 | CER ≤ 5% | CER > 20% | 평균 처리 시간 |
|---|---|---|---|---|
| 10.40% | 407 / 1000 | 468 | 181 | 1.05초 |

- 결과: [`logs/stt_child_validation_summary.txt`](../../logs/stt_child_validation_summary.txt)

### 3.2 CLOVA 연령별 평가

**400개**

| 나이 | Normalized CER | 문장 평균 CER | Semantic | MATCH 비율 |
|---|---|---|---|---|
| 7세 | 11.55% | 11.97% | 0.886 | 70% |
| 8세 | 14.33% | 12.69% | 0.865 | 63% |
| 9세 | 10.93% | 9.40% | 0.911 | 75% |
| 10세 | 12.25% | 12.26% | 0.881 | 70% |
| **전체** | **12.31%** (Corpus) | **11.58%** | **0.886** | 정확 일치 166 / 400 |

**100개**: Corpus Normalized CER 13.45%, 정확 일치 35 / 100

- 결과: [`logs/stt_age_400_summary.txt`](../../logs/stt_age_400_summary.txt), [`logs/stt_age_100_summary.txt`](../../logs/stt_age_100_summary.txt)

### 3.3 Whisper turbo (연령별 100개)

| 지표 | Whisper | CLOVA (동일 100개) |
|---|---|---|
| Normalized Corpus CER | **6.48%** | 13.45% |
| 정확 일치 | **53 / 100** | 35 / 100 |
| Semantic 평균 | 0.904 | - |
| 평균 처리 시간 | 4.07초 | - |

- CLOVA보다 정확도는 높지만 처리 시간이 길다 (로컬 실행 기준).
- 결과: [`logs/whisper_age_100_summary.txt`](../../logs/whisper_age_100_summary.txt)

### 3.4 Qwen3-ASR (연령별 400개 / Hard test 100개)

**연령별 400개 (CLOVA와 동일 샘플)**

| 모델 | 문장 평균 CER | 정확 일치 | Semantic | CLOVA 대비 개선 / 악화 | 평균 처리 시간 |
|---|---|---|---|---|---|
| CLOVA | 11.58% | 166 | 0.886 | - | - |
| Qwen3-ASR 1.7B | **4.53%** | **265** | **0.959** | 196 / 40 | 1.80초 |
| Qwen3-ASR 0.6B | 7.68% | 202 | 0.920 | 171 / 87 | 0.98초 |
| Qwen3-ASR 0.6B-4bit (MLX) | 10.81% | 150 | 0.886 | 144 / 133 | **0.42초** |

**Hard test 100개 (CLOVA가 틀린 문장)**

| 모델 | 문장 평균 Normalized CER | 정확 일치 | Semantic |
|---|---|---|---|
| CLOVA | 32.67% | 0 | - |
| Qwen3-ASR 1.7B | **8.03%** | **46** | **0.924** |
| Qwen3-ASR 0.6B | 12.69% | 30 | 0.869 |
| Qwen3-ASR 0.6B-4bit | 17.47% | 19 | 0.831 |

- 1.7B·0.6B는 Apple MPS, 0.6B-4bit는 MLX로 로컬 실행했다.
- 결과: `logs/qwen3_asr_*_summary.txt` (1.7B는 `qwen3_asr_*`, 0.6B는 `qwen3_asr_0.6b_*`, 4bit는 `qwen3_asr_0.6b_4bit_*`)

### 3.5 CLOVA + Llama 3.1 8B 후처리 (연령별 100개)

| 지표 | CLOVA | CLOVA + Llama |
|---|---|---|
| Corpus CER | **13.44%** | 21.06% |
| 정확 일치 | **35** | 15 |
| 문장별 변화 | - | 개선 4 / 동일 39 / 악화 57 |

- Llama가 이미 정답인 CLOVA 문장 21개를 불필요하게 수정했다 (불필요 수정률 60%).
- 모든 STT 결과에 LLM 후처리를 일괄 적용하는 방식은 정확도를 떨어뜨린다.
- 결과: [`logs/stt_age_100_llama_summary.txt`](../../logs/stt_age_100_llama_summary.txt)

## 4. 종합 비교 및 결론

| 모델 | 정확도 (CLOVA 대비) | 속도 | 비고 |
|---|---|---|---|
| CLOVA | 기준 | 빠름 (약 1초) | 외부 API, 비용 발생 |
| Whisper turbo | 높음 | 느림 (4.07초) | 로컬 실행 |
| Qwen3-ASR 1.7B | **가장 높음** | 보통 (1.80초) | 로컬 실행, hard test에서도 가장 강함 |
| Qwen3-ASR 0.6B | 높음 | 빠름 (0.98초) | 정확도·속도 균형 |
| Qwen3-ASR 0.6B-4bit | CLOVA와 비슷 | 가장 빠름 (0.42초) | 경량화로 정확도 손실 큼 |
| CLOVA + Llama | 낮아짐 | - | 일괄 후처리는 비권장 |

- 아동 음성 인식 정확도는 **Qwen3-ASR 1.7B**가 모든 세트에서 가장 높았다.
- 응답 속도가 중요하면 **Qwen3-ASR 0.6B**가 대안이다.
- 4bit 양자화와 LLM 일괄 후처리는 정확도 손실이 커서 제외한다.
- **최종 선정 모델: TODO (팀 결정 후 기입)**

## 5. 재현 방법

```bash
# 1) 평가 세트 생성
python make_age_samples.py            # stt_age_400_manifest.csv
python smoke_stt_batch.py             # CLOVA 400개 평가 (.env에 CLOVA 키 필요)
python make_hard_test_set.py          # hard_test_100.csv

# 2) 모델별 평가
python evaluate_whisper_100.py
.venv/bin/python evaluate_qwen_400.py                     # Qwen3-ASR 1.7B
QWEN_ASR_MODEL=Qwen/Qwen3-ASR-0.6B .venv/bin/python evaluate_qwen_400.py
QWEN_ASR_MODEL=mlx-community/Qwen3-ASR-0.6B-4bit .venv-mlx/bin/python evaluate_qwen_400.py
# hard test는 evaluate_qwen_hard_set.py를 같은 방식으로 실행
python evaluate_llama_postprocess_100.py                  # 로컬 Ollama llama3.1:8b 필요

# 3) 요약 생성
python logs/summarize_stt_results.py
python logs/summarize_llama_postprocess.py
```

추가 의존성(`requirements.txt`에 미포함): `sentence-transformers`, `openai-whisper`, `torch`, `qwen-asr`, `mlx-audio`(4bit, 별도 `.venv-mlx`), `ollama`

> ⚠️ `smoke_stt_batch.py`는 SCRUM-15에서 수정한 `stt/clova.py` 호출 방식을 기준으로 작성되었다.
