import time


def estimate_hashrate(accepted_shares):
    now = time.time()
    oldest_share = now
    total_difficulty = 0
    for s in accepted_shares:
        if s["timestamp"] < oldest_share:
            oldest_share = s["timestamp"]

    if now == oldest_share:
        return 0

    total_difficulty = sum(s["difficulty"] for s in accepted_shares)
    return total_difficulty / (now - oldest_share)  # Hashrate in H/s
