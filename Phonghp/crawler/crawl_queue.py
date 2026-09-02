from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, Dict, List, Optional
from collections import deque
import uuid


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return _utcnow()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class CrawlJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"


class CrawlChapterStatus(str, Enum):
    pending = "pending"
    skipped = "skipped"
    crawled = "crawled"
    failed = "failed"


@dataclass
class CrawlChapterItem:
    chapter_no: int
    title_vi: str
    url: str
    access: str = "regular"
    status: CrawlChapterStatus = CrawlChapterStatus.pending


@dataclass
class CrawlJobData:
    job_id: str
    book_url: str
    created_at: datetime
    updated_at: datetime
    status: CrawlJobStatus = CrawlJobStatus.queued
    total_chapters: int = 0
    crawled_chapters: int = 0
    current_chapter_index: int = 0
    current_chapter_title: Optional[str] = None
    current_chapter_url: Optional[str] = None
    book_id: Optional[str] = None
    chapters: List[CrawlChapterItem] = field(default_factory=list)


class CrawlQueueManager:
    def __init__(self) -> None:
        self._queue: Deque[str] = deque()
        self._jobs: Dict[str, CrawlJobData] = {}

    def _generate_job_id(self) -> str:
        return str(uuid.uuid4())

    def add_job(self, book_url: str) -> CrawlJobData:
        cleaned_url = book_url.strip()
        if not cleaned_url:
            raise ValueError("Invalid URL for crawl job")

        existing = self._find_job_by_book_url(cleaned_url)
        if existing:
            return existing

        job_id = self._generate_job_id()
        now = _utcnow()
        job = CrawlJobData(
            job_id=job_id,
            book_url=cleaned_url,
            created_at=now,
            updated_at=now,
            status=CrawlJobStatus.queued,
        )
        self._jobs[job_id] = job
        self._queue.append(job_id)
        return job

    def _find_job_by_book_url(self, book_url: str) -> Optional[CrawlJobData]:
        for job in self._jobs.values():
            if job.book_url == book_url:
                return job
        return None

    def get_job(self, job_id: str) -> Optional[CrawlJobData]:
        return self._jobs.get(job_id)

    def get_all_jobs(self) -> List[CrawlJobData]:
        return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def restore_job(self, job: CrawlJobData) -> None:
        if not job or not job.job_id:
            return

        job.created_at = _ensure_utc(job.created_at)
        job.updated_at = _ensure_utc(job.updated_at)
        self._jobs[job.job_id] = job
        if job.status == CrawlJobStatus.queued:
            if job.job_id not in self._queue:
                self._queue.append(job.job_id)

    def _find_job_by_book_url(self, book_url: str) -> Optional[CrawlJobData]:
        for job in self._jobs.values():
            if job.book_url == book_url:
                return job
        return None

    def pause_job(self, job_id: str) -> Optional[CrawlJobData]:
        job = self.get_job(job_id)
        if job and job.status in {CrawlJobStatus.queued, CrawlJobStatus.running}:
            job.status = CrawlJobStatus.paused
            job.updated_at = _utcnow()
            if job_id in self._queue:
                self._queue.remove(job_id)
        return job

    def resume_job(self, job_id: str) -> Optional[CrawlJobData]:
        job = self.get_job(job_id)
        if not job:
            return None
        if job.status in {CrawlJobStatus.paused, CrawlJobStatus.failed}:
            job.status = CrawlJobStatus.queued
            job.updated_at = _utcnow()
            if job_id in self._queue:
                self._queue.remove(job_id)
            self._queue.appendleft(job_id)
        return job

    def complete_job(self, job_id: str) -> Optional[CrawlJobData]:
        job = self.get_job(job_id)
        if job:
            job.status = CrawlJobStatus.completed
            if job.total_chapters > 0:
                job.crawled_chapters = job.total_chapters
                job.current_chapter_index = job.total_chapters
            job.updated_at = _utcnow()
        return job

    def fail_job(self, job_id: str) -> Optional[CrawlJobData]:
        job = self.get_job(job_id)
        if job:
            job.status = CrawlJobStatus.failed
            job.updated_at = _utcnow()
        return job

    def remove_job(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._jobs.pop(job_id)
        if job_id in self._queue:
            self._queue.remove(job_id)

    def dequeue_next(self) -> Optional[CrawlJobData]:
        while self._queue:
            job_id = self._queue.popleft()
            job = self.get_job(job_id)
            if not job:
                continue
            if job.status == CrawlJobStatus.queued:
                job.status = CrawlJobStatus.running
                job.updated_at = _utcnow()
                return job
            if job.status == CrawlJobStatus.paused:
                continue
        return None

    def add_chapters(self, job_id: str, chapters: List[CrawlChapterItem]) -> None:
        job = self.get_job(job_id)
        if job:
            job.chapters = chapters
            job.total_chapters = len(chapters)
            job.crawled_chapters = sum(1 for item in chapters if item.status == CrawlChapterStatus.crawled)
            job.current_chapter_index = 0
            job.current_chapter_title = None
            job.current_chapter_url = None
            job.updated_at = _utcnow()

    def update_current_chapter(self, job_id: str, chapter: CrawlChapterItem) -> Optional[CrawlJobData]:
        job = self.get_job(job_id)
        if job:
            job.current_chapter_index = chapter.chapter_no
            job.current_chapter_title = chapter.title_vi
            job.current_chapter_url = chapter.url
            job.updated_at = _utcnow()
        return job

    def get_remaining_chapters(self, job_id: str) -> int:
        job = self.get_job(job_id)
        if not job:
            return 0

        if job.chapters:
            return sum(1 for item in job.chapters if item.status == CrawlChapterStatus.pending)

        if job.total_chapters > 0:
            return max(0, job.total_chapters - job.crawled_chapters)

        return 0

    def update_progress(self, job_id: str, crawled_chapters: int, current_chapter_index: int) -> Optional[CrawlJobData]:
        job = self.get_job(job_id)
        if job:
            job.crawled_chapters = crawled_chapters
            job.current_chapter_index = current_chapter_index
            job.updated_at = _utcnow()
        return job

    def record_chapter_status(self, job_id: str, chapter_no: int, status: CrawlChapterStatus) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        for chapter in job.chapters:
            if chapter.chapter_no == chapter_no:
                chapter.status = status
                break
        job.crawled_chapters = sum(1 for item in job.chapters if item.status == CrawlChapterStatus.crawled)
        job.updated_at = datetime.utcnow()

    def is_paused(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return bool(job and job.status == CrawlJobStatus.paused)
