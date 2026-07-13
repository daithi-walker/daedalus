import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import probe_tests, publish_event, push_and_create_pr, run_claude_task
from .workflows import OrchestratorWorkflow, PRReviewWorkflow, TaskWorkflow

TASK_QUEUE = "agent-tasks"


async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(address)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrchestratorWorkflow, PRReviewWorkflow, TaskWorkflow],
        activities=[run_claude_task, publish_event, push_and_create_pr, probe_tests],
    )

    print(f"Worker connected to {address}, queue={TASK_QUEUE}")
    print("Ctrl-C to stop.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
