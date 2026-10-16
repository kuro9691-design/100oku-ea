from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Iterator, Sequence, TypeVar

T = TypeVar("T")


class FutureLeakError(RuntimeError):
    pass


@dataclass
class AccessAudit:
    decision_index: int
    access_count: int = 0
    max_accessed: int = -1

    def record(self, index: int) -> None:
        if index > self.decision_index:
            raise FutureLeakError(
                f"future index {index} accessed while deciding at {self.decision_index}"
            )
        self.access_count += 1
        self.max_accessed = max(self.max_accessed, index)

    def assert_clean(self) -> None:
        if self.max_accessed > self.decision_index:
            raise FutureLeakError(f"future index accessed: {self.max_accessed}")


class CausalSeries(Generic[T]):
    def __init__(self, values: Sequence[T], decision_index: int, audit: AccessAudit):
        self._values = values
        self.decision_index = decision_index
        self.audit = audit

    def __len__(self) -> int:
        return self.decision_index + 1

    def __getitem__(self, index: int | slice) -> T | list[T]:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return [self[i] for i in range(start, stop, step)]
        resolved = index if index >= 0 else len(self) + index
        if resolved < 0 or resolved >= len(self):
            raise IndexError(index)
        self.audit.record(resolved)
        return self._values[resolved]

    def __iter__(self) -> Iterator[T]:
        for index in range(len(self)):
            yield self[index]

    def raw_prefix(self) -> Sequence[T]:
        for index in range(len(self)):
            self.audit.record(index)
        return self._values[: len(self)]
