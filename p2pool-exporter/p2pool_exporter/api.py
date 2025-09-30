import redis.asyncio as redis
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

redis_client = None


def configure_redis(host, port):
    global redis_client
    redis_client = redis.Redis(host=host, port=port, db=0, protocol=3)


@traced(**traced_conf)
async def query_api(session, endpoint):
    with session.get(endpoint) as response:
        result = response.json()  # Await the actual response body (as JSON)

    if "status" in result and result.status != 200:
        raise Exception("error querying")

    return result


@traced(tracer=service_name)
async def get_miner_info(session, api, miner):
    response = await query_api(session, "{}{}/{}".format(api, "/api/miner_info", miner))

    total_shares = 0
    for s in response["shares"]:
        total_shares += s["shares"]
        total_shares += s["uncles"]

    new_data = {"last_share_height": response["last_share_height"]}
    logger.info("retrieved miner data", extra=new_data | {"miner": miner})
    cur_data = await redis_client.get(f"miner:{miner}")
    if cur_data:
        new_data = json.loads(cur_data) | new_data
    await redis_client.set(f"miner:{miner}", json.dumps(new_data), ex=300)


@traced(tracer=service_name)
async def get_sideblocks(session, api, miner):
    response = await query_api(
        session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner)
    )

    total_blocks = 0
    for b in response:
        if isinstance(b, dict):
            total_blocks += 1

    cur_data = await redis_client.get(f"miner:{miner}")
    new_data = {
        "total_blocks": total_blocks,
        "hashrate": estimate_hashrate(
            [
                {"timestamp": s["timestamp"], "difficulty": s["difficulty"]}
                for s in response
            ]
        ),
    }

    if cur_data:
        new_data = json.loads(cur_data) | new_data
    await redis_client.set(f"miner:{miner}", json.dumps(new_data), ex=300)


@traced(tracer=service_name)
async def get_payouts(session, api, miner):
    response = await query_api(
        session,
        "{}{}/{}?search_limit=0".format(api, "/api/payouts", miner),
    )
    logger.info(
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
    total_payouts = sum([x["coinbase_reward"] for x in response])

    cur_data = await redis_client.get(f"miner:{miner}")
    new_data = {"payouts": total_payouts}
    if cur_data:
        new_data = json.loads(cur_data) | new_data

    await redis_client.set(f"miner:{miner}", json.dumps(new_data), ex=300)


@traced(tracer=service_name)
async def collect_api_data(args):
    # Create the session once and pass it to each function call
    async with aiohttp.ClientSession() as session:
        # Query each miner wallet asynchronously
        tasks = (
            [get_miner_info(session, args.endpoint, miner) for miner in args.wallets]
            + [get_sideblocks(session, args.endpoint, miner) for miner in args.wallets]
            + [get_payouts(session, args.endpoint, miner) for miner in args.wallets]
        )

        # Await all tasks (don't forget this!)
        await asyncio.gather(*tasks)


@traced(tracer=service_name)
async def websocket_listener(url):
    ws_event_counter = get_counter(
        frozenset({"name": "p2pool_expoter_ws_event_counter"}.items())
    )
    main_difficulty_g = get_gauge(
        frozenset({"name": "p2pool_exporter_main_difficulty"}.items())
    )
    pool_difficulty_g = get_gauge(
        frozenset({"name": "p2pool_exporter_pool_difficulty"}.items())
    )
    found_blocks_c = get_counter(
        frozenset({"name": "p2pool_exporter_found_blocks"}.items())
    )
    side_blocks_c = get_counter(
        frozenset({"name": "p2pool_exporter_side_blocks"}.items())
    )
    orphaned_blocks_c = get_counter(
        frozenset({"name": "p2pool_exporter_orphaned_blocks"}.items())
    )

    endpoint = "{}/api/events".format(url)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.ws_connect(endpoint) as ws:
                    async for wsmsg in ws:
                        msg = wsmsg.json()
                        ws_event_counter.add(1)
                        if msg["type"] == "side_block":
                            if "main_difficulty" in msg["side_block"]:
                                main_difficulty_g.set(
                                    msg["side_block"]["main_difficulty"]
                                )

                            if "difficulty" in msg["side_block"]:
                                pool_difficulty_g.set(msg["side_block"]["difficulty"])
                            side_blocks_c.add(1)

                        elif msg["type"] == "found_block":
                            found_blocks_c.add(1)
                            main_difficulty_g.set(
                                msg["found_block"]["main_block"]["difficulty"],
                            )
                            pool_difficulty_g.set(msg["found_block"]["difficulty"])
                        elif msg["type"] == "orphaned_block":
                            orphaned_blocks_c.add(1)
                        else:
                            logger.warn(
                                {
                                    "message": "got unknown api events message: {}".format(
                                        json.dumps(msg)
                                    )
                                }
                            )
            except Exception as ex:
                logger.warn(
                    {"message": "error connecting to the websocket API: {}".format(ex)}
                )
                raise
