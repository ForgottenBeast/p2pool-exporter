from observlib import configure_telemetry
from .api import collect_api_data, websocket_listener
import argparse
import asyncio
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
        minutes=args.tts,  # Every X minutes
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
    await websocket_listener(args.endpoint, metrics)


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
    else:
        pyroscope_server = os.environ.get("PYROSCOPE_SERVER")

    configure_telemetry(
        "p2pool-exporter",
        os.environ["OTEL_SERVER"],
        pyroscope_server,
        sample_rate,
        resource_attrs=attrs,
    )

    # Schedule jobs
    asyncio.run(schedule_jobs(args))


if __name__ == "__main__":
    run()
