"""Ready-to-use system prompt templates for AI agents using OpenTime.

Usage::

    from opentime.prompts import get_system_prompt

    # For MCP-connected agents (Claude Code, Cursor, etc.)
    prompt = get_system_prompt("mcp")

    # For agents using OpenAI function calling or Gemini
    prompt = get_system_prompt("function_calling")

    # For agents calling the REST API directly
    prompt = get_system_prompt("rest_api")

    # Append to your agent's system prompt
    full_prompt = f"You are a helpful assistant.\\n\\n{prompt}"
"""

from opentime.prompts.templates import get_system_prompt

__all__ = ["get_system_prompt"]
