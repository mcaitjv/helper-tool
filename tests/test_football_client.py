import logging

import httpx
import pytest

from helper.football.client import FootballClient, FootballError

KEY = "secretkey123"


class Harness:
    """A fake API plus a fake clock, so nothing really waits."""

    def __init__(self, *responses, key=KEY, **kw):
        self.responses, self.requests, self.slept, self.time = list(responses), [], [], 0.0
        self.client = FootballClient(key, transport=httpx.MockTransport(self.handle),
                                     now=lambda: self.time, sleep=self.sleep, **kw)

    def handle(self, request):
        self.requests.append(request)
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.time += seconds


def ok(**headers):
    return httpx.Response(200, json={"n": 1}, headers=headers)


def error(status, message="", **headers):
    return httpx.Response(status, json={"message": message}, headers=headers)


async def test_key_goes_in_the_header_over_https_only():
    h = Harness(ok())
    await h.client.get("/x", {"limit": 3}, ttl=10)
    request = h.requests[0]
    assert request.headers["X-Auth-Token"] == KEY
    assert str(request.url) == "https://api.football-data.org/v4/x?limit=3"


async def test_cache_until_ttl_and_per_params():
    h = Harness(ok(), ok(), ok())
    first = await h.client.get("/x", ttl=10)
    assert await h.client.get("/x", ttl=10) is first   # cached, same fetch time
    await h.client.get("/x", {"a": 1}, ttl=10)         # other params: new request
    h.time = 11
    await h.client.get("/x", ttl=10)                   # expired: new request
    assert len(h.requests) == 3


async def test_errors_are_not_cached():
    h = Harness(error(500), ok())
    with pytest.raises(FootballError):
        await h.client.get("/x", ttl=10)
    assert (await h.client.get("/x", ttl=10)).data == {"n": 1}


async def test_waits_when_the_header_says_nothing_is_left():
    h = Harness(ok(**{"x-requests-available-minute": "0", "x-requestcounter-reset": "7"}), ok())
    await h.client.get("/a", ttl=10)
    await h.client.get("/b", ttl=10)
    assert h.slept == [7]


async def test_long_wait_is_reported_instead():
    h = Harness(ok(**{"x-requests-available-minute": "0", "x-requestcounter-reset": "40"}))
    await h.client.get("/a", ttl=10)
    with pytest.raises(FootballError, match="40 seconds"):
        await h.client.get("/b", ttl=10)
    assert h.slept == [] and len(h.requests) == 1


async def test_caller_may_accept_a_longer_wait():
    h = Harness(ok(**{"x-requests-available-minute": "0", "x-requestcounter-reset": "40"}), ok())
    await h.client.get("/a", ttl=10)
    await h.client.get("/b", ttl=10, max_wait=65)
    assert h.slept == [40]


async def test_429_waits_and_retries_once():
    h = Harness(error(429, **{"x-requestcounter-reset": "5"}), ok())
    assert (await h.client.get("/x", ttl=10)).data == {"n": 1}
    assert h.slept == [5]


async def test_429_twice_gives_up():
    h = Harness(*[error(429, **{"x-requestcounter-reset": "5"})] * 2)
    with pytest.raises(FootballError, match="limit"):
        await h.client.get("/x", ttl=10)
    assert len(h.requests) == 2


@pytest.mark.parametrize("response, word", [
    (error(400, "Your API token is invalid."), "API key"),
    (error(400, "Specified period must not exceed 10 days."), "10 days"),
    (error(403), "free"),
    (error(404), "no such data"),
    (error(500), "500"),
    (httpx.Response(200, text="<html>"), "unexpected"),
    (httpx.Response(302, headers={"location": "https://evil.example/"}), "302"),
    (httpx.ReadTimeout("t"), "too long"),
    (httpx.ConnectError("c"), "internet"),
])
async def test_clear_errors(response, word):
    h = Harness(response)
    with pytest.raises(FootballError, match=word):
        await h.client.get("/x", ttl=10)
    assert len(h.requests) == 1   # a redirect is never followed


@pytest.mark.parametrize("key", ["", "bad\nkey", "kéy"])
async def test_bad_key_is_never_sent(key):
    h = Harness(key=key)
    with pytest.raises(FootballError, match="missing or malformed"):
        await h.client.get("/x", ttl=10)
    assert h.requests == []


async def test_key_is_not_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    for response in (error(400, "Your API token is invalid."), error(403), httpx.ConnectError("c")):
        with pytest.raises(FootballError) as e:
            await Harness(response).client.get("/x", ttl=10)
        assert KEY not in repr(e.value)
    assert KEY not in caplog.text
    assert KEY not in repr(FootballClient(KEY))
