"""
Anthropic Claude API integration for Opentrons protocol generation.
Based on opentrons-ai-server/api/domain/anthropic_predict.py
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from anthropic import Anthropic
from anthropic.types import Message, MessageParam, TextBlockParam

from api.settings import Settings
from api.domain.prompts import SYSTEM_PROMPT, PROMPT, DOCUMENTS, PROMPT_FIND_RELEVANT_DOCS
from api.services.simulator import ProtocolSimulator


class AnthropicPredict:
    """
    Anthropic Claude API integration for protocol generation.
    Provides tools for:
    - simulate_protocol: Validate protocols via HF Space simulator
    - get_relevant_api_docs: Retrieve relevant Opentrons API documentation
    - chat: General conversation with tool support
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
        self.model_name = settings.anthropic_model_name
        self.model_helper = settings.model_helper
        self.max_tokens = settings.max_tokens
        self.simulator = ProtocolSimulator(settings)

        # Paths for documentation
        self.storage_path = Path(__file__).parent.parent.parent / "storage"
        self.api_docs_path = self.storage_path / "api_docs"
        self.api_docs_struct = self.api_docs_path / "api_docs_struct_v2.25.md"
        self.docs_path = self.storage_path / "docs"

        # Load cached documentation for system context
        self.cached_docs = self._load_cached_docs()

        # Define tools for Claude
        self.tools = [
            {
                "name": "simulate_protocol",
                "description": "Simulates the python protocol on user input. Returned value is text indicating if protocol is successful.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "protocol": {
                            "type": "string",
                            "description": "Protocol in python for simulation"
                        },
                    },
                    "required": ["protocol"],
                },
            },
            {
                "name": "get_relevant_api_docs",
                "description": """Retrieves relevant API documentation based on the user's query.
                Use this tool when you need specific Opentrons API information to help generate
                protocols or answer technical questions about protocol implementation.""",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's query or context about what API documentation is needed"
                        },
                    },
                    "required": ["query"],
                },
                "cache_control": {"type": "ephemeral"},
            },
        ]

    def _load_cached_docs(self) -> List[MessageParam]:
        """Load and cache system documentation for context."""
        doc_content = self._get_docs()
        if doc_content:
            return [
                {
                    "role": "user",
                    "content": [
                        TextBlockParam(
                            type="text",
                            text=DOCUMENTS.format(doc_content=doc_content),
                            cache_control={"type": "ephemeral"}
                        )
                    ],
                }
            ]
        return []

    def _get_docs(self) -> str:
        """
        Load documents from the docs directory and return as XML-formatted string.
        """
        if not self.docs_path.exists():
            return ""

        xml_output = ["<system_documentation>"]

        for file_path in self.docs_path.iterdir():
            try:
                if file_path.is_dir():
                    continue

                content = file_path.read_text(encoding="utf-8")
                document_xml = [
                    "<system_doc>",
                    f"  <title>{file_path.name}</title>",
                    "  <type>reference</type>",
                    "   <content>",
                    f"    {content}",
                    "   </content>",
                    "</system_doc>",
                ]
                xml_output.extend(document_xml)

            except Exception:
                continue

        xml_output.append("</system_documentation>")
        return "\n".join(xml_output)

    def get_relevant_api_docs(self, query: str) -> str:
        """
        Retrieve relevant API documentation based on the user's query.
        Uses Claude to analyze the documentation structure and find relevant files.

        Args:
            query: The user's query about what API documentation is needed

        Returns:
            XML-formatted string containing relevant documentation content
        """
        # Check if API docs structure file exists
        if not self.api_docs_struct.exists():
            return "<relevant_file_content>API documentation structure not found.</relevant_file_content>"

        # Load API docs structure
        api_docs_structure = self.api_docs_struct.read_text(encoding="utf-8")

        # Use Claude to find relevant files
        msg: List[MessageParam] = [{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "text",
                        "media_type": "text/plain",
                        "data": api_docs_structure
                    },
                    "title": "Python API V2 Documentation Structure",
                    "context": "This is the structure of Opentrons Python API V2 Documentation with descriptions of each file.",
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": PROMPT_FIND_RELEVANT_DOCS.format(USER_QUERY=query)
                },
            ],
        }]

        response = self.client.messages.create(
            model=self.model_helper,
            messages=msg,
            max_tokens=1024,
            temperature=0.1,
            system="You are a helpful assistant that analyzes documentation structure to find relevant files.",
        )

        files_content = response.content[0].text.strip()
        return self._parse_and_load_docs(files_content)

    def _parse_and_load_docs(self, response: str) -> str:
        """
        Parse the file list from Claude's response and load the actual file contents.

        Args:
            response: Claude's response containing <relevant_files> tags

        Returns:
            XML-formatted string with file contents
        """
        match = re.search(r"<relevant_files>(.*?)</relevant_files>", response, re.DOTALL)
        if not match:
            return "<relevant_file_content>\n</relevant_file_content>"

        files_content = match.group(1).strip()
        filenames = [f.strip() for f in files_content.split(",") if f.strip()]
        xml_content = "<relevant_file_content>\n"

        for filename in filenames:
            filepath = self.api_docs_path / filename
            try:
                content = filepath.read_text(encoding="utf-8")
                xml_content += f"<file name='{filename}'>\n"
                xml_content += "<content>\n"
                xml_content += content
                xml_content += "\n</content>\n"
                xml_content += "</file>\n"
            except FileNotFoundError:
                continue
            except Exception:
                continue

        xml_content += "</relevant_file_content>"
        return xml_content

    def handle_tool_use(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """
        Handle tool calls from Claude.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Result of the tool execution
        """
        if tool_name == "simulate_protocol":
            return self.simulator.simulate(tool_input["protocol"])
        elif tool_name == "get_relevant_api_docs":
            query = tool_input.get("query", "")
            return self.get_relevant_api_docs(query)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _process_message(
        self,
        messages: List[MessageParam],
    ) -> Message:
        """
        Process a message through the Claude API.

        Args:
            messages: List of messages to send

        Returns:
            Claude's response message
        """
        response: Message = self.client.messages.create(
            max_tokens=self.max_tokens,
            messages=messages,
            model=self.model_name,
            system=SYSTEM_PROMPT,
            tools=self.tools,
            temperature=0.0,
        )
        return response

    def _handle_response(
        self,
        response: Message,
        messages: List[MessageParam],
    ) -> str:
        """
        Handle the response from Claude, including tool use.

        Args:
            response: Claude's response message
            messages: Current message history

        Returns:
            Final text response
        """
        # Handle tool use if present
        if response.content and response.content[-1].type == "tool_use":
            tool_use = response.content[-1]
            messages.append({"role": "assistant", "content": response.content})

            # Execute the tool
            result = self.handle_tool_use(tool_use.name, tool_use.input)

            # Add tool result to messages
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    }
                ],
            })

            # Get follow-up response
            follow_up = self._process_message(messages)

            if follow_up.content and follow_up.content[0].type == "text":
                return follow_up.content[0].text

            return "Error: Unexpected follow-up response type"

        elif response.content and response.content[0].type == "text":
            return response.content[0].text

        return "Error: Unexpected response type"

    def chat(
        self,
        message: str,
        history: Optional[List[MessageParam]] = None,
    ) -> str:
        """
        Process a chat message with tool support.
        This is the main entry point for the chat tool.

        Args:
            message: User's message
            history: Optional conversation history

        Returns:
            AI assistant's response
        """
        try:
            # Start with cached docs
            messages: List[MessageParam] = self.cached_docs.copy()

            # Add conversation history
            if history:
                messages.extend(history)

            # Add current user message with prompt template
            user_message: MessageParam = {
                "role": "user",
                "content": PROMPT.format(USER_PROMPT=message)
            }
            messages.append(user_message)

            # Process the message
            response = self._process_message(messages)

            # Handle the response (including potential tool use)
            return self._handle_response(response, messages)

        except Exception as e:
            return f"Error processing message: {str(e)}"

    def simulate_protocol(self, protocol: str) -> str:
        """
        Simulate a protocol directly (for MCP tool exposure).

        Args:
            protocol: Python protocol code to simulate

        Returns:
            Simulation result
        """
        return self.simulator.simulate(protocol)
