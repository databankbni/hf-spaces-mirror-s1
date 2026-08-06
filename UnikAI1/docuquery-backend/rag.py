import os
import pandas as pd
from PyPDF2 import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from langchain_nvidia_ai_endpoints import ChatNVIDIA, NVIDIAEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

# Using NVIDIA's state-of-the-art retrieval embedding model
embedding_model = NVIDIAEmbeddings(model="nvidia/nv-embed-v1")

# Initialize language model
llm = ChatNVIDIA(
    model="nvidia/nemotron-3-super-120b-a12b",
    temperature=1,
    top_p=0.95,
    max_tokens=16384,
    reasoning_budget=16384,
    chat_template_kwargs={"enable_thinking": True},
)

vectorstore = None
retriever = None

def process_file_content(file_bytes: bytes, filename: str) -> str:
    """Processes uploaded file bytes and updates the knowledge base."""
    global vectorstore, retriever

    text = ""
    # Process by extension
    if filename.endswith(".txt"):
        text = file_bytes.decode("utf-8")
    elif filename.endswith(".pdf"):
        import io
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        text = "\n".join([page.extract_text() or "" for page in reader.pages]).strip()
    elif filename.endswith(".csv"):
        import io
        csv_file = io.BytesIO(file_bytes)
        df = pd.read_csv(csv_file)
        text = df.to_string()
    else:
        raise ValueError("Unsupported file format.")

    if not text:
        raise ValueError("No readable text found in the file.")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", " ", ""],
        length_function=len
    )

    document_texts = text_splitter.split_text(text)
    documents = [
        Document(page_content=chunk, metadata={"source": f"{filename}_chunk_{i}"})
        for i, chunk in enumerate(document_texts)
    ]

    vectorstore = FAISS.from_documents(documents, embedding_model)
    retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 10})

    return f"File '{filename}' processed successfully! {len(document_texts)} chunks added to FAISS."

def retrieve_relevant_text(query: str) -> str:
    global retriever
    if retriever is None:
        return ""
    docs = retriever.invoke(query)
    context = "\n\n".join(
        [f"[{doc.metadata['source']}]: {doc.page_content}" for doc in docs]
    )
    return context

def get_chat_response(message: str, history: list) -> str:
    """Generates response using retrieved context and strict system prompts."""
    context = retrieve_relevant_text(message)

    if not context.strip():
        return "I could not find that information in the provided document."

    messages = [
        {
            "role": "system",
            "content": f"""You are a helpful assistant. You must answer only using the information in the provided document context.
If the answer is not explicitly found in the document, say "I could not find that information in the provided document."
Strictly avoid using any external knowledge or making assumptions.

Document Context:
{context}
"""
        }
    ]

    for msg in history:
        messages.append(msg)

    messages.append({"role": "user", "content": message})

    response = llm.invoke(messages)
    return response.content
    