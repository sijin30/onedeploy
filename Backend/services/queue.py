from redis import Redis
from rq import Queue

from core.config import settings


redis_connection = Redis.from_url(settings.REDIS_URL)
deployment_queue = Queue(
    "deployments",
    connection=redis_connection,
    default_timeout=600,
)
health_queue = Queue(
    "health",
    connection=redis_connection,
    default_timeout=300,
)
