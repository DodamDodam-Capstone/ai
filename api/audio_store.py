"""
TTS 음성 임시 저장소 (오디오 참조 전달, B안).

응답 JSON 에는 음성 대신 audioReference 와 expiresAt 만 싣고, 백엔드가
GET /internal/ai/audio/{ref} 로 가져간다. 프로세스 메모리에 두므로 서버가 재시작되면
사라지고, 서버를 여러 대 띄우면 공유되지 않는다. 그 단계가 오면 오브젝트 스토리지로 바꿀 것.

만료된 참조는 404 가 아니라 410 으로 구분해야 해서, 지운 참조의 키는 따로 잠시 기억한다.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from enum import Enum

# 참조 TTL. 백엔드와 확정 전 임시값. 턴 deadline 보다 길기만 하면 된다.
DEFAULT_TTL_SEC = 600
# 가져가지 않은 음성이 메모리를 채우지 않도록 오래된 것부터 버린다.
DEFAULT_MAX_ITEMS = 500
# 만료 응답(410)을 위해 기억해 두는 지운 참조 수.
MAX_EXPIRED_REFS = 5000


class Lookup(str, Enum):
    FOUND = "found"
    EXPIRED = "expired"
    MISSING = "missing"


class InMemoryAudioStore:
    def __init__(
        self,
        ttl_sec: float = DEFAULT_TTL_SEC,
        max_items: int = DEFAULT_MAX_ITEMS,
        now=lambda: datetime.now(timezone.utc),
    ):
        self.ttl_sec = ttl_sec
        self.max_items = max_items
        self._now = now
        self._items: OrderedDict[str, tuple[datetime, bytes, str]] = OrderedDict()
        self._expired: OrderedDict[str, None] = OrderedDict()

    def put(self, audio: bytes, content_type: str) -> tuple[str, datetime]:
        """음성을 저장하고 (참조 키, 만료 시각) 을 돌려준다."""
        self._evict()
        ref = f"audio-{uuid.uuid4()}"
        expires_at = self._now() + timedelta(seconds=self.ttl_sec)
        self._items[ref] = (expires_at, audio, content_type)
        while len(self._items) > self.max_items:
            old, _ = self._items.popitem(last=False)
            self._remember_expired(old)
        return ref, expires_at

    def get(self, ref: str) -> tuple[Lookup, bytes | None, str | None]:
        """(조회 결과, 음성, content type)."""
        self._evict()
        item = self._items.get(ref)
        if item is not None:
            _, audio, content_type = item
            return Lookup.FOUND, audio, content_type
        if ref in self._expired:
            return Lookup.EXPIRED, None, None
        return Lookup.MISSING, None, None

    def _evict(self) -> None:
        now = self._now()
        for ref in [r for r, (exp, _, _) in self._items.items() if exp <= now]:
            del self._items[ref]
            self._remember_expired(ref)

    def _remember_expired(self, ref: str) -> None:
        self._expired[ref] = None
        while len(self._expired) > MAX_EXPIRED_REFS:
            self._expired.popitem(last=False)
