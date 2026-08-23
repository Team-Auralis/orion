import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.propagate import inject, extract
import asyncio

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

def test_trace_continuity_across_nats():
    # 1. Simulate API side (Inject)
    with tracer.start_as_current_span("api_publish_incident") as api_span:
        api_trace_id = api_span.get_span_context().trace_id
        
        headers = {}
        inject(headers)
        
        # Verify traceparent is in headers
        assert "traceparent" in headers, "API did not inject traceparent into NATS headers"
    
    # 2. Simulate Worker side (Extract)
    ctx = extract(headers)
    with tracer.start_as_current_span("process_nats_message", context=ctx) as worker_span:
        worker_trace_id = worker_span.get_span_context().trace_id
        
        # Verify IDs match across the simulated network boundary
        assert api_trace_id == worker_trace_id, "Worker did not maintain trace continuity"
