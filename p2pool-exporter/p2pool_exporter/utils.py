import time

def prune_shares(accepted_shares, window_seconds):
    accepted_shares = list(filter(lambda share: share.timestamp < time.time() - window_seconds, accepted_shares))


def estimate_hashrate(accepted_shares, window_seconds=600):
    now = time.time()
    recent_shares = [s for s in accepted_shares if now - s["timestamp"] <= window_seconds]

    total_difficulty = sum(s["difficulty"] for s in recent_shares)
    return total_difficulty / window_seconds  # Hashrate in H/s

