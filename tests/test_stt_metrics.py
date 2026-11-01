"""STT 평가 지표 정의 (stt_eval/metrics.py). 바뀌면 SCRUM-120 결과와 비교할 수 없게 된다."""

from __future__ import annotations

from stt_eval.metrics import cer, normalize, normalize_basic, semantic_flags


def test_normalize_ignores_spacing_and_punctuation():
    assert normalize("아빠는 자상하십니다.") == normalize("아빠는자상하십니다")
    assert normalize_basic("가을 하늘은, 맑고!") == "가을하늘은맑고"


def test_normalize_unifies_korean_decimal_and_units():
    assert normalize("삼 점 오 킬로미터") == normalize("3.5km")


def test_cer_counts_character_edits():
    # 자 -> 사 한 글자 / 9글자
    rate, distance, chars = cer(normalize("아빠는 자상하십니다."), normalize("아빠는 사상하십니다."))
    assert (distance, chars) == (1, 9)
    assert abs(rate - 1 / 9) < 1e-9


def test_cer_empty_reference():
    assert cer("", "") == (0.0, 0, 0)
    assert cer("", "그렇죠") == (1.0, 3, 0)


def test_semantic_flags_negation_and_numbers():
    assert semantic_flags("나는 안 갈래", "나는 갈래") == ["negation_mismatch"]
    assert semantic_flags("사과 3개", "사과 4개") == ["number_mismatch"]
    assert semantic_flags("사과 3개", "사과 3개") == []
