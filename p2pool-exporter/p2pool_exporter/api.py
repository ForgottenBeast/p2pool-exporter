import time
import aiohttp
import asyncio
import json
import logging as l
from opentelemetry import trace
from opentelemetry.sdk.trace import Status, StatusCode

from .telemetry import get_tracer
from .utils import estimate_hashrate


async def query_api(session, endpoint, metrics):
    with get_tracer().start_as_current_span("query_api"):
        labels = {"endpoint": endpoint}
        metrics["query_counter"].add(1, attributes=labels)
        start = time.perf_counter()
        async with session.get(endpoint) as response:
            result = await response.json()  # Await the actual response body (as JSON)

        metrics["latency"].record(time.perf_counter() - start, attributes=labels)
        if "status" in result and result.status != 200:
            metrics["error_counter"].add(1, attributes=labels)
            current_span = trace.get_current_span()
            current_span.set_status(Status(StatusCode.ERROR))

        return result


async def get_miner_info(session, api, miner, metrics):
    with get_tracer().start_as_current_span("get_miner_info"):
        response = await query_api(
            session, "{}{}/{}".format(api, "/api/miner_info", miner), metrics
        )

        total_shares = 0
        for s in response["shares"]:
            total_shares += s["shares"]
            total_shares += s["uncles"]

        label = {"miner": miner}
        metrics["total_shares"].set(total_shares, attributes=label)
        metrics["last_share_height"].set(
            response["last_share_height"], attributes=label
        )
        metrics["last_share_timestamp"].set(
            response["last_share_timestamp"], attributes=label
        )


async def get_sideblocks(session, api, miner, metrics):
    with get_tracer().start_as_current_span("get_sideblocks"):
        response = await query_api(
            session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner), metrics
        )

        label = {"miner": miner}

        total_blocks = 0
        for b in response:
            if isinstance(b, dict):
                total_blocks += 1

        metrics["sideblocks_in_window"].set(total_blocks, attributes=label)

        metrics["p2pool_hashrate"].set(
            estimate_hashrate(
                [
                    {"timestamp": s["timestamp"], "difficulty": s["difficulty"]}
                    for s in response
                ]
            ),
            attributes={"miner": miner},
        )


async def get_payouts(session, api, miner, metrics):
    with get_tracer().start_as_current_span("get_payouts"):
        response = await query_api(
            session,
            "{}{}/{}?search_limit=1".format(api, "/api/payouts", miner),
            metrics,
        )
        l.info(
            {
                "payout": {
                    "miner": miner,
                    "payout_id": response[0]["main_id"],
                    "amount": response[0]["coinbase_reward"],
                    "private_key": response[0]["coinbase_private_key"],
                    "timestamp": response[0]["timestamp"],
                }
            }
        )


async def collect_api_data(args, metrics):
    with get_tracer().start_as_current_span("collect_api_data"):
        # Start Prometheus server

        # Create the session once and pass it to each function call
        async with aiohttp.ClientSession() as session:
            # Query each miner wallet asynchronously
            tasks = (
                [
                    get_miner_info(session, args.endpoint, miner, metrics)
                    for miner in args.wallets
                ]
                + [
                    get_sideblocks(session, args.endpoint, miner, metrics)
                    for miner in args.wallets
                ]
                + [
                    get_payouts(session, args.endpoint, miner, metrics)
                    for miner in args.wallets
                ]
            )

            # Await all tasks (don't forget this!)
            results = await asyncio.gather(*tasks)

            # Optionally process results here if needed
            l.debug(f"Collected data: {results}")


async def websocket_listener(url, metrics):
    endpoint = "{}/api/events".format(url)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.ws_connect(endpoint) as ws:
                    async for wsmsg in ws:
                        with get_tracer().start_as_current_span("ws_msg_recv"):
                            msg = wsmsg.json()
                            if msg["type"] == "side_block":
                                metrics["ws_event_counter"].add(
                                    1, attributes={"type": "side_block"}
                                )
                                if "main_difficulty" in msg["side_block"]:
                                    metrics["main_difficulty"].set(
                                        msg["side_block"]["main_difficulty"]
                                    )

                                if "difficulty" in msg["side_block"]:
                                    metrics["p2pool_difficulty"].set(
                                        msg["side_block"]["difficulty"]
                                    )
                                metrics["side_blocks"].add(1)

                            elif msg["type"] == "found_block":
                                metrics["ws_event_counter"].add(
                                    1, attributes={"type": "found_block"}
                                )
                                metrics["found_blocks"].add(1)
                                metrics["main_difficulty"].set(
                                    msg["found_block"]["main_block"]["difficulty"],
                                )
                                metrics["p2pool_difficulty"].set(
                                    msg["found_block"]["difficulty"]
                                )
                            elif msg["type"] == "orphaned_block":
                                metrics["ws_event_counter"].add(
                                    1, attributes={"type": "orphaned_block"}
                                )
                            else:
                                l.warn(
                                    {
                                        "message": "got unknown api events message: {}".format(
                                            json.dumps(msg)
                                        )
                                    }
                                )
                                metrics["ws_event_counter"].add(
                                    1, attributes={"type": "unknown_type"}
                                )
            except Exception as ex:
                metrics["error_counter"].add(1, attributes={"endpoint": endpoint})
                l.warn(
                    {"message": "error connecting to the websocket API: {}".format(ex)}
                )
