from core.storage.job_store import JobStore

class ProcessingQueue:
    """Stable façade for future migration of legacy scheduler queues to SQLite."""
    def __init__(self, path="data/jobs.sqlite3"):
        self.store=JobStore(path)

    def enqueue_article(self, article_id, payload):
        return self.store.enqueue("article.process", {"article_id": article_id, **payload}, job_id=f"article:{article_id}")

    def enqueue_publish(self, article_id, payload):
        return self.store.enqueue("article.publish", {"article_id": article_id, **payload}, job_id=f"publish:{article_id}")
