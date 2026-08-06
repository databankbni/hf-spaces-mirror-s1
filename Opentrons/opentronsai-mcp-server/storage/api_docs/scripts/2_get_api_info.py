import re
from typing import List
from pathlib import Path
from anthropic import Anthropic
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Path to the .env file in opentrons-ai-server root
ENV_PATH = Path(__file__).parent.parent.parent.parent.parent / ".env"

class Settings(BaseSettings):
    """Settings for the script using the same .env as the main application."""
    anthropic_api_key: SecretStr = SecretStr("default_anthropic_api_key")
    
    model_config = SettingsConfigDict(env_file=ENV_PATH, env_file_encoding="utf-8", extra="ignore")



PROMPT_FIND_RELEVANT_DOCS = """Your task is to analyze the API documentation structure and determine which documentation files are most relevant to the user's query.

Here is the user's query:
<user_query>
{USER_QUERY}
</user_query>

Based on the documentation structure provided, identify which files would be most relevant for answering this query.
Consider the <about> sections for each file to understand their content.

Instructions:
- Analyze the query to identify key concepts (e.g., modules, pipettes, labware, specific robot types)
- Match these concepts with the appropriate documentation files based on their <about> descriptions
- List the complete file paths as they appear in the documentation structure (e.g., docs/v2/new_modules.rst)
- If a query involves multiple concepts, include all relevant files
- Be selective - only include files that directly relate to the query
- Format your response with <relevant_files> tags
- Make sure you get relevant doc only from docs

Format your response exactly like this:
<relevant_files>
docs/v2/new_modules.rst,
docs/v2/new_pipette.rst,
docs/v2/index.rst
src/opentrons/protocol_api/_parameter_context.py


</relevant_files>

Important: Use the exact file paths as shown in the documentation structure, separated by commas.
"""


def get_api_info(prompt: str, api_docs_struct_path: str = "/Users/elyorkodirov/work/git/opentrons/opentrons-ai-server/api/storage/api_docs/api_docs_struct.md") -> str:
    """
    Get relevant API documentation file paths based on a user prompt.
    
    Args:
        prompt: The user's query/prompt
        api_docs_struct_path: Path to the api_docs_struct.md file
        
    Returns:
        String containing file paths wrapped in <relevant_files> tags
    """
    # Read the API docs structure
    with open(api_docs_struct_path, 'r') as f:
        api_docs_structure = f.read()
    
    # Initialize Anthropic client
    settings = Settings()
    client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    
    # Create message for Anthropic
    msg = [
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "text", "media_type": "text/plain", "data": api_docs_structure},
                    "title": "API Documentation Structure",
                    "context": "This is the structure of Opentrons Python API V2 Documentation with descriptions of each file.",
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": PROMPT_FIND_RELEVANT_DOCS.format(USER_QUERY=prompt)},
            ],
        }
    ]
    
    # Get response from Anthropic
    response = client.messages.create(
        max_tokens=1024,
        temperature=0.0,
        messages=msg,
        model="claude-3-5-sonnet-20241022",
        system="You are a helpful assistant that analyzes documentation structure to find relevant files."
    )
    
    # Return the response text which should already be formatted with <relevant_files> tags
    return response.content[0].text.strip()



def parse_relevant_files_and_get_content(api_info_output: str, base_path: str = "/Users/elyorkodirov/work/git/opentrons/opentrons-ai-server/api/storage/api_docs") -> str:
    """
    Parse the output of get_api_info and construct XML content with file contents.
    
    Args:
        api_info_output: The output from get_api_info containing <relevant_files> tags
        base_path: Base path where the documentation files are located
        
    Returns:
        String containing XML formatted file contents
    """
    # Extract content between <relevant_files> tags
    match = re.search(r'<relevant_files>(.*?)</relevant_files>', api_info_output, re.DOTALL)
    if not match:
        return "<relevant_file_content>\n</relevant_file_content>"
    
    # Get the filenames and clean them
    files_content = match.group(1).strip()
    filenames = [f.strip() for f in files_content.split(',') if f.strip()]
    
    # Build XML content
    xml_content = "<relevant_file_content>\n"
    
    for filename in filenames:
        filepath = f"{base_path}/{filename}"
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            
            xml_content += f"<file name='{filename}'>\n"
            xml_content += "<content>\n"
            xml_content += content
            xml_content += "\n</content>\n"
            xml_content += "</file>\n"
        except FileNotFoundError:
            # Skip files that don't exist
            continue
        except Exception:
            # Skip files that can't be read
            continue
    
    xml_content += "</relevant_file_content>"
    
    return xml_content


def count_xml_content_tokens(xml_content: str, model: str = "claude-3-5-sonnet-20241022") -> int:
    """
    Count the number of tokens in the XML content using Anthropic's token counting endpoint.
    
    Args:
        xml_content: The XML formatted content to count tokens for
        model: The model to use for token counting (default: claude-3-5-sonnet-20241022)
        
    Returns:
        The number of input tokens
    """
    # Initialize Anthropic client
    settings = Settings()
    client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    
    # Count tokens using the messages.count_tokens endpoint
    response = client.messages.count_tokens(
        model=model,
        messages=[
            {
                "role": "user",
                "content": xml_content
            }
        ]
    )
    
    return response.input_tokens


# Example usage:
if __name__ == "__main__":
    prompt = """
    add thermocycler to the protocol
    """

    prompt = """
    Write a protocol using the Opentrons Python Protocol API v2 for Opentrons Flex robot according to the following description:

    Application:
    - Basic aliquoting

    Description:
    - simple

    Pipette mount(s):

    - 96-Channel 1000uL pipette

    Fixtures:
    - Trash bin

    Labware:
    - opentrons_flex_96_filtertiprack_1000ul x 1
    - nest_96_wellplate_2ml_deep x 1
    - nest_1_reservoir_290ml x 1

    Liquids:
    - Liquid 1: no need

    Steps:
    1. transfer 10ul from reservoir to the well plate
    """

    prompt = """
    Give me serial dilution example for OT-2.
    """
    
    # Get relevant files
    api_info_result = get_api_info(prompt=prompt)
    print("API Info Result:")
    print(api_info_result)
    print("\n" + "="*50 + "\n")
    
    # Parse and get content
    xml_content = parse_relevant_files_and_get_content(api_info_result)
    print("XML Content:")
    print(xml_content[:1000] + "..." if len(xml_content) > 1000 else xml_content)
    
    # Count tokens
    token_count = count_xml_content_tokens(xml_content)
    print(f"\nToken count: {token_count}")