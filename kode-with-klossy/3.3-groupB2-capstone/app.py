import gradio as gr
from huggingface_hub import InferenceClient
from sentence_transformers import SentenceTransformer
import torch

from urllib.parse import quote_plus


gr.set_static_paths(paths=["background.png"])


with open("knowledge.txt", "r", encoding="utf-8") as file:
    book_knowledge_base = file.read()

with open("literacycrisis_knowledge.txt", "r", encoding="utf-8") as file:
    literacycrisis_knowledge_base = file.read()

knowledge_base = book_knowledge_base + literacycrisis_knowledge_base

def preprocess_text(text):
    cleaned_text = text.strip()
    chunks = cleaned_text.split("\n")
    cleaned_chunks = []

    for chunk in chunks:
        stripped_chunk = chunk.strip()

        if stripped_chunk:
            cleaned_chunks.append(stripped_chunk)

    print(f"Number of text chunks: {len(cleaned_chunks)}")

    return cleaned_chunks


cleaned_chunks = preprocess_text(knowledge_base)


model = SentenceTransformer("all-MiniLM-L6-v2")


def create_embeddings(text_chunks):
    chunk_embeddings = model.encode(
        text_chunks,
        convert_to_tensor=True
    )

    print(chunk_embeddings.shape)

    return chunk_embeddings


chunk_embeddings = create_embeddings(cleaned_chunks)


def get_top_chunks(query, chunk_embeddings, text_chunks):
    query_embedding = model.encode(
        query,
        convert_to_tensor=True
    )

    query_embedding_normalized = (
        query_embedding / query_embedding.norm()
    )

    chunk_embeddings_normalized = (
        chunk_embeddings
        / chunk_embeddings.norm(dim=1, keepdim=True)
    )

    similarities = torch.matmul(
        chunk_embeddings_normalized,
        query_embedding_normalized
    )

    top_indices = torch.topk(
        similarities,
        k=min(3, len(text_chunks))
    ).indices

    top_chunks = []

    for index in top_indices:
        relevant_info = text_chunks[index.item()]
        top_chunks.append(relevant_info)

    return top_chunks


def build_search_query(message, history):
    conversation = []

    if history:
        for item in history:
            if isinstance(item, dict):
                if item.get("role") == "user":
                    content = item.get("content", "")

                    if isinstance(content, str):
                        conversation.append(content)

            elif isinstance(item, (list, tuple)) and len(item) >= 1:
                conversation.append(str(item[0]))

    conversation.append(message)

    return " ".join(conversation)


def add_history_to_messages(messages, history):
    if not history:
        return

    for item in history:
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content", "")

            if role in ["user", "assistant"] and isinstance(content, str):
                messages.append({
                    "role": role,
                    "content": content
                })

        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            user_message = item[0]
            assistant_message = item[1]

            if user_message:
                messages.append({
                    "role": "user",
                    "content": str(user_message)
                })

            if assistant_message:
                messages.append({
                    "role": "assistant",
                    "content": str(assistant_message)
                })


client = InferenceClient("Qwen/Qwen2.5-7B-Instruct", bill_to="kode-with-klossy")

def respond(message, history):
    search_query = build_search_query(message, history)

    rag_info = get_top_chunks(
        search_query,
        chunk_embeddings,
        cleaned_chunks
    )

    formatted_rag_info = "\n\n".join(rag_info)

    system_message = f"""
You are a friendly chatbot used to make boook recommendations. Use {formatted_rag_info} to formulate a maximum of 4 questions to understand the user's preferences, and then use {formatted_rag_info} to make a book suggestion. The only the first message you send to the user should always be "Hi, I'm BookMarked, would you like a book recommendation, or information about the literacy crisis?" After the first message, ask questions to narrow down what book the user may be interested in. Do not repeat the opening line.
"""


    messages = [
        {
            "role": "system",
            "content": system_message
        }
    ]

    add_history_to_messages(messages, history)

    messages.append({
        "role": "user",
        "content": message
    })

    response = client.chat_completion(
        messages=messages,
        max_tokens=500
    )

    return response.choices[0].message.content.strip()


# creates the library map using the user's location
def find_library(location):
    if not location or not location.strip():
        return """
        <div class="map-placeholder">
            enter a city or zip code to find nearby libraries
        </div>
        """

    search = quote_plus(f"public libraries near {location.strip()}")

    return f"""
    <iframe
        class="library-map"
        src="https://www.google.com/maps?q={search}&output=embed"
        loading="lazy"
        title="nearby public libraries">
    </iframe>
    """

    
custom_css = """
html,
body,
.gradio-container {
    min-height: 100vh !important;
    background-color: #f8dfe4 !important;
    background-image: url("/gradio_api/file=background.png") !important;
    background-repeat: repeat !important;
    background-size: 400px auto !important;
    background-position: center !important;
    background-attachment: fixed !important;
}

.library-card {
    padding: 20px;
    border-radius: 16px;
}

.library-map {
    width: 100%;
    height: 350px;
    border: none;
    border-radius: 16px;
}

.map-placeholder {
    height: 350px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid #f2d7e2;
    border-radius: 16px;
    background-color: #fffdfef0;
    text-align: center;
    padding: 20px;
}
"""


custom_theme = gr.themes.Soft(
    primary_hue="gray",
    secondary_hue="gray",
    neutral_hue="stone"
).set(
    button_primary_background_fill="#F8D9E5",
    button_primary_background_fill_hover="#F4C7D9",
    button_primary_border_color="#F8D9E5",
    button_primary_text_color="#5F4450",

    button_secondary_background_fill="#FCECF3",
    button_secondary_background_fill_hover="#F8DDE8",
    button_secondary_border_color="#F4CEDD",

    color_accent="#F6D7E4",

    body_background_fill="#FFF9FC",
    block_background_fill="#FFFDFE",
    block_border_color="#F4DDE6",

    input_background_fill="#FFFDFE",
    input_border_color="#F2D7E2"
)


with gr.Blocks(
    theme=custom_theme,
    css=custom_css
) as demo:

    gr.Markdown(
        """
        # bookmarked
        hi there! i'm bookmarked, a chatbot for all things reading-related.
        """
    )

    with gr.Row():
        with gr.Column(scale=2):
            gr.ChatInterface(
                fn=respond
            )

        with gr.Column(
            scale=1,
            elem_classes="library-card"
        ):
            gr.Markdown(
                """
                ## find your nearest library
                enter your city or zip code to explore libraries near you.
                """
            )

            library_location = gr.Textbox(
                label="city or zip code",
                placeholder="example: 30040"
            )

            library_button = gr.Button(
                "find libraries",
                variant="primary"
            )

            library_map = gr.HTML(
                """
                <div class="map-placeholder">
                    enter a city or zip code to find nearby libraries
                </div>
                """
            )

            library_button.click(
                fn=find_library,
                inputs=library_location,
                outputs=library_map
            )

            library_location.submit(
                fn=find_library,
                inputs=library_location,
                outputs=library_map
            )


demo.launch(
    ssr_mode=False
)