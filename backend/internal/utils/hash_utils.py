import hashlib


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def fingerprint(title: str, url: str) -> str:
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class DedupSet:
    def __init__(self):
        self._seen = set()

    def add(self, key: str) -> bool:
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    def contains(self, key: str) -> bool:
        return key in self._seen
