# 주제 분석 (Theme Classifier, P0)

세션 종료 후 아이–AI 대화 전체를 LLM 1회로 분석해 topic 목록(category·topic·sentiment·key_point·turn_ids)을 만들고, 검증한 뒤 `session_topics`에 저장한다. 학습·파인튜닝 없이 프롬프트로 분류한다.

| 파일 | 역할 |
|---|---|
| `schema.py` | Category 10 / Sentiment 5 Enum, 출력 스키마 |
| `prompt.py` | 시스템 프롬프트와 few-shot 예시 |
| `llm_client.py` | Gemini / OpenAI 호환(자체 서버·vLLM) / Ollama / Mock 어댑터 |
| `validator.py` | 스키마·Enum·turn_id·아동 발화 근거·짧은 동의·개인정보 검사 |
| `pipeline.py` | 조회 → LLM → 검증 → 재시도(최대 3회) → 저장, 작업 상태 기록 |
| `repo_sqlite.py` | 로컬용 DB (운영에선 백엔드 DB/API로 교체) |
| `api.py` | 백엔드가 호출할 FastAPI 엔드포인트 (예시) |
| `eval.py` | Category 정확도(엄격·허용 대안) · Topic F1 · 환각률 |
| `run_eval.py` | 평가셋 전체를 한 모델로 돌리고 점수 저장 |
| `first_call.py` | 실제 Gemini 첫 호출 확인용 |
| `guidelines/` | category·topic 판정 기준서(v1.2), 팀 요청 초안 |
| `eval_data/eval_set.json` | 개발셋 30세션 (지어낸 대화, 실제 아동 데이터 아님) |
| `labeling/` | 재라벨링 양식 생성, 두 라벨러 비교·kappa |

테스트는 `tests/test_topic_pipeline.py` (Mock LLM, API 키 불필요).

## 실행 (저장소 루트에서)

    python -m pytest tests/test_topic_pipeline.py          # API 키 불필요

    # .env에 GEMINI_API_KEY (필요하면 GEMINI_MODEL)
    python -m topic.run_eval gemini gemini-3.5-flash
    python -m topic.run_eval ollama qwen3:8b               # ollama serve + ollama pull qwen3:8b 필요

    pip install fastapi uvicorn
    uvicorn topic.api:app --port 8001

## 재라벨링

    python topic/labeling/make_label_form.py
    # label_template.csv를 라벨러마다 복사해 채운다 (기준서만 보고, 정답·모델 결과는 보지 않음)
    python topic/labeling/compare_labels.py labels_A.csv labels_B.csv --out compare.md

## 데이터 주의

- 외부 API(Gemini)에는 지어낸 대화만 보낸다. 실제 아동 대화는 보내지 않는다.
- 시험셋은 공개 저장소에 올리지 않는다 (평가 오염 방지).
- 평가 결과(`topic/results/`)와 로컬 DB(`*.db`)는 git에 올리지 않는다.
