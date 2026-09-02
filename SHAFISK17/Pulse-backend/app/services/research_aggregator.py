
import asyncio
import arxiv
import logging
from datetime import datetime
from typing import List, Dict, Any
from appwrite.query import Query

from app.config import settings
from app.services.appwrite_db import get_appwrite_db

# Configure logger
logger = logging.getLogger(__name__)

# Category Mapping: ArXiv -> Segmento Pulse
CATEGORY_MAPPING = {
    # AI & Machine Learning
    "cs.AI": "research-ai",
    "cs.LG": "research-ml",  # Machine Learning
    "cs.CL": "research-ai",  # Computation and Language (NLP)
    "cs.CV": "research-ai",  # Computer Vision
    "cs.NE": "research-ml",  # Neural and Evolutionary Computing
    
    # Cloud & Distributed Computing
    "cs.DC": "research-cloud", # Distributed, Parallel, and Cluster Computing
    "cs.OS": "research-cloud", # Operating Systems
    "cs.NI": "research-cloud", # Networking and Internet Architecture
    
    # Data & Databases
    "cs.DB": "research-data",  # Databases
    "cs.DS": "research-data",  # Data Structures and Algorithms
    "cs.IR": "research-data",  # Information Retrieval
    "cs.CR": "research-data",  # Cryptography and Security (Data Security)
}

# Reverse mapping for display/debugging
INTERNAL_TO_DISPLAY = {
    "research-ai": "Artificial Intelligence",
    "research-ml": "Machine Learning",
    "research-cloud": "Cloud Computing",
    "research-data": "Data Engineering"
}

class ResearchAggregator:
    """
    Fetches research papers from ArXiv and stores them in Appwrite.
    """
    def __init__(self):
        self.client = arxiv.Client(
            page_size=20,
            delay_seconds=3.0,
            num_retries=3
        )

    async def fetch_and_process_daily_papers(self):
        """
        Main entry point: Fetches papers for all mapped categories.
        """
        logger.info("🔬 [RESEARCH AGGREGATOR] Starting daily fetch...")
        
        total_fetched = 0
        total_saved = 0
        
        # Group ArXiv categories by our internal buckets to query efficiently
        # Actually, query arXiv by category groups
        # We can query multiple categories at once: 'cat:cs.AI OR cat:cs.LG'
        
        # 1. Build Query Strings
        # AI Group
        ai_query = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:cs.NE"
        # Cloud Group
        cloud_query = "cat:cs.DC OR cat:cs.OS OR cat:cs.NI"
        # Data Group
        data_query = "cat:cs.DB OR cat:cs.DS OR cat:cs.IR OR cat:cs.CR"
        
        queries = [
            ("AI/ML", ai_query),
            ("Cloud", cloud_query),
            ("Data", data_query)
        ]
        
        for group_name, query_str in queries:
            logger.info(f"   🔍 Querying ArXiv for {group_name}...")
            
            # Construct search
            search = arxiv.Search(
                query=query_str,
                max_results=30, # Limit per group to avoid spam
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending
            )
            
            # Execute sync generator in async context (blocking? ArXiv lib is sync)
            # We should ideally run this in a thread executor if it blocks too long, 
            # but for 30 items it's okay for background job.
            
            results = list(self.client.results(search))
            logger.info(f"   found {len(results)} papers for {group_name}")
            
            for paper in results:
                total_fetched += 1
                processed_paper = self._process_paper(paper)
                if processed_paper:
                   saved = await self._save_paper(processed_paper)
                   if saved:
                       total_saved += 1
                       
        logger.info(f"✅ [RESEARCH AGGREGATOR] Completed. Fetched: {total_fetched}, Saved: {total_saved}")
        return total_saved

    def _process_paper(self, paper: arxiv.Result) -> Dict[str, Any]:
        """
        Transforms ArXiv result into our Appwrite Schema.
        """
        # 1. Determine Primary Category
        # ArXiv results have .categories list. We take the first one that matches our mapping.
        primary_cat = paper.categories[0] 
        internal_cat = CATEGORY_MAPPING.get(primary_cat)
        
        if not internal_cat:
            # Fallback: check other categories
            for cat in paper.categories:
                if cat in CATEGORY_MAPPING:
                    internal_cat = CATEGORY_MAPPING[cat]
                    primary_cat = cat
                    break
        
        if not internal_cat:
            return None # Skip if not in our scope
            
        import hashlib
        pdf_url = paper.pdf_url
        url_hash = hashlib.sha256(pdf_url.encode('utf-8')).hexdigest()
            
        # 2. Format Data
        return {
            "paper_id": self._get_short_id(paper.entry_id),
            "title": paper.title.replace("\n", " ").strip(),
            "summary": paper.summary.replace("\n", " ").strip(),
            "description": paper.summary.replace("\n", " ").strip(), # Added for general compatibility
            "authors": [a.name for a in paper.authors],
            "published_at": paper.published.isoformat(),
            "pdf_url": pdf_url,
            "url": pdf_url, # COMPATIBILITY: Map pdf_url to url for frontend/models
            "image_url": "", # Ensure empty string to avoid null schema violations
            "url_hash": url_hash, # Required by base schema
            "category": internal_cat,     # research-ai
            "original_category": primary_cat, # cs.AI
            "sub_category": INTERNAL_TO_DISPLAY.get(internal_cat, "Research"), # Friendly name
            "source": "arXiv"
        }

    def _get_short_id(self, entry_id: str) -> str:
        # ArXiv IDs are like http://arxiv.org/abs/2101.12345v1
        # We want "2101.12345v1"
        return entry_id.split("/")[-1]

    async def _save_paper(self, paper_data: Dict[str, Any]) -> bool:
        """
        Saves to Appwrite if not exists.
        """
        appwrite = get_appwrite_db()
        if not appwrite.initialized:
            logger.error("Appwrite not initialized")
            return False
            
        try:
            # We need to flatten authors list to string because Appwrite String array 
            # logic depends on how we created schema. 
            paper_data['authors'] = ", ".join(paper_data['authors'])
            
            # Use deterministic document ID to let Appwrite natively catch duplicates
            # Document IDs max 36 chars: alphanumeric, _, -, .
            doc_id = paper_data['paper_id'].replace('.', '_').replace('/', '_')
            
            await appwrite.tablesDB.create_row(
                database_id=settings.APPWRITE_DATABASE_ID,
                collection_id=settings.APPWRITE_RESEARCH_COLLECTION_ID,
                document_id=doc_id,
                data=paper_data
            )
            logger.info(f"   💾 Saved: {paper_data['title'][:50]}...")
            return True
            
        except Exception as e:
            # Check for 409 Conflict Document already exists
            if "already exists" in str(e).lower() or "409" in str(e):
                 logger.debug(f"   ⏭️  Skipping duplicate (Atomic): {paper_data['paper_id']}")
                 return False
            
            logger.error(f"   ❌ Error saving paper {paper_data['paper_id']}: {e}")
            return False

# Standalone run for testing
if __name__ == "__main__":
    import sys
    import os
    
    # Add project root to path
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
    
    async def run():
        agg = ResearchAggregator()
        await agg.fetch_and_process_daily_papers()
    
    asyncio.run(run())
