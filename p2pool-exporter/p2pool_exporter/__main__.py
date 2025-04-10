import argparse
import asyncio
import aiohttp
import logging as l
from prometheus_client import start_http_server, Histogram, Counter
import time as t
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

async def get_miner_info(session, miner, query_counter, error_counter, latency):
    labels = {"endpoint": "/api/miner_info"}
    start = t.perf_counter()

    async with session.get(f'https://mini.p2pool.observer{labels["endpoint"]}/{miner}') as response:
        data = await response.json()  # Await the actual response body (as JSON)
        
    end = t.perf_counter()

    query_counter.labels(**labels).inc()
    #latency_gauge.labels(**labels).set(end - start)

    if response.status != 200:
        error_counter.labels(**labels).inc()
        return {}
    else:
        return data

# Collect API data and handle async calls properly
async def collect_api_data(args):
    query_counter = Counter('p2pool_total_queries', 'Total queries run by p2pool exporter', ["endpoint"])
    error_counter = Counter('p2pool_total_errors', 'Total query errors from p2pool exporter', ["endpoint"])
    latency = Histogram('p2pool_api_latency', 'Measured latency when calling the p2pool API')

    # Start Prometheus server
    start_http_server(args.port)

    # Create the session once and pass it to each function call
    async with aiohttp.ClientSession() as session:
        # Query each miner wallet asynchronously
        tasks = [get_miner_info(session, miner, query_counter, error_counter, latency) for miner in args.wallets]
        
        # Await all tasks (don't forget this!)
        results = await asyncio.gather(*tasks)

        # Optionally process results here if needed
        l.debug(f"Collected data: {results}")

# Function to run APScheduler jobs
async def schedule_jobs(args):
    # Create the scheduler
    scheduler = AsyncIOScheduler()

    # Schedule collect_api_data() to run every X minutes
    scheduler.add_job(
         collect_api_data, 
        'interval',  # Run periodically
        seconds=args.tts,  # Every X minutes
        id='collect_data_job',  # Job identifier
        misfire_grace_time=10,  # Handle job misfires gracefully
        args = [args],
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
    print("Press Ctrl+{} to exit")
    while True:
        await asyncio.sleep(1000)


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
    l.basicConfig(level=args.log_level)

    # Schedule jobs
    asyncio.run(schedule_jobs(args))

if __name__ == "__main__":
    run()

