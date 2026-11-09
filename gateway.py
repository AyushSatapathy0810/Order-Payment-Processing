import os

import redis
from fastapi import HTTPException, Request

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
)

# Atomically refill and consume tokens. All requests from the same IP share a bucket.
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_second = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local values = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(values[1]) or capacity
local updated_at = tonumber(values[2]) or now

tokens = math.min(capacity, tokens + (now - updated_at) * refill_per_second)

if tokens < 1 then
    redis.call('HMSET', key, 'tokens', tokens, 'updated_at', now)
    redis.call('EXPIRE', key, 120)
    return 0
end

tokens = tokens - 1
redis.call('HMSET', key, 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', key, 120)
return 1
"""


def enforce_rate_limit(request: Request) -> None:
    import time

    client_ip = request.client.host if request.client else "unknown"
    allowed = redis_client.eval(
        TOKEN_BUCKET_SCRIPT,
        1,
        f"rate-limit:{client_ip}",
        20,                 # bucket capacity
        2,                  # tokens refilled per second
        time.time(),
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")