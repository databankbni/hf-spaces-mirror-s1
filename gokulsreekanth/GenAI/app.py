import streamlit as st
import tempfile
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

st.set_page_config(page_title="Enterprise GenAI DocQuery", layout="wide")

st.title("📄 Enterprise GenAI Document Assistant")
st.caption("AICTE | IBM SkillsBuild Internship Capstone Project")

# Sidebar for Document Upload
with st.sidebar:
    st.header("Upload Knowledge Base")
    uploaded_files = st.file_uploader("Upload PDF files", type=["pdf"], accept_multiple_files=True)
    process_button = st.button("Process Documents")

# Initialize Session States
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# Process Uploaded Documents
if process_button and uploaded_files:
    with st.spinner("Processing & indexing documents..."):
        all_docs = []
        for file in uploaded_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(file.getvalue())
                loader = PyPDFLoader(tmp_file.name)
                all_docs.extend(loader.load())
        
        # Split text into chunks
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100)
        chunks = text_splitter.split_documents(all_docs)
        
        # Generate Vector Embeddings
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        st.session_state.vector_store = FAISS.from_documents(chunks, embeddings)
        st.success(f"Successfully processed {len(chunks)} text chunks!")

# Chat Interface
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask a question about your documents:"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    if st.session_state.vector_store is not None:
        results = st.session_state.vector_store.similarity_search(prompt, k=3)
        context = "\n\n".join([doc.page_content for doc in results])
        
        response = f"**Synthesized Answer (Context-Grounded):**\n\nBased on your documents:\n\n> {context[:500]}...\n\n*(Extracted from matched sources)*"
    else:
        response = "Please upload and process at least one PDF document in the sidebar first."

    with st.chat_message("assistant"):
        st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
