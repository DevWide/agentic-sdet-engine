import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    OTLP_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the OTLP extra
    OTLP_AVAILABLE = False

_provider = None


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def setup_telemetry() -> trace.Tracer:
    """Build the tracer provider, exporting to an OTLP collector and optionally to stdout."""
    global _provider

    resource = Resource.create(
        {
            "service.name": "agentic-sdet-engine",
            "service.version": "0.1.0",
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
        }
    )

    _provider = TracerProvider(resource=resource)

    # Off by default: raw span JSON on stdout interleaves with the Rich CLI output.
    if _env_flag("OTEL_CONSOLE_EXPORT"):
        _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    if OTLP_AVAILABLE and not _env_flag("OTEL_SDK_DISABLED"):
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
        try:
            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        except Exception as exc:  # noqa: BLE001 - telemetry must never break the run
            logger.warning("OTLP exporter disabled (endpoint=%s): %s", endpoint, exc)

    trace.set_tracer_provider(_provider)
    return trace.get_tracer("agentic-sdet-engine")


def flush_telemetry() -> None:
    """Drain the batch processors before the CLI exits, so no span is lost."""
    if _provider:
        _provider.shutdown()


tracer = setup_telemetry()
