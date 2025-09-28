from functools import lru_cache
from opentelemetry.metrics import get_meter

def strip_query_params(url: str) -> str:
    return url.split("?")[0]


@lru_cache(maxsize=None)
def get_counter(counter_data, up_down = False):
    if up_down:
        return get_meter("p2pool-exporter").create_up_down_counter(**dict(counter_data))
    else:
        return get_meter("p2pool-exporter").create_counter(**dict(counter_data))


@lru_cache(maxsize=None)
def get_gauge(gauge_data):
    return get_meter("p2pool-exporter").create_gauge(**dict(gauge_data))


@lru_cache(maxsize=None)
def get_histogram(hist_data):
    return get_meter("p2pool-exporter").create_histogram(**dict(histogram_data))

def get_query_labels(result, error, func_args = None, func_kwargs = None):
    if error:
        return {"status":"failure", "endpoint":func_args[1]}
    return {"status":"success", endpoint: func_args[1]}

def get_traced_conf():
    traced_conf = {
        "tracer": "p2pool-exporter",
        "counter": "p2pool_exporter_query_counter",
        "timer": "p2pool_exporter_latency",
        "timer_factory": get_histogram,
        "counter_factory": get_counter,
        "label_fn": get_query_labels,
    }
    return traced_conf

URLLibInstrumentor().instrument(
    # Remove all query params from the URL attribute on the span.
    url_filter=strip_query_params,
)
AsyncioInstrumentor().instrument()
