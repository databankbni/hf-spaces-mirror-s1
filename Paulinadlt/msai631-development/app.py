import os

import gradio as gr
from huggingface_hub import InferenceClient


# Hugging Face hosted sentiment-analysis model
SENTIMENT_MODEL = (
    "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
)

# Read the Hugging Face token securely from the Space secret
HF_TOKEN = os.getenv("HF_TOKEN")

# Create the client that connects to the hosted Hugging Face service
sentiment_client = InferenceClient(
    provider="hf-inference",
    api_key=HF_TOKEN
)


def get_initial_state():
    """
    Creates a new conversation state for each user session.
    """
    return {
        "flow": None,
        "stage": None,
        "data": {}
    }


def get_sentiment_message(message):
    """
    Sends the user's message to the hosted Hugging Face sentiment model.

    The sentiment result is used internally to make Classie's response
    sound more supportive and natural.
    """
    if not HF_TOKEN:
        return (
            "\n\n"
            "I hope this information helps. Feel free to ask another "
            "engine-related question."
        )

    try:
        results = sentiment_client.text_classification(
            message,
            model=SENTIMENT_MODEL
        )

        if not results:
            return (
                "\n\n"
                "I hope this information helps. Feel free to ask another "
                "engine-related question."
            )

        best_result = max(results, key=lambda result: result.score)
        sentiment_label = best_result.label.upper()
        confidence_score = best_result.score

        if sentiment_label == "NEGATIVE" and confidence_score >= 0.90:
            return (
                "\n\n"
                "I understand how frustrating engine problems can be. "
                "I hope these troubleshooting steps help you determine "
                "what to check next."
            )

        if sentiment_label == "POSITIVE" and confidence_score >= 0.90:
            return (
                "\n\n"
                "I'm glad I could help. Feel free to ask another "
                "engine-related question."
            )

        return (
            "\n\n"
            "I hope this information helps. Let me know if you have another "
            "engine-related question."
        )

    except Exception as error:
        print(f"Sentiment analysis error: {error}")

        return (
            "\n\n"
            "I hope this information helps. Feel free to ask another "
            "engine-related question."
        )


def contains_yes(message):
    """
    Identifies common affirmative responses.
    """
    yes_phrases = [
        "yes",
        "yeah",
        "yep",
        "i do",
        "there is",
        "there are",
        "noticed one",
        "noticed some"
    ]

    return any(phrase in message for phrase in yes_phrases)


def contains_no(message):
    """
    Identifies common negative responses.
    """
    no_phrases = [
        "no",
        "nope",
        "not that i know",
        "none",
        "i don't",
        "i do not",
        "haven't noticed",
        "have not noticed"
    ]

    return any(phrase in message for phrase in no_phrases)


def handle_overheating_flow(original_message, message, state):
    """
    Handles the multi-turn overheating conversation.

    Classie remembers the user's previous answers and asks one
    diagnostic question at a time.
    """
    stage = state.get("stage")
    data = state.setdefault("data", {})

    if stage == "operating_condition":
        if "driv" in message or "road" in message or "moving" in message:
            data["operating_condition"] = "while driving"

        elif "idl" in message or "stopped" in message or "stationary" in message:
            data["operating_condition"] = "while idling"

        elif "both" in message or "all the time" in message:
            data["operating_condition"] = "while driving and idling"

        else:
            return (
                "I want to make sure I understand.\n\n"
                "Does the overheating happen **while driving**, "
                "**while idling**, or **both**?"
            ), state

        state["stage"] = "coolant_leak"

        return (
            f"Thanks. You said the overheating happens "
            f"**{data['operating_condition']}**.\n\n"
            "Have you noticed any coolant leaking underneath the vehicle "
            "or around the engine?"
        ), state

    if stage == "coolant_leak":
        if contains_yes(message):
            data["coolant_leak"] = True

        elif contains_no(message):
            data["coolant_leak"] = False

        else:
            return (
                "Have you noticed a coolant leak?\n\n"
                "Please answer **yes**, **no**, or describe what you see."
            ), state

        state["stage"] = "warning_lights"

        return (
            "Thank you. Are any temperature, coolant, check-engine, "
            "or other warning lights currently illuminated?"
        ), state

    if stage == "warning_lights":
        if contains_yes(message):
            data["warning_lights"] = True

        elif contains_no(message):
            data["warning_lights"] = False

        else:
            return (
                "Are any warning lights illuminated?\n\n"
                "Please answer **yes**, **no**, or describe the warning."
            ), state

        operating_condition = data.get(
            "operating_condition",
            "during operation"
        )
        coolant_leak = data.get("coolant_leak", False)
        warning_lights = data.get("warning_lights", False)

        observations = [
            f"The overheating occurs {operating_condition}."
        ]

        if coolant_leak:
            observations.append("You reported signs of a coolant leak.")
        else:
            observations.append("You did not notice a coolant leak.")

        if warning_lights:
            observations.append("You reported an illuminated warning light.")
        else:
            observations.append("You did not report an illuminated warning light.")

        observation_text = "\n".join(
            f"• {observation}" for observation in observations
        )

        if coolant_leak:
            recommendation = (
                "Because you noticed a possible coolant leak, stop operating "
                "the engine and allow it to cool completely. Do not open a hot "
                "cooling system. The leak and coolant level should be inspected "
                "before the vehicle is operated again."
            )
        elif warning_lights:
            recommendation = (
                "Because a warning light is active, retrieve the diagnostic "
                "fault code and review the manufacturer's service information. "
                "If the temperature continues to rise, stop the engine and "
                "have it inspected by a qualified technician."
            )
        else:
            recommendation = (
                "Start by checking the coolant level only after the engine has "
                "cooled completely. The radiator, cooling fan, airflow path, "
                "thermostat, and other cooling-system components may also need "
                "inspection."
            )

        response = (
            "Here is a summary of what you shared:\n\n"
            f"{observation_text}\n\n"
            f"{recommendation}\n\n"
            "**Safety reminder:** If the engine temperature continues to rise, "
            "stop operating the vehicle to reduce the risk of engine damage.\n\n"
            "Would you like help with another engine-related topic?"
        )

        # End the overheating flow after providing the recommendation.
        state = get_initial_state()

        return response, state

    # Reset the flow if an unexpected stage is encountered.
    return (
        "I lost track of that troubleshooting step. Please tell me again "
        "what issue the engine is experiencing."
    ), get_initial_state()


def generate_rule_based_response(original_message, state):
    """
    Generates Classie's response and updates conversation state.
    """
    message = original_message.lower().strip()

    # Allow the user to leave an active troubleshooting flow.
    if message in ["cancel", "restart", "start over", "reset"]:
        return (
            "No problem. I cleared the current troubleshooting conversation.\n\n"
            "What engine-related issue would you like help with?"
        ), get_initial_state()

    # Continue an active multi-turn flow before checking general keywords.
    if state.get("flow") == "overheating":
        return handle_overheating_flow(
            original_message,
            message,
            state
        )

    use_sentiment = True

    if any(word in message for word in ["hello", "hi", "hey"]):
        use_sentiment = False

        rule_based_response = (
            "Hello! 👋 I'm Classie, your Engine Support Assistant.\n\n"
            "I can guide you through basic engine-support questions and ask "
            "follow-up questions when additional information is needed.\n\n"
            "Type **help** to see what I can do."
        )

    elif any(
        phrase in message
        for phrase in [
            "thank you",
            "thanks",
            "thank you so much",
            "thanks a lot",
            "that helped",
            "very helpful",
            "appreciate it",
            "i appreciate it"
        ]
    ):
        use_sentiment = False
        rule_based_response = (
            "You're welcome! 😊 Is there another engine-related issue "
            "I can help you with?"
        )

    elif any(
        phrase in message
        for phrase in [
            "help",
            "what can you do",
            "capabilities",
            "options"
        ]
    ):
        use_sentiment = False

        rule_based_response = (
            "I can provide basic information about:\n\n"
            "• Check engine lights\n"
            "• Engine overheating\n"
            "• Low oil pressure\n"
            "• Engine fault codes\n"
            "• Basic engine troubleshooting\n\n"
            "For overheating concerns, I can also ask follow-up questions "
            "to better understand the situation.\n\n"
            "Try asking: **My engine is overheating.**"
        )

    elif any(
        phrase in message
        for phrase in [
            "check engine",
            "engine light",
            "warning light",
            "malfunction indicator"
        ]
    ):
        rule_based_response = (
            "A check engine light can indicate different engine or "
            "emissions-related issues.\n\n"
            "A good first step is to retrieve the diagnostic fault code and "
            "review the manufacturer's service information.\n\n"
            "If the light is flashing or the engine is not operating normally, "
            "the equipment should be inspected by a qualified technician."
        )

    elif any(
        phrase in message
        for phrase in [
            "overheating",
            "overheat",
            "hot engine",
            "engine is hot",
            "engine hot",
            "high temperature",
            "temperature warning"
        ]
    ):
        # Begin the new multi-turn overheating flow.
        use_sentiment = False

        state = {
            "flow": "overheating",
            "stage": "operating_condition",
            "data": {}
        }

        rule_based_response = (
            "I'm sorry you're experiencing engine overheating. Let's narrow "
            "down what is happening.\n\n"
            "**Does the overheating occur while driving, while idling, "
            "or both?**\n\n"
            "You can type **cancel** at any time to stop this troubleshooting "
            "conversation."
        )

    elif any(
        phrase in message
        for phrase in [
            "oil pressure",
            "low oil",
            "oil warning",
            "oil light"
        ]
    ):
        rule_based_response = (
            "Low oil pressure can indicate a low oil level, an oil leak, "
            "a sensor issue, or a lubrication-system problem.\n\n"
            "Stop the engine, allow it to cool, and check the oil level "
            "according to the manufacturer's instructions.\n\n"
            "**Warning:** Continued operation with low oil pressure may "
            "damage the engine."
        )

    elif any(
        phrase in message
        for phrase in [
            "fault code",
            "fault codes",
            "diagnostic code"
        ]
    ):
        use_sentiment = False

        rule_based_response = (
            "A fault code is generated when an engine control system detects "
            "a condition outside its expected operating parameters.\n\n"
            "The code can help identify the system that requires further "
            "troubleshooting, but it does not always identify the exact root "
            "cause of the problem."
        )

    elif any(
        phrase in message
        for phrase in [
            "troubleshoot",
            "troubleshooting",
            "diagnose",
            "diagnosis"
        ]
    ):
        rule_based_response = (
            "Basic troubleshooting begins by gathering information about the "
            "problem, checking active fault codes, reviewing recent changes or "
            "repairs, and performing visual inspections.\n\n"
            "Diagnostic procedures should follow the manufacturer's service "
            "information."
        )

    else:
        use_sentiment = False

        rule_based_response = (
            "I'm not sure I understood that request.\n\n"
            "I can help with:\n\n"
            "• Check engine lights\n"
            "• Engine overheating\n"
            "• Oil pressure\n"
            "• Engine fault codes\n"
            "• Basic troubleshooting\n\n"
            "Could you rephrase the issue or type **help** to see the "
            "supported topics?"
        )

    if use_sentiment:
        rule_based_response += get_sentiment_message(original_message)

    return rule_based_response, state


def respond(message, history, state):
    """
    Adds the user's message and Classie's response to the chat history.
    """
    original_message = message.strip()

    if not original_message:
        response = (
            "Sorry, I did not receive a message. Please enter a question "
            "or type **help** to see what I can do."
        )

        history = history + [
            {
                "role": "assistant",
                "content": response
            }
        ]

        return "", history, state

    response, state = generate_rule_based_response(
        original_message,
        state
    )

    history = history + [
        {
            "role": "user",
            "content": original_message
        },
        {
            "role": "assistant",
            "content": response
        }
    ]

    return "", history, state


def clear_conversation():
    """
    Clears both the visible conversation and internal state.
    """
    return "", [], get_initial_state()


with gr.Blocks(title="Classie – Engine Support Assistant") as demo:
    gr.Markdown(
        """
        # 🤖 Classie – Engine Support Assistant

        Classie is a traditional rule-based chatbot enhanced with an
        AI-powered sentiment analysis service.

        Classie can answer questions about check engine lights, engine
        overheating, oil pressure, fault codes, and basic troubleshooting.

        The updated overheating feature uses follow-up questions to create
        a more natural and context-aware conversation.

        Type **help** to see Classie's capabilities.
        """
    )

    chatbot = gr.Chatbot(
        label="Conversation with Classie",
        type="messages",
        height=500
    )

    conversation_state = gr.State(get_initial_state())

    message_box = gr.Textbox(
        label="Your Message",
        placeholder="Ask Classie an engine-related question...",
        lines=2
    )

    with gr.Row():
        send_button = gr.Button("Send", variant="primary")
        clear_button = gr.Button("Clear Conversation")

    gr.Examples(
        examples=[
            ["Hello"],
            ["What can you do?"],
            ["My engine is overheating and I am very frustrated"],
            ["What is a fault code?"],
            ["My oil pressure is low"]
        ],
        inputs=message_box
    )

    send_button.click(
        fn=respond,
        inputs=[
            message_box,
            chatbot,
            conversation_state
        ],
        outputs=[
            message_box,
            chatbot,
            conversation_state
        ]
    )

    message_box.submit(
        fn=respond,
        inputs=[
            message_box,
            chatbot,
            conversation_state
        ],
        outputs=[
            message_box,
            chatbot,
            conversation_state
        ]
    )

    clear_button.click(
        fn=clear_conversation,
        inputs=[],
        outputs=[
            message_box,
            chatbot,
            conversation_state
        ]
    )


demo.launch()
