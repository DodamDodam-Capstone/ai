"""Run the trained model1 v0.3 locally. Model files are downloaded separately."""
import argparse
import importlib.util
import json
import os
from pathlib import Path


def load_predictor(model_dir, device_name):
    model_dir = model_dir.expanduser().resolve()
    required = ["config.json", "model.safetensors", "tokenizer.json",
                "tokenizer_config.json", "emotion_metadata.json", "preprocessing.py"]
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"모델 폴더: {model_dir}\n누락 파일: {', '.join(missing)}")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    meta = json.loads((model_dir / "emotion_metadata.json").read_text(encoding="utf-8"))
    if meta.get("schema_version") != "model1-v0.3" or meta.get("num_labels") != 6:
        raise ValueError("model1 v0.3의 모델 폴더를 선택하세요.")
    classes = meta["classes"]
    if classes != [f"C{i}" for i in range(6)]:
        raise ValueError("저장된 클래스 순서가 예상과 다릅니다.")
    if device_name == "auto":
        device_name = "cuda" if torch.cuda.is_available() else "cpu"
    if device_name == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA를 사용할 수 없습니다. --device cpu로 실행하세요.")
    device = torch.device(device_name)
    spec = importlib.util.spec_from_file_location("model1_saved_preprocess", model_dir / "preprocessing.py")
    preprocess = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preprocess)
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False, use_safetensors=True
    ).to(device).eval()
    if [model.config.id2label[i] for i in range(6)] != classes:
        raise ValueError("모델 출력 순서와 저장 설정이 다릅니다.")
    threshold = float(meta["review_threshold"])
    if not 0 <= threshold <= 1:
        raise ValueError("저장된 검토 기준을 확인하세요.")

    @torch.inference_mode()
    def predict(text):
        cleaned = preprocess.prepare_inference_text(text)
        inputs = tokenizer(cleaned, return_tensors="pt", truncation=True,
                           max_length=int(meta["max_length"])).to(device)
        scores = model(**inputs).logits[0].float().softmax(-1).cpu().tolist()
        index = max(range(6), key=scores.__getitem__)
        code = classes[index]
        return {
            "문장": text, "모델 입력": cleaned, "예측 코드": code,
            "예측 감정": meta["class_names"][code], "모델 점수": scores[index],
            "최종 판정": meta["class_names"][code] if scores[index] >= threshold else "검토 필요",
            "검토 기준": threshold,
            "범주별 점수": {f"{c} {meta['class_names'][c]}": scores[i] for i, c in enumerate(classes)},
        }

    print(f"모델 로드 완료 | 장치: {device} | 검토 기준: {threshold}")
    return predict


def main():
    parser = argparse.ArgumentParser(description="학습된 아동 발화 감정 모델을 로컬에서 실행합니다.")
    parser.add_argument("--model-dir", type=Path, default=Path(__file__).resolve().parent / "model")
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    parser.add_argument("--text", help="한 문장만 예측하고 종료")
    args = parser.parse_args()
    try:
        predict = load_predictor(args.model_dir, args.device)
    except (ImportError, OSError, ValueError) as exc:
        parser.exit(1, f"실행 준비 실패: {exc}\n")
    if args.text is not None:
        try:
            print(json.dumps(predict(args.text), ensure_ascii=False, indent=2))
        except ValueError as exc:
            parser.exit(1, f"입력 오류: {exc}\n")
        return
    print("문장을 한 줄씩 입력하세요. 종료: /quit")
    while True:
        try:
            sentence = input("\n문장> ")
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break
        if sentence.strip() == "/quit":
            break
        if not sentence.strip():
            continue
        try:
            print(json.dumps(predict(sentence), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"입력 오류: {exc}")


if __name__ == "__main__":
    main()
