from typing import Protocol


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dims: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
