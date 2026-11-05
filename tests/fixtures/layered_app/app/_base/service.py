"""Shared base class for services."""

import logging

from app.repos.repository_factory import AllRepositories


class BaseService:
    """Gives every service a logger and the injected repositories."""

    def __init__(self, repos: AllRepositories) -> None:
        self.repos = repos
        self.logger = logging.getLogger(type(self).__name__)
