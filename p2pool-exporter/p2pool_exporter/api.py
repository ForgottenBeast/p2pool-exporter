import time
import aiohttp
import asyncio
import json
import logging as l
from opentelemetry import trace
from opentelemetry.sdk.trace import Status, StatusCode

from .telemetry import get_tracer, get_current_trace_id
from .utils import prune_shares, estimate_hashrate


async def query_api(session, endpoint, metrics):
    with get_tracer().start_as_current_span("query_api"):
        trace_id = get_current_trace_id()
        labels = {"endpoint": endpoint,  "trace_id": trace_id}
        metrics["query_counter"].add(1,attributes = labels)
        start = time.perf_counter()
        async with session.get(endpoint) as response:
            result = (
                await response.json()
            )  # Await the actual response body (as JSON)

        metrics["latency"].record(time.perf_counter() - start, attributes = labels)
        if "status" in result and result.status != 200:
            metrics["error_counter"].add(1, attributes = labels)
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

        trace_id = get_current_trace_id()
        label = {"miner": miner, "trace_id": trace_id}
        metrics["total_shares"].set(total_shares, attributes = label)
        metrics["last_share_height"].set(response["last_share_height"], attributes = label)
        metrics["last_share_timestamp"].set(
            response["last_share_timestamp"],
            attributes = label
        )


async def get_sideblocks(session, api, miner, metrics):
    with get_tracer().start_as_current_span("get_sideblocks"):
        response = await query_api(
            session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner), metrics
        )

        trace_id = get_current_trace_id()
        label = {"miner": miner, "trace_id": trace_id }
        metrics["sideblocks_in_window"].set(len(response), attributes=label)


async def get_payouts(session, api, miner, metrics):
    with get_tracer().start_as_current_span("get_payouts"):
        trace_id = get_current_trace_id()
        response = await query_api(
            session,
            "{}{}/{}?search_limit=1".format(api, "/api/payouts", miner),
            metrics,
        )
        l.info(
            json.dumps(
                {
                    "miner": miner,
                    "payout_id": response[0]["main_id"],
                    "amount": response[0]["coinbase_reward"],
                    "private_key": response[0]["coinbase_private_key"],
                    "trace_id": trace_id,
                }
            )
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


async def websocket_listener(url, metrics, miners, window_seconds):
    endpoint = "{}/api/events".format(url)
    accepted_shares = {}
    for m in miners:
        accepted_shares[m] = []

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(endpoint) as ws:
            async for wsmsg in ws:
                with get_tracer().start_as_current_span("ws_msg_recv"):
                    msg = wsmsg.json()
                    trace_id = get_current_trace_id()
                    label = { "trace_id": trace_id}
                    if msg["type"] == "side_block":
                        metrics["ws_event_counter"].add(1,attributes = {"type":"side_block"} | label)
                        metrics["main_difficulty"].set(msg["side_block"]["main_difficulty"], attributes = label)
                        metrics["p2pool_difficulty"].set(msg["side_block"]["difficulty"], attributes = label)
                        metrics["side_blocks"].add(1, attributes = label)

                        miner = msg["side_block"]["miner_address"]
                        if miner in miners:
                            accepted_shares[miner].append(
                                {
                                    "timestamp": msg["side_block"]["timestamp"],
                                    "difficulty": msg["side_block"]["difficulty"],
                                }
                            )
                            prune_shares(accepted_shares[miner], window_seconds)
                            metrics["p2pool_hashrate"].set(
                                estimate_hashrate(
                                    accepted_shares[miner], window_seconds
                                ),
                                attributes = {"miner": miner} | label
                            )

                    elif msg["type"] == "found_block":
                        metrics["ws_event_counter"].add(1,attributes = {"type":"found_block"}|label)
                        metrics["found_blocks"].add(1, attributes = label )
                        metrics["main_difficulty"].set(
                            msg["found_block"]["main_block"]["difficulty"], attributes = label
                        )
                        metrics["p2pool_difficulty"].set(msg["found_block"]["difficulty"], attributes = label)
                    elif msg["type"] == "orphaned_block":
                        metrics["ws_event_counter"].add(1, attributes = {"type":"orphaned_block"}|label)
                    else:
                        print("got type:{}".format(msg.type))
                        print(msg)
                        metrics["ws_event_counter"].add(1, attributes = {"type":"unknown_type"}|label)
