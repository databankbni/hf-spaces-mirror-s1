import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from config import Config


class SchemaRAG:
    """
    RAG pipeline for F1 database schema.
    Embeds table/column metadata using sentence-transformers and
    retrieves relevant schema context via FAISS (Facebook AI Similarity Search).
    """

    def __init__(self):
        """Initialize the embedding model and FAISS index."""
        print("[RAG] Loading embedding model (all-MiniLM-L6-v2)...")
        self.embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        self._documents = []       # List of document text strings
        self._metadata = []        # List of metadata dicts
        self._index = None         # FAISS index
        self._is_indexed = False
        print("[RAG] Embedding model loaded.")

    # Tables to exclude from RAG indexing (non-F1 system tables)
    EXCLUDED_TABLES = {"messages", "conversations"}

    # Semantic enrichment: extra keywords to improve FAISS retrieval
    # These help match user queries to the correct tables
    SEMANTIC_ENRICHMENT = {
        "results": (
            "Use this table for: race wins, podiums, finishing positions, "
            "race outcomes, who won, who finished first/second/third, "
            "driver points per race, fastest laps, grid positions, "
            "total wins, career stats, race results, DNF, did not finish"
        ),
        "drivers": (
            "Use this table for: driver names, nationalities, date of birth, "
            "driver lookup, forename surname, who is a driver, "
            "Hamilton, Verstappen, Schumacher, Vettel, Alonso, Norris, Leclerc, "
            "Sainz, Pérez, Russell, Bottas, Räikkönen, Prost, Senna, all drivers, "
            "compare drivers, how many wins does a driver have, career stats, "
            "driver information, which driver, who won, who finished"
        ),
        "races": (
            "Use this table for: race calendar, Grand Prix names, race dates, "
            "race schedule, which year, season, round number, "
            "race location, when was a race held"
        ),
        "circuits": (
            "Use this table for: circuit names, track locations, country, "
            "where is a circuit, which country, track in Japan, Italy, UK, USA, "
            "Monza, Silverstone, Spa, Monaco, Suzuka, Interlagos, COTA, Bahrain, "
            "Jeddah, Albert Park, Hungaroring, Zandvoort, Imola, Baku, Singapore, "
            "Red Bull Ring, Paul Ricard, Barcelona, Montreal, Sakhir, Yas Marina, "
            "circuit location, Grand Prix venue, race track, where was a race held"
        ),
        "constructors": (
            "Use this table for: team names, constructor names, "
            "Ferrari, Red Bull, Mercedes, McLaren, Williams, Alpine, Haas, "
            "Alfa Romeo, AlphaTauri, Aston Martin, Racing Point, Renault, "
            "team nationality, team lookup, how many points did a team score, "
            "team performance, constructor information, which team"
        ),
        "qualifying": (
            "Use this table for: qualifying times, Q1 Q2 Q3 times, "
            "pole position, qualifying results, grid order, "
            "fastest qualifier, qualifying lap times"
        ),
        "driver_standings": (
            "Use this table for: championship standings, points table, "
            "championship position after each race, cumulative points, "
            "title race, who leads the championship, world championship"
        ),
        "constructor_standings": (
            "Use this table for: constructors championship, team standings, "
            "team points after each race, constructors title"
        ),
        "pit_stops": (
            "Use this table for: pit stop times, pit stop duration, "
            "number of pit stops, pit strategy, pit stop milliseconds"
        ),
        "lap_times": (
            "Use this table for: lap times, individual lap data, "
            "lap by lap analysis, fastest lap in a race, lap duration"
        ),
        "sprint_results": (
            "Use this table for: sprint race results, sprint qualifying, "
            "sprint race finishing positions, sprint points"
        ),
        "constructor_results": (
            "Use this table for: constructor results per race, "
            "team race results, constructor points"
        ),
        "status": (
            "Use this table for: race status codes, DNF reasons, "
            "finished, accident, engine failure, retired"
        ),
        "seasons": (
            "Use this table for: F1 seasons, season URLs, year list"
        ),
    }

    def build_schema_documents(self, schema_info: list[dict]) -> list[dict]:
        """
        Convert raw schema metadata into rich text documents for embedding.
        Each document describes one table comprehensively.
        """
        documents = []

        for table in schema_info:
            table_name = table["table_name"]

            # Skip non-F1 system tables
            if table_name in self.EXCLUDED_TABLES:
                print(f"[RAG] Skipping system table: {table_name}")
                continue

            # Build column descriptions
            col_lines = []
            primary_keys = []
            for col in table["columns"]:
                col_name = col["COLUMN_NAME"]
                data_type = col["DATA_TYPE"]
                nullable = "nullable" if col["IS_NULLABLE"] == "YES" else "not null"
                key_info = ""
                if col["COLUMN_KEY"] == "PRI":
                    key_info = " (PRIMARY KEY)"
                    primary_keys.append(col_name)
                elif col["COLUMN_KEY"] == "MUL":
                    key_info = " (INDEXED)"
                elif col["COLUMN_KEY"] == "UNI":
                    key_info = " (UNIQUE)"

                col_lines.append(f"  - {col_name}: {data_type}, {nullable}{key_info}")

            # Build foreign key descriptions
            fk_lines = []
            for fk in table["foreign_keys"]:
                fk_lines.append(
                    f"  - {fk['COLUMN_NAME']} → {fk['REFERENCED_TABLE_NAME']}.{fk['REFERENCED_COLUMN_NAME']}"
                )

            # Build sample data preview
            sample_lines = []
            if table["sample_rows"]:
                for i, row in enumerate(table["sample_rows"][:3]):
                    clean_row = {
                        k: v for k, v in row.items()
                        if v != "<binary>" and v is not None
                    }
                    sample_lines.append(f"  Row {i + 1}: {clean_row}")

            # Compose the full document
            doc = f"Table: {table_name}\n"
            doc += f"Row count: {table['row_count']}\n"

            # Add semantic enrichment keywords
            if table_name in self.SEMANTIC_ENRICHMENT:
                doc += f"Description: {self.SEMANTIC_ENRICHMENT[table_name]}\n"

            doc += f"Columns:\n" + "\n".join(col_lines) + "\n"
            if fk_lines:
                doc += f"Foreign Keys:\n" + "\n".join(fk_lines) + "\n"
            if sample_lines:
                doc += f"Sample Data:\n" + "\n".join(sample_lines) + "\n"

            documents.append({
                "id": f"table_{table_name}",
                "text": doc,
                "metadata": {"table_name": table_name},
            })

        return documents

    def index_schema(self, schema_info: list[dict]):
        """Embed and store schema documents in FAISS index."""
        if self._is_indexed:
            print("[RAG] Schema already indexed, skipping.")
            return

        documents = self.build_schema_documents(schema_info)

        if not documents:
            print("[RAG] No schema documents to index.")
            return

        self._documents = [doc["text"] for doc in documents]
        self._metadata = [doc["metadata"] for doc in documents]

        print(f"[RAG] Indexing {len(documents)} table descriptions...")

        # Encode all documents
        embeddings = self.embed_model.encode(self._documents, convert_to_numpy=True)
        embeddings = embeddings.astype(np.float32)

        # Normalize for cosine similarity
        faiss.normalize_L2(embeddings)

        # Create FAISS index (Inner Product on normalized vectors = cosine similarity)
        dimension = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dimension)
        self._index.add(embeddings)

        self._is_indexed = True
        print(f"[RAG] Schema indexed successfully ({len(documents)} tables in FAISS).")

    def retrieve(self, question: str, top_k: int = None) -> str:
        """
        Retrieve the most relevant schema context for a user question.

        Args:
            question: Natural language question
            top_k: Number of top results to return

        Returns:
            Combined schema context string
        """
        if top_k is None:
            top_k = Config.TOP_K_SCHEMA_RESULTS

        if not self._is_indexed or self._index is None:
            return "Schema not indexed yet. Please wait for initialization."

        # Encode and normalize query
        query_embedding = self.embed_model.encode([question], convert_to_numpy=True)
        query_embedding = query_embedding.astype(np.float32)
        faiss.normalize_L2(query_embedding)

        # Search FAISS index
        top_k = min(top_k, len(self._documents))
        scores, indices = self._index.search(query_embedding, top_k)

        # Get retrieved table names and docs
        retrieved_names = set()
        relevant_docs = []
        for i in indices[0]:
            if i < len(self._documents):
                relevant_docs.append(self._documents[i])
                retrieved_names.add(self._metadata[i]["table_name"])

        # Apply co-occurrence rules — add related tables
        co_occur_tables = self._get_co_occurring_tables(retrieved_names)
        for table_name in co_occur_tables:
            idx = self._get_table_index(table_name)
            if idx is not None:
                relevant_docs.append(self._documents[idx])

        if not relevant_docs:
            return "No relevant schema found."

        context = "\n---\n".join(relevant_docs)
        return context

    def get_all_table_names(self) -> list[str]:
        """Get all indexed table names."""
        return [m["table_name"] for m in self._metadata]

    def retrieve_with_scores(self, question: str, top_k: int = None) -> list[dict]:
        """
        Retrieve relevant tables with similarity scores for RAG evaluation.

        Returns:
            List of {"table": table_name, "score": float} sorted by score descending
        """
        if top_k is None:
            top_k = Config.TOP_K_SCHEMA_RESULTS

        if not self._is_indexed or self._index is None:
            return []

        # Encode and normalize query
        query_embedding = self.embed_model.encode([question], convert_to_numpy=True)
        query_embedding = query_embedding.astype(np.float32)
        faiss.normalize_L2(query_embedding)

        # Search FAISS index
        top_k = min(top_k, len(self._documents))
        scores, indices = self._index.search(query_embedding, top_k)

        results = []
        retrieved_names = set()
        for i, idx in enumerate(indices[0]):
            if idx < len(self._metadata):
                table_name = self._metadata[idx]["table_name"]
                results.append({
                    "table": table_name,
                    "score": round(float(scores[0][i]), 4),
                })
                retrieved_names.add(table_name)

        # Apply co-occurrence rules — add related tables with score marker
        co_occur_tables = self._get_co_occurring_tables(retrieved_names)
        for table_name in co_occur_tables:
            results.append({
                "table": table_name,
                "score": -1.0,  # marker: added by co-occurrence, not FAISS
            })

        return results

    # ── Co-occurrence Rules ──────────────────────────────────

    # If table A is retrieved, also include table B (and vice versa)
    TABLE_CO_OCCURRENCE = {
        "results":                ["drivers"],
        "drivers":                ["results"],
        "races":                  ["circuits"],
        "circuits":               ["races"],
        "driver_standings":       ["drivers", "races"],
        "constructor_standings":  ["constructors", "races"],
        "qualifying":             ["drivers", "races", "circuits"],
        "pit_stops":              ["results", "races"],
        "lap_times":              ["drivers", "races"],
        "constructor_results":    ["constructors", "races"],
    }

    def _get_co_occurring_tables(self, retrieved_names: set) -> list[str]:
        """Return tables that should be auto-included based on co-occurrence rules."""
        to_add = []
        for table in retrieved_names:
            for co_table in self.TABLE_CO_OCCURRENCE.get(table, []):
                if co_table not in retrieved_names and co_table not in to_add:
                    to_add.append(co_table)
        return to_add

    def _get_table_index(self, table_name: str):
        """Find the index of a table in the metadata list."""
        for i, m in enumerate(self._metadata):
            if m["table_name"] == table_name:
                return i
        return None

