# 감정 분류기 model1 v0.3

klue/bert-base 를 아동 발화 감정 6범주로 미세조정한 모델이다. 서비스에서는
`emotion/model.py` 의 `BertEmotionClassifier` 가 `models/model/` 을 읽는다.

**저장소에는 가중치가 없다.** `model.safetensors`(약 440MB) 하나만 아래 Google Drive
폴더에서 받아 `models/model/` 에 넣으면 된다. 나머지 파일은 저장소에 들어 있다.
https://drive.google.com/drive/folders/1afljQOL9ZWceixSoUWVL7JNTfGUhV6yI

가중치가 없으면 AI 서버는 규칙 기반 분류기로 내려가고, `tests/test_emotion_model.py` 의
실제 모델 테스트는 건너뛴다. 서버 의존성은 `requirements-stt.txt` 에 있다.

아래는 서비스와 무관하게 모델만 따로 받아 문장을 넣어보는 방법이다.

---

# model1 로컬 문장 확인

Windows, Python 3.12 64비트, CPU 실행 기준입니다. 다시 학습할 필요가 없습니다.

## 1. 모델 다운로드

다음 본인 Google Drive 폴더의 파일 6개를 모두 다운로드합니다.
https://drive.google.com/drive/folders/1afljQOL9ZWceixSoUWVL7JNTfGUhV6yI

압축을 풀고 predict_local.py 옆에 model 폴더를 두세요.

```text
model1_local/
  predict_local.py
  requirements.txt
  model/
    config.json
    model.safetensors
    tokenizer.json
    tokenizer_config.json
    preprocessing.py
    emotion_metadata.json
```

모델 폴더는 약 443MB입니다. 다운로드한 ZIP의 중첩 폴더 때문에 model/model 형태가 되지 않도록 확인하세요. model.safetensors 하나만으로는 실행되지 않습니다.

## 2. 최초 설치

Python 3.12 64비트가 없다면 https://www.python.org/downloads/windows/ 에서 먼저 설치합니다.
이 폴더를 연 뒤 주소창에 powershell을 입력해 터미널을 열고 아래 명령을 한 줄씩 실행합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

별도 가상환경 활성화 명령이나 PowerShell 실행 정책 변경은 필요 없습니다.
Transformers 5.22.1은 실제 Colab 학습 결과에 기록된 버전입니다. PyTorch는 CPU용으로 설치합니다.

## 3. 문장 입력

```powershell
.\.venv\Scripts\python.exe .\predict_local.py
```

문장을 한 줄씩 입력하면 예측 감정, 모델 점수, 최종 판정, 6범주 점수가 나옵니다. /quit을 입력하면 종료합니다. 실행할 때 모델을 한 번 로드한 뒤 여러 문장을 확인할 수 있습니다.

한 문장만 확인하려면:

```powershell
.\.venv\Scripts\python.exe .\predict_local.py --text "내일 발표가 걱정돼."
```

모델을 다른 위치에 저장했다면:

```powershell
.\.venv\Scripts\python.exe .\predict_local.py --model-dir "D:\emotion\model"
```

## 동작 기준

- Google 로그인, Sheets 연결, 재학습이 필요 없습니다.
- 저장된 전처리, 클래스 순서, 최대 길이, 임계값을 그대로 읽습니다.
- 최고 점수 0.95 미만은 검토 필요입니다. 모델 점수는 보정된 정답 확률이 아닙니다.
- 모델과 라이브러리를 설치한 뒤에는 인터넷 연결 없이 실행합니다. 이 스크립트에는 입력 문장을 전송하거나 파일로 기록하는 기능이 없습니다.
- GPU가 없어도 실행됩니다. CUDA를 사용하려면 본인 장치에 맞는 GPU용 PyTorch를 설치한 뒤 --device cuda를 사용합니다.
- CPU와 GPU의 수치 계산 차이로 끝자리 점수가 달라질 수 있습니다.

검증 범위: 학습된 모델의 재로딩과 예측은 Colab에서 확인했습니다. 이 로컬 실행 파일은 문법과 명령행 처리를 확인했으며, 사용자 Windows에서의 전체 모델 실행은 아직 확인하지 않았습니다.

공식 설치 문서:
- https://pytorch.org/get-started/locally/
- https://huggingface.co/docs/transformers/installation
