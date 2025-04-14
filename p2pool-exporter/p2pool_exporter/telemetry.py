import logging
from opentelemetry import trace, metrics

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor

from opentelemetry._logs import set_logger_provider

from opentelemetry.sdk.metrics import MeterProvider 
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    )
from opentelemetry.sdk.metrics.export import (
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics import AlwaysOnExemplarFilter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

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
    endpoint = "http://{}/v1/traces".format(server)
    resource = Resource(attributes={SERVICE_NAME: "p2pool-exporter"})
    tracerProvider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    tracerProvider.add_span_processor(processor)
    trace.set_tracer_provider(tracerProvider)
    tracer = trace.get_tracer(__name__)

    otlp_exporter = OTLPMetricExporter(endpoint="http://{}/v1/metrics".format(server) )
    metric_reader = PeriodicExportingMetricReader(otlp_exporter,export_interval_millis=5000)

    provider = MeterProvider(metric_readers=[metric_reader], exemplar_filter=AlwaysOnExemplarFilter())

    # Sets the global default meter provider
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter("p2pool-exporter")

    otlp_log_exporter = OTLPLogExporter(endpoint="http://{}/v1/logs".format(server))

# Set up the logger provider with a batch log processor
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))
    set_logger_provider(logger_provider)

    # Set up Python logging integration
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)

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
