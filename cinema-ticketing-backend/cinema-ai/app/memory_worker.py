"""Retry leased MySQL outbox jobs and maintain the derived Chroma index."""

import asyncio
import logging

from app.java_client import JavaApiClient
from app.memory import MemoryIndex

logger = logging.getLogger(__name__)


async def process_job(java: JavaApiClient, index: MemoryIndex, job: dict) -> None:
    """Skip superseded versions; acknowledge only after successful projection."""
    success = False
    try:
        memory = job.get("memory")
        if memory is None or memory["version"] == job["eventVersion"]:
            # Lease lasts five minutes; bound a batch job so later jobs retain their lease.
            async with asyncio.timeout(20):
                await index.apply(job["memoryId"], memory)
        success = True
    except Exception as exc:
        logger.warning("Memory indexing failed for job %s (%s)", job["jobId"], type(exc).__name__)
    await java.post(
        f"/internal/ai/memory-index/{job['jobId']}/ack",
        {"leaseToken": job["leaseToken"], "success": success},
    )


async def run() -> None:
    """Poll with bounded retries; server leases recover interrupted workers."""
    java, index = JavaApiClient(), MemoryIndex()
    try:
        while True:
            try:
                jobs = await java.post("/internal/ai/memory-index/claim", {})
                for job in jobs:
                    await process_job(java, index, job)
                await asyncio.sleep(1 if jobs else 5)
            except Exception as exc:
                logger.warning("Memory worker unavailable (%s)", type(exc).__name__)
                await asyncio.sleep(5)
    finally:
        await java.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
