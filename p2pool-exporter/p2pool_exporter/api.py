from bs4 import BeautifulSoup
import re
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
    async with session.get(endpoint) as response:
        result = await response.json()  # Await the actual response body (as JSON)

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
    await redis_client.set(f"miner:{miner}", json.dumps(new_data), ex=3600)


@traced(tracer=service_name)
async def get_sideblocks(session, api, miner):
    response = await query_api(
        session, "{}{}/{}".format(api, "/api/side_blocks_in_window", miner)
    )

    total_blocks = 0
    last_timestamp = 0
    for b in response:
        if isinstance(b, dict):
            total_blocks += 1
            if b["timestamp"] > last_timestamp:
                last_timestamp = b["timestamp"]

    cur_data = await redis_client.get(f"miner:{miner}")

    new_data = {
        "total_blocks": total_blocks,
        "last_share_timestamp": last_timestamp,
        "hashrate": estimate_hashrate(
            [
                {"timestamp": s["timestamp"], "difficulty": s["difficulty"]}
                for s in response
            ]
        ),
    }

    logger.info("retrieved miner performance", extra=new_data)

    if cur_data:
        data = json.loads(cur_data)
        prev_timestamp = data.get("last_share_timestamp")
        # also checks if prev timestamp is 0
        if prev_timestamp and prev_timestamp >= last_timestamp:
            new_data["last_share_timestamp"] = prev_timestamp
        new_data = data | new_data
    await redis_client.set(f"miner:{miner}", json.dumps(new_data), ex=3600)


@traced(tracer=service_name)
async def get_payouts(session, api, miner):
    response = await query_api(
        session,
        "{}{}/{}?search_limit=1".format(api, "/api/payouts", miner),
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

    cur_data = await redis_client.get(f"miner:{miner}") or {}
    new_data = {"last_payout_id": response[0]["main_id"]}
    if cur_data:
        cur_data = json.loads(cur_data)
        prev_payout = cur_data.get("payouts") or 0
        prev_payout_id = cur_data.get("last_payout_id") or 0

        if prev_payout_id != new_data["last_payout_id"]:
            new_data["payouts"] = prev_payout + response[0]["coinbase_reward"]

        new_data = cur_data | new_data

    await redis_client.set(f"miner:{miner}", json.dumps(new_data), ex=3600)


@traced(tracer=service_name)
async def get_exchange_rates(session, currencies):
    global redis_client

    async with session.get(
        "https://min-api.cryptocompare.com/data/price",
        params={"fsym": "XMR", "tsyms": ",".join(currencies)},
    ) as response:
        result = await response.json()  # Await the actual response body (as JSON)

    if "status" in result and result.status != 200:
        logger.error(
            f"error getting exchange rate: {result}", extra={"status": result.status}
        )
        return
    elif "RateLimit" in result:
        logger.error("rate limited on exchange rate")
        return

    await redis_client.set("exchange_rates", json.dumps(result), ex=3600)

@traced(tracer=service_name)
async def get_raffle_rates(session, miner):
    try:
        async with session.get("https://xmrvsbeast.com/cgi-bin/p2pool_bonus_history.cgi", params={"address": miner}) as response:
            result = await response.text()
            parsed = BeautifulSoup(result, features="html.parser")

        if not parsed or not parsed.body:
            logger.error(f"Failed to parse raffle rates HTML for miner {miner}")
            return

        raffle_element = parsed.body.find('p', attrs={"style": "color:#40a340;"})
        if not raffle_element:
            logger.error(f"Raffle rates element not found for miner {miner}. Website structure may have changed.")
            return

        raffle_state = raffle_element.text
        match = re.match(r'.*avg: (?P<one_hour>[0-9]+\.[0-9]+)(?P<one_hour_unit>[A-z])H/s.*avg: (?P<one_day>[0-9]+\.[0-9]+)(?P<one_day_unit>[A-z])H/s', raffle_state)

        if not match:
            logger.error(f"Raffle rates regex pattern did not match for miner {miner}. Text: {raffle_state}")
            return

        one_hour_rate = float(match.group("one_hour")) * 1000.0
        one_day_rate = float(match.group("one_day")) * 1000.0

        logger.info(f"Retrieved raffle rates for miner {miner}: 1h={one_hour_rate}, 1d={one_day_rate}")

        cur_data = await redis_client.get(f"miner:{miner}")
        if cur_data:
            cur_data = json.loads(cur_data)
        else:
            cur_data = {}

        new_data = {"raffle_rates": {"hour": one_hour_rate, "day": one_day_rate}}
        new_data = cur_data | new_data

        await redis_client.set(f"miner:{miner}", json.dumps(new_data), ex=3600)
    except Exception as e:
        logger.error(f"Error fetching raffle rates for miner {miner}: {e}", exc_info=True)

@traced(tracer=service_name)
async def collect_api_data(args):
    # Create the session once and pass it to each function call
    async with aiohttp.ClientSession() as session:
        # Query each miner wallet asynchronously
        tasks = (
            [get_miner_info(session, args.endpoint, miner) for miner in args.wallets]
            + [get_sideblocks(session, args.endpoint, miner) for miner in args.wallets]
            + [get_payouts(session, args.endpoint, miner) for miner in args.wallets]
            + [get_exchange_rates(session, args.exchange_rate)]
            + [get_raffle_rates(session, miner) for miner in args.wallets]
        )

        await asyncio.gather(*tasks)


@traced(tracer=service_name)
async def websocket_listener(url):
    ws_event_counter = get_counter(
        frozenset({"name": "p2pool_exporter_ws_event_counter"}.items())
    )
    difficulty_g = get_gauge(frozenset({"name": "p2pool_exporter_difficulty"}.items()))
    blocks_c = get_counter(frozenset({"name": "p2pool_exporter_blocks"}.items()))

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
                                difficulty_g.set(
                                    msg["side_block"]["main_difficulty"],
                                    attributes={"pool": "main"},
                                )

                            if "difficulty" in msg["side_block"]:
                                difficulty_g.set(
                                    msg["side_block"]["difficulty"],
                                    attributes={"pool": "side"},
                                )
                            blocks_c.add(1, attributes={"type": "sideblock"})

                        elif msg["type"] == "found_block":
                            blocks_c.add(1, attributes={"type": "found"})
                            difficulty_g.set(
                                msg["found_block"]["main_block"]["difficulty"],
                                attributes={"pool": "main"},
                            )
                            difficulty_g.set(
                                msg["found_block"]["difficulty"],
                                attributes={"pool": "side"},
                            )
                        elif msg["type"] == "orphaned_block":
                            blocks_c.add(1, attributes={"type": "orphaned"})
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
                await asyncio.sleep(5)
