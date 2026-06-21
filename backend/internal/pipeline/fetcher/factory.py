from .bilibili import BilibiliFetcher
from .github import GitHubFetcher
from .rss import RSSFetcher


class FetcherFactory:
    _registry = {
        "bilibili": BilibiliFetcher,
        "github": GitHubFetcher,
        "rss": RSSFetcher,
    }

    @classmethod
    def get(cls, source_type: str):
        if source_type not in cls._registry:
            raise ValueError(f"Unknown source_type: {source_type}")
        return cls._registry[source_type]()

    @classmethod
    def register(cls, source_type: str, fetcher_cls):
        cls._registry[source_type] = fetcher_cls
