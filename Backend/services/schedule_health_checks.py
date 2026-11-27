from datetime import datetime, timezone

from rq_scheduler import Scheduler

from core.config import settings
from services.queue import health_queue, redis_connection
from services.tasks import check_container_health


def main() -> None:
    scheduler = Scheduler(
        queue=health_queue,
        connection=redis_connection,
    )
    scheduler.schedule(
        scheduled_time=datetime.now(timezone.utc),
        func=check_container_health,
        interval=int(settings.WATCHDOG_INTERVAL_SECONDS),
        repeat=None,
        queue_name=health_queue.name,
        id="onedeploy-health-check",
    )


if __name__ == "__main__":
    main()
