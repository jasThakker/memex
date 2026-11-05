"""A transport that pretends to speak HTTP."""

from .base import Transport


class HttpTransport(Transport):
    def send(self, payload: str) -> int:
        return len(payload.encode())
