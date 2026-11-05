"""A client that sends text over a transport."""

from toolkit._transport.http import HttpTransport
from toolkit.text.slug import slugify


class Client:
    def __init__(self) -> None:
        self.transport = HttpTransport()

    def send(self, title: str) -> int:
        return self.transport.send(slugify(title))
