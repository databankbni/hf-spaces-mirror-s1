"""Simple workflow orchestration for multi-agent research system."""

import logging
from typing import Optional
from datetime import datetime

from agents.researcher import ResearcherAgent
from agents.writer import WriterAgent
from database.connection import DatabaseConnection
from utils.llmops import AgentMonitor, validate_agent_input

logger = logging.getLogger(__name__)


class ResearchWorkflow:
    """Orchestrates Researcher and Writer agents."""

    def __init__(self, db_connection: Optional[DatabaseConnection] = None, model_name: Optional[str] = None):
        self.db = db_connection
        self.researcher = ResearcherAgent(db_connection=db_connection, model_name=model_name)
        self.writer = WriterAgent(db_connection=db_connection, model_name=model_name)
        self.monitor = AgentMonitor()

    def execute(self, query: str, progress_callback=None) -> dict:
        """
        Execute the full research workflow.
        
        Args:
            query: The research query string
            
        Returns:
            Dictionary containing workflow results
        """
        logger.info(f"Executing workflow for query: {query}")
        self.monitor.reset()

        result = {
            "query": query,
            "status": "pending",
            "research_findings": [],
            "report": None,
            "report_path": None,
            "query_id": None,
            "error": None,
            "timestamp": datetime.now().isoformat(),
            "monitor_status": None,
        }

        try:
            # Step 1: Validate input
            logger.info("Step 1: Validating query")
            if progress_callback:
                progress_callback("Validating query input...")
            self.monitor.check_iteration_limit()
            self.monitor.check_timeout()

            if not validate_agent_input(query, max_length=2000):
                result["status"] = "failed"
                result["error"] = "Invalid query input"
                return result

            # Store query in database
            if self.db:
                try:
                    query_id = self.db.store_query(query)
                    result["query_id"] = query_id
                    logger.info(f"Stored query with ID: {query_id}")
                except Exception as e:
                    logger.warning(f"Failed to store query: {e}")

            result["status"] = "validating"

            # Step 2: Research
            logger.info("Step 2: Starting research")
            self.monitor.check_iteration_limit()
            self.monitor.check_timeout()

            research_result = self.researcher.research(
                query=query,
                query_id=result.get("query_id"),
                progress_callback=progress_callback,
            )

            if research_result.get("status") == "no_results":
                result["status"] = "completed"
                result["error"] = "No research findings available"
                result["monitor_status"] = self.monitor.get_status()
                return result

            result["research_findings"] = research_result.get("findings", [])
            result["status"] = "researched"

            # Step 3: Write report
            logger.info("Step 3: Writing report")
            if progress_callback:
                progress_callback("Synthesizing final report...")
            self.monitor.check_iteration_limit()

            if not result.get("research_findings"):
                logger.warning("No findings to write report on")
                result["report"] = f"# Research Report\n\n**Query:** {query}\n\n**Status:** No findings to report\n"
                result["status"] = "completed_no_findings"
            else:
                report_result = self.writer.synthesize_report(
                    query=query,
                    findings=result["research_findings"],
                    query_id=result.get("query_id"),
                )

                if report_result.get("status") == "failed":
                    result["status"] = "failed"
                    result["error"] = f"Report generation failed: {report_result.get('error')}"
                    return result

                result["report"] = report_result.get("report")
                result["report_path"] = report_result.get("report_path")
                result["status"] = "written"

            # Step 4: Finalize
            logger.info("Step 4: Finalizing")
            if progress_callback:
                progress_callback("Finalizing research workflow...")
            if result.get("query_id") and self.db:
                try:
                    self.db.update_query_status(
                        query_id=result["query_id"],
                        status=result["status"],
                        result_summary=result.get("error") or f"Report with {len(result['research_findings'])} findings",
                        report_path=result.get("report_path"),
                    )
                except Exception as e:
                    logger.warning(f"Failed to update query status: {e}")

            result["timestamp"] = datetime.now().isoformat()
            result["monitor_status"] = self.monitor.get_status()

            logger.info(f"Workflow completed with status: {result['status']}")
            return result

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            result["status"] = "failed"
            result["error"] = str(e)
            result["monitor_status"] = self.monitor.get_status()
            return result
