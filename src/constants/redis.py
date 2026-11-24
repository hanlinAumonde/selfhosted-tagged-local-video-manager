#: Second key segment, after the configured prefix, of each kind of thing kept in Redis.
#: Each kind has its own, so a scan over one can never reach another.
CACHE_NAMESPACE = "cache"
TASK_NAMESPACE = "task"
BATCH_NAMESPACE = "batch"
QUEUE_NAMESPACE = "queue"

#: Last segment of a task's or batch's progress channel, and of a task's latest frame.
PROGRESS_CHANNEL = "progress"
LATEST_FRAME = "latest"

#: Appended to a queue's name to name the consumer group its worker reads with.
#: Deployed names: changing it strands the messages already queued.
CONSUMER_GROUP_SUFFIX = "-worker"