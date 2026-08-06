"""Main entry point for Autonomous Multi-Agent Research System."""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("research_system.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


def initialize_database():
    """Initialize PostgreSQL database connection and schema."""
    try:
        from database.connection import DatabaseConnection

        db = DatabaseConnection()
        db.initialize_schema()
        logger.info("Database initialized successfully")
        return db
    except Exception as e:
        logger.warning(f"Database initialization failed: {e}")
        logger.info("Continuing without database support...")
        return None


def run_research(query: str, use_database: bool = True):
    """
    Run the full research workflow for a query.
    
    Args:
        query: Research query string
        use_database: Whether to use database storage
    """
    from workflow import ResearchWorkflow

    print(f"\n{'='*80}")
    print(f"RESEARCH QUERY: {query}")
    print(f"{'='*80}\n")

    # Initialize components
    db = initialize_database() if use_database else None
    workflow = ResearchWorkflow(db_connection=db)

    print("⏳ Starting research workflow...")
    print("  → Validating query...")
    print("  → Searching and scraping web sources...")
    print("  → Extracting relevant information...")
    print("  → Synthesizing report...")
    print("  → Finalizing results...\n")

    # Execute workflow
    result = workflow.execute(query)

    # Display results
    status = result.get("status", "unknown")
    findings_count = result.get("findings_count", 0)
    report_path = result.get("report_path", "N/A")

    print(f"{'='*80}")
    print(f"WORKFLOW COMPLETE")
    print(f"{'='*80}")
    print(f"Status: {status.upper()}")
    print(f"Sources Analyzed: {findings_count}")
    print(f"Report Path: {report_path}")

    if result.get("monitor_status"):
        monitor = result["monitor_status"]
        print(f"Execution Time: {monitor.get('elapsed_seconds', 0):.2f}s")
        print(f"Iterations: {monitor.get('iterations', 0)}")

    if result.get("error"):
        print(f"Error: {result['error']}")

    print(f"{'='*80}\n")

    # Display report preview
    if result.get("report") and status in ["written", "completed"]:
        report = result["report"]
        preview_length = 500
        print("REPORT PREVIEW:")
        print("-" * 80)
        print(report[:preview_length])
        if len(report) > preview_length:
            print(f"\n... [Full report saved to: {report_path}]")
        print("-" * 80)

    return result


def show_historical_queries(limit: int = 10):
    """Display historical research queries from database."""
    try:
        from database.connection import DatabaseConnection

        db = DatabaseConnection()
        queries = db.get_historical_queries(limit=limit)

        if not queries:
            print("No historical queries found.")
            return

        print(f"\n{'='*80}")
        print(f"HISTORICAL QUERIES (Last {len(queries)})")
        print(f"{'='*80}")

        for q in queries:
            print(f"\nID: {q['id']}")
            print(f"Query: {q['query']}")
            print(f"Date: {q['created_at']}")
            print(f"Status: {q['status']}")
            if q.get("result_summary"):
                print(f"Summary: {q['result_summary'][:100]}...")
            print("-" * 40)

    except Exception as e:
        logger.error(f"Failed to retrieve historical queries: {e}")
        print(f"Error: {e}")


def main():
    """Main CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Autonomous Multi-Agent Research System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py research "AI market trends 2024"
  python main.py history --limit 20
  python main.py research "renewable energy innovations" --no-db
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Research command
    research_parser = subparsers.add_parser("research", help="Run a new research query")
    research_parser.add_argument("query", type=str, help="Research query string")
    research_parser.add_argument(
        "--no-db", action="store_true", help="Disable database storage"
    )

    # History command
    history_parser = subparsers.add_parser("history", help="Show historical queries")
    history_parser.add_argument(
        "--limit", type=int, default=10, help="Number of queries to display"
    )

    args = parser.parse_args()

    if args.command == "research":
        run_research(args.query, use_database=not args.no_db)
    elif args.command == "history":
        show_historical_queries(limit=args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
