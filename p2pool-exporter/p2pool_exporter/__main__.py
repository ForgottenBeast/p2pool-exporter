import argparse
import asyncio
import aiohttp
import logging as l
from prometheus_client import start_http_server, Histogram, Counter, Gauge
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

async def query_api(session, endpoint, metrics):
    labels = {"endpoint": endpoint}
    metrics["query_counter"].labels(**labels).inc()
    with metrics["latency"].labels(**labels).time():
        async with session.get(endpoint) as response:
            result = await response.json()  # Await the actual response body (as JSON)

            if "status" in result and result.status != 200:
                metrics["error_counter"].labels(**labels).inc()
            return result

async def get_miner_info(session,api, miner,metrics):
    response = await query_api(session, "{}{}/{}".format(api, "/api/miner_info", miner),metrics)
        
    total_shares = 0
    for s in response["shares"]:
        total_shares += s["shares"]

    label = { "miner": miner}
    metrics["total_shares"].labels(**label).set(total_shares)
    metrics["last_share_height"].labels(**label).set(response["last_share_height"])
    metrics["last_share_timestamp"].labels(**label).set(response["last_share_timestamp"])

async def get_sideblocks(session,api, miner, metrics):
    response = await query_api(session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner),metrics)
    label = { "miner": miner}
    metrics["sideblocks_in_window"].labels(**label).set(len(response))

async def get_payouts(session,api, miner, metrics):
    response = await query_api(session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner),metrics)

# Collect API data and handle async calls properly
async def collect_api_data(args, metrics):

    # Start Prometheus server

    # Create the session once and pass it to each function call
    async with aiohttp.ClientSession() as session:
        # Query each miner wallet asynchronously
        tasks = [get_miner_info(session, args.endpoint, miner,metrics) for miner in args.wallets] + [get_sideblocks(session, args.endpoint,  miner,metrics) for miner in args.wallets]
        
        # Await all tasks (don't forget this!)
        results = await asyncio.gather(*tasks)

        # Optionally process results here if needed
        l.debug(f"Collected data: {results}")


async def websocket_listener(url, metrics):
    endpoint = "{}/api/events".format(url)
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(endpoint) as ws:
            async for msg in ws:
                metrics["ws_event_counter"].inc()
                if msg.type == "side_block":
                    metrics.main_difficulty.set(msg.side_block.main_difficulty)
                    metrics.p2pool_difficulty.set(msg.side_block.difficulty)
                    metrics.side_blocks.inc()
                elif msg.type == "found_block":
                    metrics.found_blocks.inc()
                    metrics.main_difficulty.set(msg.found_block.main_block.difficulty)
                    metrics.p2pool_difficulty.set(msg.found_block.difficulty)
                    


                print(msg)

async def schedule_jobs(args):
    # Create the scheduler

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
        "ws_event_counter": Counter("p2pool_ws_events","messages received through the websocket API")
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
            l.info(f'Job {event.job_id} succeeded')

    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Start the scheduler and run the asyncio loop together
    scheduler.start()
    await websocket_listener(args.endpoint, metrics)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--api-endpoint", action="store", dest="endpoint", required=True, help="API endpoint eg: p2pool mini observer/api")
    parser.add_argument("-w", "--wallets", nargs="+", action="store", dest="wallets", required=True, help="Wallets to monitor")
    parser.add_argument("-l", "--log", help="Specify log level", dest="log_level", default="INFO", action="store")
    parser.add_argument("-p", "--pyroscope-server", help="Pyroscope server address for profiling", dest="pyroscope", default=None, action="store")
    parser.add_argument("-o", "--otlp-server", help="OTLP server for spans", dest="otlp", default=None, action="store")
    parser.add_argument("-t", "--time-to-scrape", help="How many minutes between scrapes", dest="tts", default=5, action="store")
    parser.add_argument("-P", "--port", help="Prometheus port to expose metrics", dest="port", action="store", default=9093, type=int)

    args = parser.parse_args()
    start_http_server(args.port)
    l.basicConfig(level=args.log_level)
    # Schedule jobs
    asyncio.run(schedule_jobs(args))

if __name__ == "__main__":
    run()

