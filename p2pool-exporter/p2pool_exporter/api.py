import time
import aiohttp
import asyncio
import json
from logging import getLogger
from .telemetry import get_traced_conf, get_counter, get_gauge
from .utils import estimate_hashrate
from observlib import traced

logger = getLogger(__name__)
service_name = "p2pool-exporter"

traced_conf = get_traced_conf()

@traced(**traced_conf)
async def query_api(session,endpoint, metrics):
        global session
        with session.get(endpoint) as response:
            result = response.json()  # Await the actual response body (as JSON)

        if "status" in result and result.status != 200:
            raise Exception("error querying")

        return result

@traced(tracer = service_name)
async def get_miner_info(session, api, miner, metrics):
    shares_c = get_counter(frozenset({"name":"p2pool_exporter_total_shares"}.items()))
    last_shares_height_g = get_gauge(frozenset({"name":"p2pool_exporter_last_share_height"}.items()))
    last_shares_timestamp_g = get_gauge(frozenset({"name":"p2pool_exporter_last_share_timestamp"}.items()))

    response = await query_api(
        session, "{}{}/{}".format(api, "/api/miner_info", miner), metrics
    )

    total_shares = 0
    for s in response["shares"]:
        total_shares += s["shares"]
        total_shares += s["uncles"]

    label = {"miner": miner}

    shares_c.set(total_shares, attributes=label)
    last_share_height_g.set(
        response["last_share_height"], attributes=label
    )
    last_share_timestamp_g.set(
        response["last_share_timestamp"], attributes=label
    )


@traced(tracer = service_name)
async def get_sideblocks(session, api, miner, metrics):
    sideblocks_c = get_counter(frozenset({"name":"p2pool_exporter_sideblocks_in_window"}.items()),up_down = True)
    hashrate_c = get_counter(frozenset({"name":"p2pool_exporter_hashrate"}.items()),up_down = True)
    response = await query_api(
        session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner), metrics
    )

    label = {"miner": miner}

    total_blocks = 0
    for b in response:
        if isinstance(b, dict):
            total_blocks += 1

    sideblocks_c.set(total_blocks, attributes=label)

    hashrate_c.set(
        estimate_hashrate(
            [
                {"timestamp": s["timestamp"], "difficulty": s["difficulty"]}
                for s in response
            ]
        ),
        attributes={"miner": miner},
    )


@traced(tracer = service_name)
async def get_payouts(session, api, miner, metrics):
    payouts_c = get_counter(frozenset({"name":"p2pool_exporter_payouts"}.items()), up_down = True) #goes down when payouts are old enough
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


@traced(tracer = service_name)
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


@traced(tracer = service_name)
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
