from .client import client


async def save_crawl_job(data: dict):
    if not data:
        return None

    if hasattr(client, "crawljob"):
        return await client.crawljob.upsert(
            where={"job_id": data["job_id"]},
            data={
                "create": data,
                "update": data,
            },
        )

    columns = ", ".join(f'"{key}"' for key in data.keys())
    placeholders = ", ".join(f"${idx + 1}" for idx in range(len(data)))
    update_assignments = ", ".join(
        f'"{key}" = EXCLUDED."{key}"' for key in data.keys() if key != "job_id"
    )
    query = (
        f"INSERT INTO \"CrawlJob\" ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT (\"job_id\") DO UPDATE SET {update_assignments} RETURNING *"
    )
    result = await client.query_raw(query, *data.values())
    return result[0] if result else None


async def update_crawl_job(job_id: str, data: dict):
    if not job_id or not data:
        return None

    if hasattr(client, "crawljob"):
        return await client.crawljob.update(
            where={"job_id": job_id},
            data=data,
        )

    assignments = ", ".join(f'"{key}" = ${idx + 1}' for idx, key in enumerate(data.keys()))
    query = (
        f"UPDATE \"CrawlJob\" SET {assignments} WHERE \"job_id\" = ${len(data) + 1} RETURNING *"
    )
    values = [*data.values(), job_id]
    result = await client.query_raw(query, *values)
    return result[0] if result else None


async def delete_crawl_job(job_id: str):
    if not job_id:
        return None

    if hasattr(client, "crawljob"):
        return await client.crawljob.delete(where={"job_id": job_id})

    return await client.execute_raw(
        'DELETE FROM "CrawlJob" WHERE "job_id" = $1',
        job_id,
    )


async def get_crawl_jobs():
    if hasattr(client, "crawljob"):
        return await client.crawljob.find_many(order={"updatedAt": "desc"})

    return await client.query_raw('SELECT * FROM "CrawlJob" ORDER BY "updatedAt" DESC')


async def get_crawl_job_by_id(job_id: str):
    if not job_id:
        return None

    if hasattr(client, "crawljob"):
        return await client.crawljob.find_unique(where={"job_id": job_id})

    return await client.query_first(
        'SELECT * FROM "CrawlJob" WHERE "job_id" = $1 LIMIT 1',
        job_id,
    )



