"""Transport interface."""

from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, payload: str) -> int: ...
