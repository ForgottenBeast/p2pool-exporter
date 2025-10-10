from functools import lru_cache, partial
import json
import redis
from opentelemetry.metrics import get_meter, CallbackOptions, Observation
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor


def strip_query_params(url: str) -> str:
    return url.split("?")[0]


@lru_cache(maxsize=None)
def get_counter(counter_data, up_down=False):
    if up_down:
        return get_meter("p2pool-exporter").create_up_down_counter(**dict(counter_data))
    else:
        return get_meter("p2pool-exporter").create_counter(**dict(counter_data))


@lru_cache(maxsize=None)
def get_gauge(gauge_data):
    return get_meter("p2pool-exporter").create_gauge(**dict(gauge_data))


@lru_cache(maxsize=None)
def get_histogram(hist_data):
    return get_meter("p2pool-exporter").create_histogram(**dict(hist_data))


def get_query_labels(result, error, func_args=None, func_kwargs=None):
    if error:
        return {"status": "failure", "endpoint": func_args[1]}
    return {"status": "success", "endpoint": func_args[1]}


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

redis_client = None


def exchange_rate_callback(options: CallbackOptions, currencies):
    global redis_client
    rates = redis_client.get("exchange_rates")
    if rates:
        rates = json.loads(rates)
        if "Message" not in rates:
            for c, r in rates.items():
                yield Observation(r, attributes={"currency": c})


def miner_info_callback(options: CallbackOptions, miners):
    global redis_client
    for miner in miners:
        data = redis_client.get(f"miner:{miner}")
        attrs = {"miner": miner}
        parsed = {}
        if data:
            parsed = json.loads(data)

        value = parsed.get("last_share_height") or 0
        yield Observation(value, attributes=attrs | {"metric": "last_share_height"})

        value = parsed.get("hashrate") or 0
        yield Observation(value, attributes=attrs | {"metric": "hashrate"})

        value = parsed.get("last_share_timestamp") or 0
        yield Observation(value, attributes=attrs | {"metric": "last_share_timestamp"})


def miner_rewards_callback(options: CallbackOptions, miners):
    global redis_client
    for miner in miners:
        data = redis_client.get(f"miner:{miner}")
        attrs = {"miner": miner}
        parsed = {}
        if data:
            parsed = json.loads(data)
        total_blocks = parsed.get("total_blocks") or 0
        yield Observation(total_blocks, attributes=attrs | {"metric": "total_blocks"})

        payouts = parsed.get("payouts") or 0
        yield Observation(payouts, attributes=attrs | {"metric": "payouts"})


def initialize_telemetry(redis_host, redis_port, miners, currencies):
    global redis_client
    redis_client = redis.Redis(host=redis_host, port=redis_port, db=0, protocol=3)
    meter = get_meter("p2pool-exporter")
    meter.create_observable_gauge(
        name="p2pool_exporter_miner_performance",
        callbacks=[partial(miner_info_callback, miners=miners)],
        description="miner information",
    )
    meter.create_observable_up_down_counter(
        name="p2pool_exporter_miner_rewards",
        callbacks=[partial(miner_rewards_callback, miners=miners)],
        description="miner rewards info",
    )
    meter.create_observable_gauge(
        name="p2pool_exporter_exchange_rate",
        callbacks=[partial(exchange_rate_callback, currencies=currencies)],
        description="exchange rates",
    )
