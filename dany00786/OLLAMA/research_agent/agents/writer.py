"""Writer Agent - Synthesizes research findings into reports."""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

import ollama
from dotenv import load_dotenv

from database.connection import DatabaseConnection

load_dotenv()

logger = logging.getLogger(__name__)


class WriterAgent:
    """Agent responsible for synthesizing research findings into coherent reports."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        host: Optional[str] = None,
        db_connection: Optional[DatabaseConnection] = None,
    ):
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", "qwen2:0.5b")
        self.host = host or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = ollama.Client(host=self.host)
        self.db = db_connection
        self.output_dir = Path("reports")
        self.output_dir.mkdir(exist_ok=True)

    def _generate_report_structure(self, query: str, findings: List[Dict]) -> Dict:
        """Use LLM to determine the best structure for the report."""
        structure_prompt = f"""
        Based on the following research query and findings, suggest a report structure.
        
        Query: {query}
        Number of findings: {len(findings)}
        
        Provide a structured outline with:
        1. Executive Summary
        2. Key sections (3-5 main topics)
        3. Conclusion and Recommendations
        
        Return a JSON-like structure with section titles and brief descriptions.
        """

        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert report writer. Create a structured outline for a research report."
                    },
                    {
                        "role": "user",
                        "content": structure_prompt
                    }
                ],
                options={"temperature": 0.5}
            )
            return {"structure": response["message"]["content"]}
        except Exception as e:
            logger.error(f"Failed to generate report structure: {e}")
            return {"structure": "Standard report structure will be used"}

    def synthesize_report(
        self,
        query: str,
        findings: List[Dict],
        query_id: Optional[int] = None,
        report_format: str = "markdown",
    ) -> Dict:
        """
        Synthesize research findings into a comprehensive report.
        
        Args:
            query: The original research query
            findings: List of research findings from ResearcherAgent
            query_id: Optional database query ID
            report_format: Output format (markdown, plain_text)
            
        Returns:
            Dictionary containing the generated report
        """
        logger.info(f"Synthesizing report for query: {query[:50]}...")

        if not findings:
            logger.warning("No findings provided for report generation")
            return {
                "report": f"# Research Report\n\n**Query:** {query}\n\n**Status:** No findings available\n",
                "status": "no_findings",
            }

        # Compile findings into a formatted string
        findings_text = "\n\n".join([
            f"Source {i+1}: {f.get('title', 'Unknown')}\nURL: {f.get('url', 'N/A')}\n\n{f.get('summary', '')}"
            for i, f in enumerate(findings)
        ])

        # Generate comprehensive report
        report_prompt = f"""
        Write a comprehensive research report based on the following findings.
        
        RESEARCH QUERY: {query}
        
        FINDINGS:
        {findings_text}
        
        REPORT REQUIREMENTS:
        1. Executive Summary (2-3 paragraphs)
        2. Key Findings (Grounded strictly in the provided sources, organized by theme)
        3. Speculative Analysis & Creative Synthesis (CRITICAL: Use your advanced AI knowledge to brainstorm, extrapolate, and answer any speculative, forward-looking, or creative aspects of the query that the raw findings didn't explicitly cover. For example: proposed business models, architectural analysis, future trends, or creative ideation requested in the query.)
        4. Conclusions and Recommendations
        5. Sources Referenced
        
        FORMATTING:
        - Use markdown formatting
        - Include headers, bullet points, and numbered lists where appropriate
        - Cite sources inline using [Source N](URL) format for the Key Findings section
        - Maintain professional, analytical tone
        - Be concise but thorough
        
        Write the complete report now.
        """

        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a senior research analyst and expert report writer. "
                        "Create comprehensive, well-structured reports with proper citations."
                    },
                    {
                        "role": "user",
                        "content": report_prompt
                    }
                ],
                options={"temperature": 0.5}
            )

            report_content = response["message"]["content"]

            # Add metadata
            report_header = f"""# Research Report

**Query:** {query}
**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Sources Analyzed:** {len(findings)}

---

"""

            full_report = report_header + report_content

            # Save report to file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_query = "".join(c if c.isalnum() else "_" for c in query[:50]).lower()
            filename = f"{safe_query}_{timestamp}.md"
            report_path = self.output_dir / filename

            with open(report_path, "w", encoding="utf-8") as f:
                f.write(full_report)

            # Store in database if available
            if query_id and self.db:
                try:
                    self.db.store_report(
                        query_id=query_id,
                        report_content=full_report,
                        report_format=report_format,
                    )
                    self.db.update_query_status(
                        query_id=query_id,
                        status="completed",
                        result_summary=f"Report generated with {len(findings)} findings",
                        report_path=str(report_path),
                    )
                except Exception as e:
                    logger.error(f"Failed to store report in database: {e}")

            result = {
                "report": full_report,
                "report_path": str(report_path),
                "status": "completed",
                "findings_count": len(findings),
                "generated_at": datetime.now().isoformat(),
            }

            logger.info(f"Report generated successfully: {report_path}")
            return result

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return {
                "report": f"# Research Report\n\n**Query:** {query}\n\n**Error:** Report generation failed: {str(e)}\n",
                "status": "failed",
                "error": str(e),
            }

    def generate_executive_summary(self, query: str, findings: List[Dict]) -> str:
        """Generate a brief executive summary without a full report."""
        if not findings:
            return f"No findings available for query: {query}"

        findings_text = "\n".join([f.get("summary", "")[:500] for f in findings[:5]])

        prompt = f"""
        Write a concise executive summary (3-5 bullet points) for this research:
        
        Query: {query}
        
        Key Findings:
        {findings_text}
        
        Focus on the most important insights and actionable recommendations.
        """

        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an executive summarization expert. Create concise summaries."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                options={"temperature": 0.5}
            )
            return response["message"]["content"]
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return f"Summary unavailable for: {query}"
