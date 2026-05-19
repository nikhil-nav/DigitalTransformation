Add a new tool to the LLM agent tool set.

$ARGUMENTS describes the tool — e.g., "fetch_company_website tool that retrieves and summarizes a company's homepage".

Steps:
1. Read `backend/app/llm/tools.py` — tool definitions use Anthropic's canonical JSON schema format
2. Add the new tool definition to `tools.py`
3. Read `backend/app/llm/agent.py` — the agent loop dispatches tools by `tool_use.name`
4. Add a handler branch in `agent.py` (or in the calling domain module if domain-specific)
5. Read `backend/app/llm/openai_provider.py` — if the tool should work with OpenAI too, add the translation there
6. Add tests in `backend/tests/test_llm.py`

Key facts:
- Tool schema is **always** defined in Anthropic format in `tools.py`
- `openai_provider.py` translates on the fly — OpenAI uses a different schema
- Server-side tools (e.g., Anthropic `web_search`) are handled differently from client-dispatched tools — check `StreamEvent` kinds in `provider.py`
