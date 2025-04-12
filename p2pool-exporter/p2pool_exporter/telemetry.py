from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)

from opentelemetry.trace.span import format_trace_id
from prometheus_client import start_http_server, Histogram, Counter, Gauge
import pyroscope


def strip_query_params(url: str) -> str:
    return url.split("?")[0]


URLLibInstrumentor().instrument(
    # Remove all query params from the URL attribute on the span.
    url_filter=strip_query_params,
)
LoggingInstrumentor(set_logging_format=True)
AsyncioInstrumentor().instrument()

# Creates a tracer from the global tracer provider
tracer = None


def get_tracer():
    global tracer
    return tracer


def configure_pyroscope(**kwargs):
    pyroscope.configure(**kwargs)


def configure_otlp(service_name, server):
    global tracer
    resource = Resource(attributes={SERVICE_NAME: service_name})
    tracerProvider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=server))
    tracerProvider.add_span_processor(processor)
    trace.set_tracer_provider(tracerProvider)
    tracer = trace.get_tracer(__name__)


def get_metrics():
    return {
        "query_counter": Counter(
            "p2pool_total_queries", "Total queries run by p2pool exporter", ["endpoint"]
        ),
        "error_counter": Counter(
            "p2pool_total_errors",
            "Total query errors from p2pool exporter",
            ["endpoint"],
        ),
        "latency": Histogram(
            "p2pool_api_latency",
            "Measured latency when calling the p2pool API",
            ["endpoint"],
        ),
        "total_shares": Gauge("p2pool_total_shares", "Total shares mined", ["miner"]),
        "last_share_height": Gauge(
            "p2pool_last_share_height", "last share height", ["miner"]
        ),
        "last_share_timestamp": Gauge(
            "p2pool_last_share_timestamp", "last share timestamp", ["miner"]
        ),
        "sideblocks_in_window": Gauge(
            "p2pool_sideblocks", "number of sideblocks in current window", ["miner"]
        ),
        "payouts": Gauge("p2pool_payouts", "p2pool payouts", ["miner"]),
        "found_blocks": Counter("p2pool_found_blocks", "pool-wide found blocks"),
        "side_blocks": Counter("p2pool_blocks", "pool-wide side blocks"),
        "main_difficulty": Gauge("p2pool_main_difficulty", "p2pool payouts", ["miner"]),
        "p2pool_difficulty": Gauge(
            "p2pool_sidechain_difficulty", "p2pool payouts", ["miner"]
        ),
        "ws_event_counter": Counter(
            "p2pool_ws_events", "messages received through the websocket API", ["type"]
        ),
        "p2pool_hashrate": Gauge(
            "p2pool_hashrate", "estimated hashrate per miner", ["miner"]
        ),
    }
