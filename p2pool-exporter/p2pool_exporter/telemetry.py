from prometheus_client import start_http_server
from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk.metrics import MeterProvider 
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)
from opentelemetry.sdk.metrics.export import (
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics import AlwaysOnExemplarFilter

import pyroscope


def get_current_trace_id():
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().trace_id, '032x')
    return "none"

def strip_query_params(url: str) -> str:
    return url.split("?")[0]


URLLibInstrumentor().instrument(
    # Remove all query params from the URL attribute on the span.
    url_filter=strip_query_params,
)
AsyncioInstrumentor().instrument()

# Creates a tracer from the global tracer provider
tracer = None


# Creates a meter from the global meter provider
meter = None

def get_meter():
    global meter
    return meter

def get_tracer():
    global tracer
    return tracer


def configure_pyroscope(**kwargs):
    pyroscope.configure(**kwargs)


def configure_otlp(server):
    global tracer
    global meter
    resource = Resource(attributes={SERVICE_NAME: "p2pool-exporter"})
    tracerProvider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://{}/v1/traces".format(server)))
    tracerProvider.add_span_processor(processor)
    trace.set_tracer_provider(tracerProvider)
    tracer = trace.get_tracer(__name__)

    metric_reader = PeriodicExportingMetricReader(PrometheusMetricReader())

    provider = MeterProvider(metric_readers=[metric_reader], exemplar_filter=AlwaysOnExemplarFilter())

    # Sets the global default meter provider
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter("p2pool-exporter")

def get_metrics():
    return {
        "query_counter": 
meter.create_counter(
    "p2pool_total_queries", unit="1", description="total emitted queries"
),

        "error_counter": meter.create_counter(
    "p2pool_total_errors", unit="1", description="total errors on queries"
),

        "latency": meter.create_histogram(
    name="p2pool_api_latency",
    unit="ms",
    description="Measured latency when calling the p2pool API",
),
        "total_shares":meter.create_gauge(
    name="total_shares",
    unit="1",
    description="Total shares mined"
),

        "last_share_height":meter.create_gauge(
    name="p2pool_last_share_height",
    unit="1",
    description="last share height"
),

        "last_share_timestamp": meter.create_gauge(
            name = "p2pool_last_share_timestamp", 
            unit = "1",
            description = "last share timestamp",
        ),
        "sideblocks_in_window": meter.create_gauge(
            name = "p2pool_sideblocks",
            unit = "1",
            description = "number of sideblocks in current window"
        ),
        "payouts": meter.create_gauge(name = "p2pool_payouts", unit = "1", description = "p2pool payouts"),
        "found_blocks": meter.create_counter(name = "p2pool_found_blocks", unit = "1", description= "pool-wide found blocks"),
        "side_blocks": meter.create_counter(name = "p2pool_blocks", unit = "1", description =  "pool-wide side blocks"),
        "main_difficulty": meter.create_gauge(name = "p2pool_main_difficulty", unit = "1", description =  "p2pool payouts"),
        "p2pool_difficulty": meter.create_gauge(
            name = "p2pool_sidechain_difficulty", description= "p2pool sidechain difficulty", unit = "1"
        ),
        "ws_event_counter": meter.create_counter(
            name = "p2pool_ws_events", unit = "1",description =  "messages received through the websocket API"
        ),
        "p2pool_hashrate": meter.create_gauge(
            name = "p2pool_hashrate", description = "estimated hashrate per miner", unit = "1",
        ),
    }
