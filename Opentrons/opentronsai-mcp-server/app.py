"""
Opentrons AI MCP Server

A Gradio-based MCP server that provides tools for generating, simulating,
and managing Opentrons laboratory protocols using AI.

Priority Tools:
1. simulate_protocol - Validate protocols via HF Space simulator
2. get_relevant_api_docs - Retrieve relevant Opentrons API documentation
3. chat - General AI assistant conversation with tool support

Workflow:
1. User asks to write a protocol (e.g., "write a serial dilution protocol")
2. System uses get_relevant_api_docs to get relevant documentation
3. Based on relevant context + user request, chat tool generates a protocol
4. User can simulate the protocol to validate it
"""

import gradio as gr

from api.settings import Settings
from api.domain.anthropic_predict import AnthropicPredict
from api.services.simulator import ProtocolSimulator

# Initialize settings and services
settings = Settings()
predictor = AnthropicPredict(settings)
simulator = ProtocolSimulator(settings)


# =============================================================================
# PRIORITY TOOL 1: Simulate Protocol
# =============================================================================

def simulate_protocol(protocol: str) -> str:
    """
    Simulates the python protocol on user input.
    Returned value is text indicating if protocol is successful.

    Args:
        protocol: Protocol code in Python for simulation

    Returns:
        Text indicating if protocol is successful or error details
    """
    if not protocol or not protocol.strip():
        return "Error: No protocol code provided"

    return simulator.simulate(protocol)


# =============================================================================
# PRIORITY TOOL 2: Get Relevant API Docs
# =============================================================================

def get_relevant_api_docs(query: str) -> str:
    """
    Retrieves relevant API documentation based on the user's query.
    Use this tool when you need specific Opentrons API information to help
    generate protocols or answer technical questions about protocol implementation.

    Args:
        query: The user's query or context about what API documentation is needed

    Returns:
        XML-formatted relevant documentation content
    """
    if not query or not query.strip():
        return "<relevant_file_content>Error: No query provided</relevant_file_content>"

    return predictor.get_relevant_api_docs(query)


# =============================================================================
# PRIORITY TOOL 3: Chat
# =============================================================================

def generate_protocol(message: str) -> str:
    """
    Generate Opentrons protocols using AI.
    This tool automatically retrieves relevant API documentation and
    generates validated protocols based on your requirements.

    Args:
        message: Your protocol request (e.g., "Write a serial dilution protocol for Flex")

    Returns:
        Generated protocol code with explanation
    """
    if not message or not message.strip():
        return "Error: No message provided"

    return predictor.chat(message)


# =============================================================================
# Gradio Interface
# =============================================================================

# Simulate Protocol Interface
simulate_interface = gr.Interface(
    fn=simulate_protocol,
    inputs=gr.Code(
        language="python",
        label="Protocol Code",
        lines=25,
        value='''from opentrons import protocol_api

metadata = {
    'protocolName': 'Test Protocol',
    'author': 'OpentronsAI',
    'description': 'A simple test protocol',
    'source': 'OpentronsAI'
}

requirements = {
    'robotType': 'Flex',
    'apiLevel': '2.28'
}

def run(protocol: protocol_api.ProtocolContext):
    # Load trash bin (required for Flex)
    trash = protocol.load_trash_bin('A3')

    # Load tip rack
    tiprack = protocol.load_labware('opentrons_flex_96_tiprack_200ul', 'D1')

    # Load pipette
    pipette = protocol.load_instrument('flex_1channel_1000', 'left', tip_racks=[tiprack])

    # Load labware
    plate = protocol.load_labware('nest_96_wellplate_200ul_flat', 'D2')

    # Simple protocol step
    pipette.pick_up_tip()
    pipette.aspirate(100, plate['A1'])
    pipette.dispense(100, plate['A2'])
    pipette.drop_tip()
'''
    ),
    outputs=gr.Textbox(label="Simulation Result", lines=10),
    api_name="simulate_protocol",
    title="Simulate Protocol",
    description="Validate your Opentrons protocol using the simulator. Paste your Python protocol code and click Submit to check for errors."
)

# Get API Docs Interface
api_docs_interface = gr.Interface(
    fn=get_relevant_api_docs,
    inputs=gr.Textbox(
        label="Query",
        placeholder="e.g., How to use thermocycler module? or Serial dilution protocol examples",
        lines=3,
    ),
    outputs=gr.Textbox(label="Relevant Documentation", lines=30),
    api_name="get_relevant_api_docs",
    title="API Documentation",
    description="Search Opentrons API documentation to find relevant information for your protocol development."
)

# Protocol Generation Interface
chat_interface = gr.Interface(
    fn=generate_protocol,
    inputs=gr.Textbox(
        label="Message",
        placeholder="e.g., Write a serial dilution protocol for Flex with 8 dilution steps",
        lines=5,
    ),
    outputs=gr.Markdown(label="Response"),
    api_name="generate_protocol",
    title="Chat with Opentrons AI",
    description="""Chat with the Opentrons AI assistant to generate protocols, ask questions, or get help.

**Example prompts:**
- "Write a serial dilution protocol for Flex"
- "Create a PCR setup protocol with thermocycler"
- "How do I use the 96-channel pipette?"
- "Generate a sample transfer protocol for OT-2"
"""
)

# Build tabbed interface
# demo = gr.TabbedInterface(
#     [chat_interface, simulate_interface, api_docs_interface],
#     ["Chat", "Simulate", "API Docs"],
#     title="Opentrons AI Protocol Generator (MCP Server)",
# )

# hide tabs
with gr.Blocks(title="Opentrons AI Protocol Generator (MCP Server)") as demo:
    gr.Markdown("<h1 style='text-align: center; margin-bottom: 1rem'>Opentrons AI Protocol Generator (MCP Server)</h1>")
    with gr.Tabs():
        with gr.Tab("Chat", visible=False):
            chat_interface.render()
        with gr.Tab("Simulate", visible=False):
            simulate_interface.render()
        with gr.Tab("API Docs", visible=False):
            api_docs_interface.render()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Opentrons AI MCP Server")
    print("=" * 60)
    print("\nStarting server with MCP support...")
    print("\nMCP endpoint will be available at:")
    print("  http://localhost:7860/gradio_api/mcp/")
    print("\nMCP Client Configuration:")
    print('''
{
  "mcpServers": {
    "opentrons-ai": {
      "url": "http://localhost:7860/gradio_api/mcp/"
    }
  }
}
''')
    print("=" * 60 + "\n")

    demo.launch(mcp_server=True)
