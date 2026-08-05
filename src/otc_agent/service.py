from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .budget import Budget
from .catalog import Catalog
from .domain import ChangeKind, ChangeRequest
from .orchestrator import Planner
from .security import SecurityViolation
from .telemetry import Metrics, trace_id_from_traceparent


MAX_BODY = 20_000


def serve(host: str, port: int, catalog: Catalog) -> None:
    metrics = Metrics()
    planner = Planner(catalog, metrics)

    class Handler(BaseHTTPRequestHandler):
        server_version = "otc-agent"

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/healthz", "/readyz"}:
                self._json(HTTPStatus.OK, {"status": "ok"})
            elif self.path == "/metrics":
                body = metrics.render_prometheus().encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/plans":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise SecurityViolation("request body size is invalid")
                raw = json.loads(self.rfile.read(length))
                request = ChangeRequest(
                    service=raw.get("service"),
                    kind=ChangeKind(raw["kind"]),
                    description=raw["description"],
                    issue_url=raw.get("issue_url"),
                    docs_repository=raw.get("docs_repository"),
                    correlation_id=trace_id_from_traceparent(self.headers.get("traceparent")) or raw.get("correlation_id"),
                )
                plan = planner.plan(request, Budget())
                self._json(HTTPStatus.OK, plan.as_dict())
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                metrics.increment("requests_total", status="rejected")
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "detail": str(exc)[:300]})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, status: HTTPStatus, value: object) -> None:
            body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer((host, port), Handler).serve_forever()
