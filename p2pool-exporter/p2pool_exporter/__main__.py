from .telemetry import get_metrics, configure_pyroscope, configure_otlp
from .api import collect_api_data, websocket_listener
import argparse
import asyncio
import logging as l
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from apscheduler.schedulers.asyncio import AsyncIOScheduler


async def schedule_jobs(args):
    # Create the scheduler

    metrics = get_metrics()

    scheduler = AsyncIOScheduler()

    # Schedule collect_api_data() to run every X minutes
    scheduler.add_job(
        collect_api_data,
        "interval",  # Run periodically
        seconds=args.tts,  # Every X minutes
        id="collect_data_job",  # Job identifier
        misfire_grace_time=10,  # Handle job misfires gracefully
        args=[args, metrics],
    )

    # Add a listener to log job execution outcomes
    def job_listener(event):
        if event.exception:
            l.error(f"Job {event.job_id} failed with exception: {event.exception}")
        else:
            l.debug(f"Job {event.job_id} succeeded")

    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Start the scheduler and run the asyncio loop together
    scheduler.start()
    await websocket_listener(args.endpoint, metrics, args.wallets, args.window)


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
        "-p",
        "--pyroscope-server",
        help="Pyroscope server address for profiling",
        dest="pyroscope",
        default=None,
        action="store",
    )
    parser.add_argument(
        "-o",
        "--otlp-server",
        help="OTLP server for spans",
        dest="otlp",
        default=None,
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
        "-P",
        "--port",
        help="Prometheus port to expose metrics, leave to 0 to only upload through otlp",
        dest="port",
        action="store",
        default=9093,
        type=int,
    )
    parser.add_argument(
        "-W",
        "--window-seconds",
        help="window to use for hashrate estimation",
        dest="window",
        action="store",
        default=600,
        type=int,
    )

    args = parser.parse_args()
    if args.pyroscope:
        configure_pyroscope(
            application_name="p2pool_exporter",
            server_address="http://{}".format(args.pyroscope),
        )

    if args.otlp:
        configure_otlp(args.otlp, "p2pool-exporter")

    l.basicConfig(level=args.log_level)
    # Schedule jobs
    asyncio.run(schedule_jobs(args))


if __name__ == "__main__":
    run()
