from opentelemetry import trace
import json
import time
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider, Status, StatusCode
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
import argparse
import asyncio
import aiohttp
import logging as l
from prometheus_client import start_http_server, Histogram, Counter, Gauge
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import pyroscope
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.trace.span import format_trace_id

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

async def query_api(session, endpoint, metrics):
    with tracer.start_as_current_span("query_api") as span:
        labels = {"endpoint": endpoint}
        metrics["query_counter"].labels(**labels).inc()
        with metrics["latency"].labels(**labels).time():
            async with session.get(endpoint) as response:
                result = await response.json()  # Await the actual response body (as JSON)

                if "status" in result and result.status != 200:
                    metrics["error_counter"].labels(**labels).inc()
                    current_span = trace.get_current_span()
                    current_span.set_status(Status(StatusCode.ERROR))

                return result

async def get_miner_info(session,api, miner,metrics):
    with tracer.start_as_current_span("get_miner_info") as span:
        response = await query_api(session, "{}{}/{}".format(api, "/api/miner_info", miner),metrics)
            
        total_shares = 0
        for s in response["shares"]:
            total_shares += s["shares"]

        label = { "miner": miner}
        metrics["total_shares"].labels(**label).set(total_shares)
        metrics["last_share_height"].labels(**label).set(response["last_share_height"])
        metrics["last_share_timestamp"].labels(**label).set(response["last_share_timestamp"])

async def get_sideblocks(session,api, miner, metrics):
    with tracer.start_as_current_span("get_sideblocks") as span:
        response = await query_api(session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner),metrics)
        label = { "miner": miner}
        metrics["sideblocks_in_window"].labels(**label).set(len(response))

async def get_payouts(session,api, miner, metrics):
    with tracer.start_as_current_span("get_payouts") as span:
        response = await query_api(session, "{}{}/{}?search_limit=1".format(api, "/api/payouts", miner),metrics)
        l.info(json.dumps({ "miner": miner, "payout_id": response[0]["main_id"], "amount": response[0]["coinbase_reward"], "private_key": response[0]["coinbase_private_key"] }))

async def collect_api_data(args, metrics):
    with tracer.start_as_current_span("collect_api_data") as span:

        # Start Prometheus server

        # Create the session once and pass it to each function call
        async with aiohttp.ClientSession() as session:
            # Query each miner wallet asynchronously
            tasks = [get_miner_info(session, args.endpoint, miner,metrics) for miner in args.wallets] + [get_sideblocks(session, args.endpoint,  miner,metrics) for miner in args.wallets] + [ get_payouts(session, args.endpoint, miner, metrics) for miner in args.wallets]
            
            # Await all tasks (don't forget this!)
            results = await asyncio.gather(*tasks)

            # Optionally process results here if needed
            l.debug(f"Collected data: {results}")

def prune_shares(accepted_shares, window_seconds):
    accepted_shares = list(filter(lambda share: share.timestamp < time.time() - window_seconds, accepted_shares))


def estimate_hashrate(accepted_shares, window_seconds=600):
    now = time.time()
    recent_shares = [s for s in accepted_shares if now - s["timestamp"] <= window_seconds]

    total_difficulty = sum(s["difficulty"] for s in recent_shares)
    return total_difficulty / window_seconds  # Hashrate in H/s

async def websocket_listener(url, metrics, miners, window_seconds):
    endpoint = "{}/api/events".format(url)
    accepted_shares = {}
    for m in miners:
        accepted_shares[m] = []

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(endpoint) as ws:
            async for msg in ws:
                with tracer.start_as_current_span("ws_msg_recv") as span:
                    if msg.type == "side_block":
                        metrics["ws_event_counter"].labels(type = "side_block").inc()
                        metrics.main_difficulty.set(msg.side_block.main_difficulty)
                        metrics.p2pool_difficulty.set(msg.side_block.difficulty)
                        metrics.side_blocks.inc()

                        if msg.side_block.miner_address in miners:
                            miner = msg.side_block.miner_address
                            accepted_shares[miner].append({
                                "timestamp":msg.side_block.timestamp,
                                "difficulty":msg.side_block.difficulty
                                })
                            prune_shares(accepted_shares[miner], window_seconds)
                            metrics.p2pool_hashrate.labels(miner=miner).set(estimate_hashrate(accepted_shares[miner], window_seconds))


                    elif msg.type == "found_block":
                        metrics["ws_event_counter"].labels(type = "found_block").inc()
                        metrics.found_blocks.inc()
                        metrics.main_difficulty.set(msg.found_block.main_block.difficulty)
                        metrics.p2pool_difficulty.set(msg.found_block.difficulty)
                    else:
                        metrics["ws_event_counter"].labels(type = "orphaned_block").inc()
                    

async def schedule_jobs(args):
    # Create the scheduler

    with tracer.start_as_current_span("schedule_jobs") as span:
        metrics = {
            "query_counter" : Counter('p2pool_total_queries', 'Total queries run by p2pool exporter', ["endpoint"]),
            "error_counter" : Counter('p2pool_total_errors', 'Total query errors from p2pool exporter', ["endpoint"]),
            "latency" : Histogram('p2pool_api_latency', 'Measured latency when calling the p2pool API', ["endpoint"]),
            "total_shares" : Gauge('p2pool_total_shares', 'Total shares mined', ["miner"]),
            "last_share_height" : Gauge('p2pool_last_share_height', 'last share height', ["miner"]),
            "last_share_timestamp" : Gauge('p2pool_last_share_timestamp', 'last share timestamp', ["miner"]),
            "sideblocks_in_window" : Gauge('p2pool_sideblocks','number of sideblocks in current window', ["miner"]),
            "payouts" : Gauge('p2pool_payouts','p2pool payouts', ["miner"]),
            "found_blocks" : Counter('p2pool_found_blocks','pool-wide found blocks'),
            "side_blocks" : Counter('p2pool_blocks','pool-wide side blocks'),
            "main_difficulty" : Gauge('p2pool_main_difficulty','p2pool payouts', ["miner"]),
            "p2pool_difficulty" : Gauge('p2pool_sidechain_difficulty','p2pool payouts', ["miner"]),
            "ws_event_counter": Counter("p2pool_ws_events","messages received through the websocket API", ["type"]),
            "p2pool_hashrate": Gauge('p2pool_hashrate', "estimated hashrate per miner", ["miner"]),
        }



    scheduler = AsyncIOScheduler()

    # Schedule collect_api_data() to run every X minutes
    scheduler.add_job(
         collect_api_data, 
        'interval',  # Run periodically
        seconds=args.tts,  # Every X minutes
        id='collect_data_job',  # Job identifier
        misfire_grace_time=10,  # Handle job misfires gracefully
        args = [args, metrics],
    )

    # Add a listener to log job execution outcomes
    def job_listener(event):
        if event.exception:
            l.error(f'Job {event.job_id} failed with exception: {event.exception}')
        else:
            l.debug(f'Job {event.job_id} succeeded')

    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Start the scheduler and run the asyncio loop together
    scheduler.start()
    await websocket_listener(args.endpoint, metrics, args.wallets, args.window)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--api-endpoint", action="store", dest="endpoint", required=True, help="API endpoint eg: p2pool mini observer/api")
    parser.add_argument("-w", "--wallets", nargs="+", action="store", dest="wallets", required=True, help="Wallets to monitor")
    parser.add_argument("-l", "--log", help="Specify log level", dest="log_level", default="INFO", action="store")
    parser.add_argument("-p", "--pyroscope-server", help="Pyroscope server address for profiling", dest="pyroscope", default=None, action="store")
    parser.add_argument("-o", "--otlp-server", help="OTLP server for spans", dest="otlp", default=None, action="store")
    parser.add_argument("-t", "--time-to-scrape", help="How many minutes between scrapes", dest="tts", default=5, action="store")
    parser.add_argument("-P", "--port", help="Prometheus port to expose metrics", dest="port", action="store", default=9093, type=int)
    parser.add_argument("-W", "--window-seconds", help = "window to use for hashrate estimation", dest = "window", action = "store", default = 600, type = int)

    args = parser.parse_args()
    if args.pyroscope:
        pyroscope.configure(application_name = "p2pool_exporter", server_address=args.pyroscope)

    if args.otlp:
        resource = Resource(attributes={SERVICE_NAME: "p2pool_exporter"})
        tracerProvider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=args.otlp))
        tracerProvider.add_span_processor(processor)
        trace.set_tracer_provider(tracerProvider)
        global tracer
        tracer = trace.get_tracer(__name__)

    start_http_server(args.port, addr = "127.0.0.1")
    l.basicConfig(level=args.log_level)
    # Schedule jobs
    asyncio.run(schedule_jobs(args))

if __name__ == "__main__":
    run()

