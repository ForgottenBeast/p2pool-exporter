from observlib import configure_telemetry
import os
from .api import collect_api_data, websocket_listener, configure_redis
import argparse
import asyncio
from .telemetry import initialize_telemetry
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from logging import getLogger

logger = getLogger(__name__)


async def schedule_jobs(args):
    # Create the scheduler

    scheduler = AsyncIOScheduler()

    # Schedule collect_api_data() to run every X minutes
    scheduler.add_job(
        collect_api_data,
        "interval",  # Run periodically
        minutes=int(args.tts),  # Every X minutes
        id="collect_data_job",  # Job identifier
        misfire_grace_time=10,  # Handle job misfires gracefully
        args=[args],
    )

    # Add a listener to log job execution outcomes
    def job_listener(event):
        if event.exception:
            logger.error(f"Job {event.job_id} failed with exception: {event.exception}")
        else:
            logger.debug(f"Job {event.job_id} succeeded")

    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Start the scheduler and run the asyncio loop together
    scheduler.start()
    await websocket_listener(args.endpoint)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--api-endpoint",
        action="store",
        dest="endpoint",
        required=True,
        help="API endpoint eg: p2pool mini observer/api",
    )
    parser.add_argument(
        "-w",
        "--wallets",
        nargs="+",
        action="store",
        dest="wallets",
        required=True,
        help="Wallets to monitor",
    )
    parser.add_argument(
        "-l",
        "--log",
        help="Specify log level",
        dest="log_level",
        default="INFO",
        action="store",
    )
    parser.add_argument(
        "-t",
        "--time-to-scrape",
        help="How many minutes between scrapes",
        dest="tts",
        default=5,
        action="store",
    )

    parser.add_argument(
        "-e",
        "--exchange-rate",
        help="currencies for exchange rate tracking",
        dest="exchange_rate",
        default=["EUR"],
        nargs="+",
        action="store",
    )

    parser.add_argument(
        "-d",
        "--devmode",
        action="store_true",
        help="enable debug mode, increase telemetry",
        dest="debug",
    )

    parser.add_argument(
        "-P",
        "--port",
        help="Prometheus port to expose metrics, leave to 0 to only upload through otlp",
        dest="port",
        action="store",
        default=9093,
        type=int,
    )

    args = parser.parse_args()
    attrs = {}
    sample_rate = 5
    if args.debug:
        attrs = {"environment": "dev"}
        sample_rate = 100

    pyroscope_server = None
    if args.debug:
        pyroscope_server = os.environ.get("PYROSCOPE_DEV_SERVER")
        redis = os.environ.get("REDIS_DEV_SERVER").split(":")
    else:
        pyroscope_server = os.environ.get("PYROSCOPE_SERVER")
        redis = os.environ.get("REDIS_SERVER").split(":")

    configure_redis(*redis)
    configure_telemetry(
        "p2pool-exporter",
        os.environ["OTEL_SERVER"],
        pyroscope_server,
        sample_rate,
        resource_attrs=attrs,
    )

    # Schedule jobs
    initialize_telemetry(*redis, args.wallets, args.exchange_rate)
    asyncio.run(schedule_jobs(args))


if __name__ == "__main__":
    run()
