import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    OTLP_AVAILABLE = True
except ImportError:
    OTLP_AVAILABLE = False

_provider = None


def setup_telemetry() -> trace.Tracer:
    """Configura o provedor de traces com suporte a Console e Jaeger via HTTP OTLP."""
    global _provider

    resource = Resource.create(
        {
            "service.name": "agentic-sdet-engine",
            "service.version": "1.0.0",
            "deployment.environment": "development",
        }
    )

    _provider = TracerProvider(resource=resource)
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    if OTLP_AVAILABLE:
        try:
            # Envia via HTTP/JSON direto para o Jaeger no endpoint OTLP padrao
            otlp_exporter = OTLPSpanExporter(
                endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
            )
            _provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except Exception:
            pass

    trace.set_tracer_provider(_provider)
    return trace.get_tracer("agentic-sdet-engine")


def flush_telemetry():
    """Forca o envio imediato de todos os traces em buffer antes de encerrar o CLI."""
    if _provider:
        _provider.shutdown()


tracer = setup_telemetry()