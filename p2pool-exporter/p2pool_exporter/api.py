from .telemetry import get_tracer
import logging as l
import json
import asyncio
import aiohttp
from .utils import prune_shares, estimate_hashrate


async def query_api(session, endpoint, metrics):
    with get_tracer().start_as_current_span("query_api") as span:
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
    with get_tracer().start_as_current_span("get_miner_info") as span:
        response = await query_api(session, "{}{}/{}".format(api, "/api/miner_info", miner),metrics)
            
        total_shares = 0
        for s in response["shares"]:
            total_shares += s["shares"]

        label = { "miner": miner}
        metrics["total_shares"].labels(**label).set(total_shares)
        metrics["last_share_height"].labels(**label).set(response["last_share_height"])
        metrics["last_share_timestamp"].labels(**label).set(response["last_share_timestamp"])

async def get_sideblocks(session,api, miner, metrics):
    with get_tracer().start_as_current_span("get_sideblocks") as span:
        response = await query_api(session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner),metrics)
        label = { "miner": miner}
        metrics["sideblocks_in_window"].labels(**label).set(len(response))

async def get_payouts(session,api, miner, metrics):
    with get_tracer().start_as_current_span("get_payouts") as span:
        response = await query_api(session, "{}{}/{}?search_limit=1".format(api, "/api/payouts", miner),metrics)
        l.info(json.dumps({ "miner": miner, "payout_id": response[0]["main_id"], "amount": response[0]["coinbase_reward"], "private_key": response[0]["coinbase_private_key"] }))

async def collect_api_data(args, metrics):
    with get_tracer().start_as_current_span("collect_api_data") as span:

        # Start Prometheus server

        # Create the session once and pass it to each function call
        async with aiohttp.ClientSession() as session:
            # Query each miner wallet asynchronously
            tasks = [get_miner_info(session, args.endpoint, miner,metrics) for miner in args.wallets] + [get_sideblocks(session, args.endpoint,  miner,metrics) for miner in args.wallets] + [ get_payouts(session, args.endpoint, miner, metrics) for miner in args.wallets]
            
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
            async for msg in ws:
                with get_tracer().start_as_current_span("ws_msg_recv") as span:
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

