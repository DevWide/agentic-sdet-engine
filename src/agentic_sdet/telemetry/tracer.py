import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.sdk.resources import Resource

def configure_telemetry(service_name: str = "agentic-sdet-engine"):
    resource = Resource.create({
        "service.name": service_name,
        "service.version": "1.0.0",
        "deployment.environment": os.getenv("ENV", "development"),
    })
    provider = TracerProvider(resource=resource)
    # ConsoleSpanExporter imprime os Spans de forma visual; pode ser trocado por OTLPSpanExporter
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)

tracer = configure_telemetry()