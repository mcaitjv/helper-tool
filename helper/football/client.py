"""HTTP client for football-data.org: key, cache, rate limit and clear errors."""
import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from helper.tools.registry import ToolError

BASE_URL = "https://api.football-data.org/v4"


class FootballError(ToolError):
    """A football API problem, worded so the model can explain it."""


class NotFound(FootballError):
    """The API has nothing at this address (404)."""


class NotAllowed(FootballError):
    """The plan does not include this (403)."""


@dataclass(frozen=True)
class Fetched:
    data: dict
    at: datetime  # when it left the API (a cached answer keeps its old time)


class FootballClient:
    def __init__(
        self,
        key: str,
        *,
        max_wait: float = 15,  # longest we keep the user waiting for the rate limit
        transport: httpx.AsyncBaseTransport | None = None,  # tests plug in a fake
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._key = key
        self._max_wait = max_wait
        self._transport = transport
        self._now = now
        self._sleep = sleep
        self._blocked_until = 0.0
        self._cache: dict[tuple, tuple[float, Fetched]] = {}

    async def get(
        self, path: str, params: dict | None = None, *, ttl: float, max_wait: float | None = None
    ) -> Fetched:
        """GET a path. An answer younger than `ttl` seconds comes from the cache."""
        cache_key = (path, tuple(sorted((params or {}).items())))
        hit = self._cache.get(cache_key)
        if hit and self._now() < hit[0]:
            return hit[1]

        # Checked here so a malformed key never reaches a header or a traceback.
        if not (self._key.isascii() and self._key.isalnum()):
            raise FootballError("the football API key is missing or malformed in .env.")

        max_wait = self._max_wait if max_wait is None else max_wait
        await self._wait_for_limit(max_wait)
        response = await self._send(path, params)
        if response.status_code == 429:  # too many requests: wait and retry once
            self._blocked_until = self._now() + self._reset_seconds(response)
            await self._wait_for_limit(max_wait)
            response = await self._send(path, params)
        data = self._read(response)

        fetched = Fetched(data, datetime.now().astimezone())
        self._drop_expired()
        self._cache[cache_key] = (self._now() + ttl, fetched)
        return fetched

    async def _send(self, path: str, params: dict | None) -> httpx.Response:
        try:
            # Redirects stay off, so the key is never sent to another address.
            async with httpx.AsyncClient(transport=self._transport, timeout=20) as http:
                response = await http.get(
                    BASE_URL + path, params=params, headers={"X-Auth-Token": self._key}
                )
        except httpx.TimeoutException:
            raise FootballError("football-data.org took too long to answer.") from None
        except httpx.HTTPError:
            raise FootballError("can't reach football-data.org. Is the internet on?") from None

        # The API tells us how many requests are left in this minute.
        if response.headers.get("x-requests-available-minute") == "0":
            self._blocked_until = self._now() + self._reset_seconds(response)
        return response

    async def _wait_for_limit(self, max_wait: float) -> None:
        wait = self._blocked_until - self._now()
        if wait <= 0:
            return
        if wait > max_wait:
            raise FootballError(
                f"the football API limit (10 requests a minute) is used up. "
                f"Try again in {wait:.0f} seconds."
            )
        await self._sleep(wait)

    @staticmethod
    def _reset_seconds(response: httpx.Response) -> float:
        try:
            return float(response.headers["x-requestcounter-reset"])
        except (KeyError, ValueError):
            return 60.0

    def _read(self, response: httpx.Response) -> dict:
        status = response.status_code
        try:
            data = response.json()
        except ValueError:
            data = None
        if status == 200 and isinstance(data, dict):
            return data

        message = str(data.get("message", "")) if isinstance(data, dict) else ""
        if status == 400 and "token" in message.lower():  # what a wrong key really returns
            raise FootballError("football-data.org rejected the API key. Check .env.")
        if status == 400:
            raise FootballError(f"football-data.org refused the request: {message[:200]}")
        if status == 403:
            raise NotAllowed("this data is not included in the free football-data.org plan.")
        if status == 404:
            raise NotFound("football-data.org has no such data.")
        if status == 429:
            raise FootballError("the football API limit is used up. Try again in a minute.")
        raise FootballError(f"football-data.org gave an unexpected answer (status {status}).")

    def _drop_expired(self) -> None:
        now = self._now()
        self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
