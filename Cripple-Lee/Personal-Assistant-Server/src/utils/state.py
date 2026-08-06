from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    """Input state for the agent.

    Defines the initial structure of incoming data.
    See: https://langchain-ai.github.io/langgraph/concepts/low_level/#state
    """

    # add_messages appends new messages to the checkpointed history instead of
    # overwriting it, so each run only needs to send the new human message.
    messages: Annotated[list, add_messages]