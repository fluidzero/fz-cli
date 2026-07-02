"""Shared fixtures: CliRunner + a route-table mock of the EV API.

The mock replaces FZClient.request (after auth, retry, and 401-replay would
run), but preserves the >=400 -> handle_api_error contract so commands see
the same exit-code behavior as production.
"""

from __future__ import annotations

import json as json_mod
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
import pytest
from click.testing import CliRunner

from fz_cli.errors import handle_api_error


@dataclass
class Recorded:
    method: str
    path: str
    json: Any
    params: dict | None
    files: Any


@dataclass
class MockApi:
    routes: dict[tuple[str, str], Callable[[Recorded], httpx.Response]] = field(
        default_factory=dict
    )
    requests: list[Recorded] = field(default_factory=list)

    def add(self, method: str, path: str, status: int = 200, json_body=None, headers=None):
        def handler(_req: Recorded) -> httpx.Response:
            return httpx.Response(
                status,
                json=json_body,
                headers=headers or {},
                request=httpx.Request(method, f"http://ev.test{path}"),
            )

        self.routes[(method.upper(), path)] = handler

    def add_handler(self, method: str, path: str, handler):
        self.routes[(method.upper(), path)] = handler

    def handle(self, method, path, *, json=None, data=None, params=None, files=None):
        rec = Recorded(method.upper(), path, json, params, files)
        self.requests.append(rec)
        handler = self.routes.get((rec.method, rec.path))
        if handler is None:
            resp = httpx.Response(
                404,
                json={"detail": f"route not mocked: {rec.method} {rec.path}"},
                request=httpx.Request(method, f"http://ev.test{path}"),
            )
        else:
            resp = handler(rec)
        if resp.status_code >= 400:
            handle_api_error(resp)  # raises SystemExit with mapped code
        return resp

    @property
    def last(self) -> Recorded:
        assert self.requests, "no API requests were made"
        return self.requests[-1]


@pytest.fixture
def api(monkeypatch) -> MockApi:
    mock = MockApi()

    def fake_request(self, method, path, *, json=None, data=None, params=None, files=None):
        return mock.handle(method, path, json=json, data=data, params=params, files=files)

    monkeypatch.setattr("fz_cli.client.FZClient.request", fake_request)
    return mock


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def invoke(runner, api):
    """Invoke the CLI with the API mocked; returns (result, api)."""
    from fz_cli.main import cli

    def _invoke(args, env=None, input=None):
        return runner.invoke(cli, args, env=env or {}, input=input)

    return _invoke


def parse_json_out(result) -> Any:
    """Parse stdout as JSON (for -o json invocations)."""
    return json_mod.loads(result.output)
