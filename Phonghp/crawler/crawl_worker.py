from services.crawl_service import crawl_job_worker as service_crawl_job_worker

async def crawl_job_worker(job, manager):
    await service_crawl_job_worker(job, manager)
