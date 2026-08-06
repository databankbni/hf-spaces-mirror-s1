"""Researcher Agent - Scrapes web data for research queries."""

import os
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import trafilatura
import ollama
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

from database.connection import DatabaseConnection

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class ScrapedContent:
    """Represents content scraped from a web source."""
    url: str
    title: str
    content: str
    metadata: Dict = field(default_factory=dict)
    scraped_at: datetime = field(default_factory=datetime.now)


class ResearcherAgent:
    """Agent responsible for researching topics by scraping web data."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        host: Optional[str] = None,
        max_results: Optional[int] = None,
        db_connection: Optional[DatabaseConnection] = None,
    ):
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", "qwen2:0.5b")
        self.host = host or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.max_results = int(os.getenv("MAX_SCRAPING_RESULTS", "10")) if max_results is None else max_results
        self.client = ollama.Client(host=self.host)
        self.db = db_connection
        self.search_engine = "https://html.duckduckgo.com/html/?q="

        # Local Vector DB for RAG
        try:
            self.chroma_client = chromadb.Client()
            self.embed_model = "nomic-embed-text"
            self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        except Exception as e:
            logger.warning(f"Failed to initialize ChromaDB: {e}")
            self.chroma_client = None

    def _search_duckduckgo(self, query: str) -> List[str]:
        """Search DuckDuckGo and return URLs of top results using the DDGS library."""
        try:
            from duckduckgo_search import DDGS
            
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=self.max_results))
                urls = [r["href"] for r in results if "href" in r]
                
            if not urls:
                logger.warning(f"No results found for query: {query}")
                return []
                
            logger.info(f"Found {len(urls)} search results using DDGS for: {query[:50]}...")
            return urls

        except Exception as e:
            logger.error(f"DDGS search failed: {e}. Falling back to Wikipedia/Arxiv...")
            # If DDG fails, try to get anything from Wikipedia as a last resort
            wiki_urls = self._search_wikipedia(query)
            if wiki_urls:
                return wiki_urls
            return self._search_arxiv(query)

    def _search_wikipedia(self, query: str) -> List[str]:
        """Search Wikipedia API and return article URLs."""
        try:
            import requests
            headers = {"User-Agent": "ResearchAgent/1.0 (research-tool; contact@example.com)"}
            url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={requests.utils.quote(query)}&limit={self.max_results}&namespace=0&format=json"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            urls = data[3] if len(data) > 3 else []
            logger.info(f"Found {len(urls)} Wikipedia results for query: {query[:50]}...")
            return urls
        except Exception as e:
            logger.error(f"Wikipedia search failed: {e}")
            return []

    def _search_arxiv(self, query: str) -> List[str]:
        """Search Arxiv API and return abstract page URLs."""
        try:
            import requests
            from bs4 import BeautifulSoup
            search_url = f"http://export.arxiv.org/api/query?search_query=all:{requests.utils.quote(query)}&start=0&max_results={self.max_results}"
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "xml")
            # Extract the <id> inside each <entry> tag (skip the top-level feed <id>)
            urls = [entry.find("id").text.strip() for entry in soup.find_all("entry") if entry.find("id")]
            logger.info(f"Found {len(urls)} Arxiv results for query: {query[:50]}...")
            return urls
        except Exception as e:
            logger.error(f"Arxiv search failed: {e}")
            return []

    def _scrape_url(self, url: str) -> Optional[ScrapedContent]:
        """Scrape content from a single URL."""
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                # Fallback to requests if trafilatura fails to fetch
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                downloaded = response.text

            content = trafilatura.extract(downloaded, include_links=False, include_images=False)
            
            if not content:
                # Fallback to bs4 if trafilatura extraction fails
                soup = BeautifulSoup(downloaded, "html.parser")
                for script in soup(["script", "style", "nav", "footer", "header"]):
                    script.decompose()
                content = soup.get_text(separator=" ", strip=True)
                
            soup = BeautifulSoup(downloaded, "html.parser")
            title = soup.title.string if soup.title else url

            scraped = ScrapedContent(
                url=url,
                title=title.strip() if isinstance(title, str) else str(title),
                content=content[:5000] if content else "",
                metadata={"source": "smart_scrape"},
            )

            logger.debug(f"Successfully scraped: {url}")
            return scraped

        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return None

    def _generate_sub_queries(self, query: str, missing_context: str = "") -> List[Dict[str, str]]:
        """Generate focused search queries and route to the best search engine."""
        
        # Escape any curly braces in the inputs to prevent f-string/format errors
        safe_query = query.replace("{", "(").replace("}", ")")
        safe_missing = missing_context.replace("{", "(").replace("}", ")")
        
        prompt = f"""
        You are an expert researcher routing queries to the best search engine. Break down the following complex research request into 2-3 specific, optimized search engine queries.
        
        Original Request: {safe_query}
        """
        if safe_missing:
            prompt += f"\n\nWe already have some information, but are specifically missing this context: {safe_missing}\nGenerate queries to find ONLY this missing information."
            
        prompt += """
        
        For each query, select the BEST source:
        - "arxiv": For AI/ML papers, physics, math, and deep technical/academic research.
        - "wikipedia": For general facts, historical events, well-known entities, or overviews.
        - "duckduckgo": For news, current events, business models, blogs, or general web searches.

        Respond ONLY with a valid JSON array of objects. Example:
        [
            {"query": "attention is all you need architecture", "source": "arxiv"},
            {"query": "history of the roman empire", "source": "wikipedia"},
            {"query": "latest SaaS pricing models 2024", "source": "duckduckgo"}
        ]
        """
        
        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3},
                format="json"
            )
            
            content = response["message"]["content"].strip()
            import json
            queries = json.loads(content)
            return queries[:3]
        except Exception as e:
            logger.error(f"Failed to generate sub-queries: {e}")
            return [{"query": query, "source": "duckduckgo"}]

    def _evaluate_findings(self, query: str, findings: List[Dict]) -> Dict:
        """Evaluate if the gathered findings are sufficient to answer the query."""
        if not findings:
            return {"is_sufficient": False, "missing_info": "No information gathered yet."}
            
        findings_summary = "\n\n".join([f"Source: {f['url']}\nSummary: {f['summary'][:500]}" for f in findings])
        
        prompt = f"""
        You are a research evaluator. Evaluate if the gathered findings are sufficient to fully answer the original research request.
        
        Original Request: {query}
        
        Gathered Findings:
        {findings_summary}
        
        Determine if the findings cover all aspects of the original request.
        
        Respond ONLY with a valid JSON object. Example:
        {{"is_sufficient": false, "missing_info": "specific pricing details for CRM software"}}
        
        If sufficient, set "is_sufficient" to true and "missing_info" to an empty string.
        """
        
        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.3},
                format="json"
            )
            
            content = response["message"]["content"].strip()
            import json
            evaluation = json.loads(content)
            
            return {
                "is_sufficient": evaluation.get("is_sufficient", True),
                "missing_info": evaluation.get("missing_info", "")
            }
        except Exception as e:
            logger.error(f"Failed to evaluate findings: {e}")
            return {"is_sufficient": True, "missing_info": ""} # Default to sufficient on error to avoid infinite loops

    def _get_relevant_chunks(self, text: str, query: str, top_k: int = 4) -> str:
        """Embed text locally and retrieve the most relevant chunks using ChromaDB."""
        if not self.chroma_client:
            return text[:3000]
            
        try:
            import uuid
            collection_name = f"temp_{uuid.uuid4().hex}"
            collection = self.chroma_client.create_collection(name=collection_name)
            
            chunks = self.text_splitter.split_text(text)
            if not chunks:
                return text[:3000]
                
            embeddings = []
            for chunk in chunks:
                response = self.client.embeddings(model=self.embed_model, prompt=chunk)
                embeddings.append(response["embedding"])
                
            collection.add(
                documents=chunks,
                embeddings=embeddings,
                ids=[f"chunk_{i}" for i in range(len(chunks))]
            )
            
            query_emb = self.client.embeddings(model=self.embed_model, prompt=query)["embedding"]
            results = collection.query(query_embeddings=[query_emb], n_results=min(top_k, len(chunks)))
            
            self.chroma_client.delete_collection(name=collection_name)
            
            if results and results["documents"] and results["documents"][0]:
                return "\n\n...[semantic gap]...\n\n".join(results["documents"][0])
            return text[:3000]
        except Exception as e:
            logger.error(f"Local RAG chunking failed: {e}")
            return text[:3000]

    def _extract_relevant_info(self, query: str, contents: List[ScrapedContent]) -> List[Dict]:
        """Use LLM to extract relevant information from scraped content."""
        relevant_findings = []

        for scraped in contents:
            if len(scraped.content) > 3000:
                logger.info(f"Document {scraped.url} is large. Performing semantic chunking...")
                context_text = self._get_relevant_chunks(scraped.content, query)
            else:
                context_text = scraped.content
                
            prompt = f"""
            Extract key findings from the following content related to the research query.
            
            Query: {query}
            
            Content from {scraped.url}:
            {context_text}
            
            Provide a concise summary of the most relevant information, focusing on facts, 
            statistics, and insights directly related to the query.
            """

            try:
                response = self.client.chat(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert research analyst. Extract key findings from web content."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    options={"temperature": 0.7}
                )

                finding = {
                    "url": scraped.url,
                    "title": scraped.title,
                    "summary": response["message"]["content"],
                    "scraped_at": scraped.scraped_at.isoformat(),
                }
                relevant_findings.append(finding)

            except Exception as e:
                logger.error(f"LLM extraction failed for {scraped.url}: {e}")
                # Store raw content if LLM extraction fails
                relevant_findings.append({
                    "url": scraped.url,
                    "title": scraped.title,
                    "summary": scraped.content[:1000],
                    "scraped_at": scraped.scraped_at.isoformat(),
                })

        return relevant_findings

    def research(self, query: str, query_id: Optional[int] = None, max_iterations: int = 3, progress_callback=None) -> Dict:
        """
        Execute an iterative deep research cycle: plan, search, scrape, extract, and evaluate.
        
        Args:
            query: The research query string
            query_id: Optional database query ID for storing results
            max_iterations: Maximum number of research loops
            progress_callback: Function to call with progress updates
            
        Returns:
            Dictionary containing research findings
        """
        logger.info(f"Starting deep research for query: {query}")
        
        all_findings = []
        visited_urls = set()
        missing_context = ""
        
        for iteration in range(max_iterations):
            logger.info(f"--- Research Iteration {iteration + 1}/{max_iterations} ---")
            if progress_callback:
                progress_callback(f"Research loop {iteration + 1}/{max_iterations}: Planning queries...")
                
            sub_queries = self._generate_sub_queries(query, missing_context)
            if not sub_queries:
                break
                
            logger.info(f"Generated sub-queries: {sub_queries}")
            
            scraped_contents = []
            for item in sub_queries:
                sub_query = item.get("query", "")
                source = item.get("source", "duckduckgo")
                
                if progress_callback:
                    progress_callback(f"Searching {source} for: {sub_query}")
                    
                if source == "arxiv":
                    urls = self._search_arxiv(sub_query)
                elif source == "wikipedia":
                    urls = self._search_wikipedia(sub_query)
                else:
                    urls = self._search_duckduckgo(sub_query)
                
                for url in urls[:self.max_results]:
                    if url in visited_urls:
                        continue
                        
                    visited_urls.add(url)
                    if progress_callback:
                        progress_callback(f"Scraping source: {url[:50]}...")
                    content = self._scrape_url(url)
                    
                    if content:
                        scraped_contents.append(content)
                        if query_id and self.db:
                            self.db.store_finding(
                                query_id=query_id,
                                source_url=url,
                                title=content.title,
                                content=content.content[:2000],
                            )
            
            if not scraped_contents and iteration == 0:
                logger.warning("No content could be scraped on first iteration")
                return {"query": query, "findings": [], "status": "no_results"}
                
            if scraped_contents:
                if progress_callback:
                    progress_callback(f"Extracting insights from {len(scraped_contents)} new sources...")
                new_findings = self._extract_relevant_info(query, scraped_contents)
                all_findings.extend(new_findings)
                
            if progress_callback:
                progress_callback("Evaluating gathered information...")
            evaluation = self._evaluate_findings(query, all_findings)
            
            if evaluation["is_sufficient"]:
                logger.info("Findings deemed sufficient.")
                break
                
            missing_context = evaluation["missing_info"]
            logger.info(f"Findings insufficient. Missing: {missing_context}")
            
        result = {
            "query": query,
            "findings": all_findings,
            "sources_count": len(all_findings),
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
        }

        logger.info(f"Deep research completed: {len(all_findings)} findings from {len(visited_urls)} sources")
        return result
