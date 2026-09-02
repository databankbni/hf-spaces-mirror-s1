import os
import json
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_pinecone import PineconeVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
import db

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'characters_config.json')

class MahabharataCharacter:
    def __init__(self, character_name, user_id="default", look_back_k=3):
        self.character_name = character_name.capitalize()
        self.user_id = user_id
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.pinecone_api_key = os.getenv("PINECONE_API_KEY")
        
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        if not self.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY not found in environment variables")
        
        # Load character config
        self.config = self._load_config()
        self.traits = self.config.get("traits", "A warrior from the Mahabharata")
        self.style = self.config.get("style", "Formal and respectful")
        self.values = self.config.get("values", "Dharma and Duty")
        
        self.llm = ChatGroq(
            temperature=0.7, 
            groq_api_key=self.groq_api_key, 
            model_name="openai/gpt-oss-120b"
        )
        
        self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        self.index_name = "mahabharata-characters"
        
        self.vectorstore = PineconeVectorStore(
            index_name=self.index_name,
            embedding=self.embeddings,
            pinecone_api_key=self.pinecone_api_key
        )
        
        # Shared pool retrieval: no hard character filter (so passages from any
        # book are reachable), but the query is biased with the character's name
        # at runtime so their own passages rank highest. k is larger since we
        # now retrieve from full books, not just short memory snippets.
        self.retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": max(look_back_k, 6)}
        )
        
        self.chain = self._build_chain()

    def _load_config(self):
        try:
            with open(CONFIG_PATH, 'r') as f:
                data = json.load(f)
                return data.get(self.character_name, {})
        except FileNotFoundError:
            print(f"Warning: Config file not found at {CONFIG_PATH}")
            return {}

    def _get_history_string(self):
        # Retrieve persistent history from SQLite
        history = db.get_chat_history(self.user_id, self.character_name, limit=5)
        formatted_history = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in history])
        return formatted_history

    def _build_chain(self):
        system_template = """You are {character_name} from the Mahabharata.
        
        PERSONALITY PROFILE:
        - Traits: {traits}
        - Speaking Style: {style}
        - Core Values: {values}
        
        INSTRUCTIONS:
        1. Speak strictly in the first person ("I"). Never break character; you ARE {character_name}.
        2. Ground your answer in the SOURCE PASSAGES below. They are drawn from the texts of your life and are your primary source of truth. Prefer specific details, names, and events found there.
        3. If the passages do not contain the answer, you may speak from the well-known events of your own life, but do NOT invent specific facts, names, or events. It is better to say you do not recall than to fabricate.
        4. Weave the passages into your own voice; do not quote them mechanically or mention that they are "passages".
        5. EMBODY your specific traits and values in every sentence.

        SOURCE PASSAGES (from the books and memories of your life):
        {context}
        
        CHAT HISTORY:
        {chat_history}
        
        USER INPUT:
        {question}
        
        YOUR RESPONSE:"""
        
        prompt = ChatPromptTemplate.from_template(system_template)

        def format_docs(docs):
            return "\n\n".join(doc.page_content for doc in docs)

        # Step 1: retrieve documents using a name-biased query so this
        # character's own passages surface first from the shared pool.
        retrieve_docs = RunnableLambda(
            lambda x: self.retriever.invoke(f"{self.character_name}: {x['question']}")
        )

        # Step 2: generate the answer from the retrieved docs + persona + history.
        generate_answer = (
            {
                "context": lambda x: format_docs(x["docs"]),
                "question": lambda x: x["question"],
                "chat_history": lambda x: self._get_history_string(),
                "character_name": lambda x: self.character_name,
                "traits": lambda x: self.traits,
                "style": lambda x: self.style,
                "values": lambda x: self.values
            }
            | prompt
            | self.llm
            | StrOutputParser()
        )

        # Keep BOTH the answer and the retrieved docs so we can cite sources.
        # This is the classic "return source documents" RAG pattern in LCEL.
        rag_chain = (
            RunnablePassthrough.assign(docs=retrieve_docs)
            | RunnablePassthrough.assign(answer=generate_answer)
        )

        return rag_chain

    def _extract_sources(self, docs):
        """De-duplicate the human-readable source of each retrieved chunk."""
        sources, seen = [], set()
        for d in docs:
            src = d.metadata.get("source", "")
            if not src or src in seen:
                continue
            seen.add(src)
            # Prettify the hand-written memory files; books already have titles.
            if src.endswith("_memories.txt"):
                src = f"{src.split('_')[0].capitalize()} — personal memory"
            sources.append(src)
        return sources

    def chat(self, user_input):
        # Save user message
        db.save_message(self.user_id, self.character_name, "user", user_input)

        # Run the RAG chain -> {question, docs, answer}
        result = self.chain.invoke({"question": user_input})
        answer = result["answer"]
        sources = self._extract_sources(result["docs"])

        # Save bot response (text only)
        db.save_message(self.user_id, self.character_name, "assistant", answer)

        return {"response": answer, "sources": sources}
