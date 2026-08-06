from typing_extensions import TypedDict


class Context(TypedDict):
    """Context parameters for the agent.

    This is a TypedDict, so instances are plain dicts accessed via keys
    (e.g. ``runtime.context["hf_token"]``), not attributes.

    Set these when creating assistants OR when invoking the graph.
    See: https://langchain-ai.github.io/langgraph/cloud/how-tos/configuration_cloud/
    """

    my_configurable_param: str