import re
import unicodedata

def strip_tags(text):
    text = str(text)
    pattern = r'\((?:SP|NO|SN|FP):([^()]*)\)'
    while re.search(pattern, text):
        text = re.sub(pattern, r'\1', text)
    return text


def sentence_key(text):
    return ''.join(c for c in strip_tags(text) if not c.isspace() and not unicodedata.category(c).startswith('P'))


def normalize_model_text(text):
    text = strip_tags(text)
    text = ''.join(' ' if c.isspace() else c for c in text if c.isspace() or unicodedata.category(c) not in ('Cc','Cf'))
    return re.sub(r'\s+', ' ', text).strip()


def model_text_exclusion(text):
    if not text or not sentence_key(text):return 'empty_text'
    if re.search(r'\((?:SP|NO|SN|FP):',text):return 'malformed_tag'
    return None


def prepare_inference_text(text):
    if not isinstance(text,str):raise ValueError('문자열을 입력하세요.')
    cleaned=normalize_model_text(text)
    reason=model_text_exclusion(cleaned)
    if reason:raise ValueError(f'예측할 수 없는 발화입니다: {reason}')
    return cleaned
