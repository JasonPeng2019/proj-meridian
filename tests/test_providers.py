"""Provider routing and native Messages tool exchange, without real credentials."""
import asyncio
import json

import httpx
import pytest

from backend.app import providers


@pytest.fixture
def clean_keys(monkeypatch, tmp_path):
    for name in ["CHAT_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "MERIDIAN_NO_KEY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(providers, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(providers, "inside", lambda path: tmp_path / path)
    return monkeypatch


def test_each_named_key_selects_its_provider_and_default_model(clean_keys):
    clean_keys.setenv("OPENAI_API_KEY", "fixture-openai")
    assert providers.provider_name() == "openai"
    assert providers.model_name() == "gpt-6-luna"
    assert providers.api_key() == "fixture-openai"
    clean_keys.delenv("OPENAI_API_KEY")
    clean_keys.setenv("ANTHROPIC_API_KEY", "fixture-anthropic")
    assert providers.provider_name() == "anthropic"
    assert providers.model_name() == "claude-sonnet-5-5"
    assert providers.api_key() == "fixture-anthropic"


def test_both_keys_and_explicit_selection_never_cross_provider_credentials(clean_keys):
    clean_keys.setenv("OPENAI_API_KEY", "fixture-openai")
    clean_keys.setenv("ANTHROPIC_API_KEY", "fixture-anthropic")
    assert providers.api_key() == "fixture-openai"
    clean_keys.setenv("CHAT_PROVIDER", "anthropic")
    clean_keys.setenv("ANTHROPIC_MODEL", "explicit-anthropic-model")
    assert providers.api_key() == "fixture-anthropic"
    assert providers.model_name() == "explicit-anthropic-model"
    clean_keys.delenv("ANTHROPIC_API_KEY")
    assert providers.api_key() is None  # OpenAI's available key must not be substituted.
    clean_keys.setenv("CHAT_PROVIDER", "openai")
    assert providers.model_name() == "gpt-6-luna"


def test_no_key_mode_disables_both_providers(clean_keys):
    clean_keys.setenv("ANTHROPIC_API_KEY", "fixture-anthropic")
    clean_keys.setenv("MERIDIAN_NO_KEY", "1")
    assert providers.api_key() is None


def test_unsupported_provider_fails_without_network_or_key_disclosure(clean_keys):
    clean_keys.setenv("CHAT_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="CHAT_PROVIDER"):
        providers.api_key()


def test_native_anthropic_exchange_batches_tool_results_and_preserves_text():
    requests = []
    blocks = [{"type": "thinking", "thinking": "not saved to conversation", "signature": "fixture-signature"},
              {"type": "tool_use", "id": "tool-a", "name": "find_part", "input": {"query": "Plate"}},
              {"type": "tool_use", "id": "tool-b", "name": "get_facts", "input": {"key": "D-001"}}]
    answer = "Two possible readings: 3 mm and 6 mm. [cite: D-001/part]"

    def respond(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["authorization"] == "Bearer fixture-anthropic"
        assert request.headers["anthropic-version"] == "2026-10-21"
        body = json.loads(request.content)
        assert "reasoning" not in body and "store" not in body and "service_tier" not in body
        assert body["tools"][0]["input_schema"]["type"] == "object"
        requests.append(body)
        return httpx.Response(200, json={"id": "fixture-message", "stop_reason": "tool_use" if len(requests)==1 else "end_turn",
            "content": blocks if len(requests)==1 else [{"type": "text", "text": answer}],
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 3, "output_tokens": 2}}, headers={"request-id":"fixture-request"})

    async def run():
        items = [{"role": "user", "content": "Previous question"}, {"role":"assistant", "content":"Previous answer"},
                 {"role":"user", "content":"Show the plate"}]
        tools = [{"name":"find_part", "description":"Find a part", "parameters":{"type":"object"}}]
        async with providers.AnthropicClient(api_key="fixture-anthropic", transport=httpx.MockTransport(respond)) as client:
            first = await client.responses.create(model=providers.ANTHROPIC_MODEL, instructions="Use evidence", input=items, tools=tools, max_output_tokens=6000)
            assert [item.call_id for item in first.output if item.type=="function_call"] == ["tool-a","tool-b"]
            items.extend(first.output)
            items.extend([{"type":"function_call_output", "call_id":"tool-a", "output":'{"parts":["D-001"]}'},
                          {"type":"function_call_output", "call_id":"tool-b", "output":'{"thickness":[3,6]}'}])
            last = await client.responses.create(model=providers.ANTHROPIC_MODEL, instructions="Use evidence", input=items, tools=tools, max_output_tokens=6000)
            assert last.output_text == answer and last.status == "completed"
            assert last.usage.total_tokens == 15
    asyncio.run(run())
    assert len(requests) == 2
    assert requests[1]["messages"][-2] == {"role":"assistant", "content":blocks}
    results = requests[1]["messages"][-1]
    assert results["role"] == "user"
    assert [item["tool_use_id"] for item in results["content"]] == ["tool-a","tool-b"]


def test_anthropic_format_parser_uses_native_schema_without_answer_retries():
    schema = {"type":"object", "properties":{"value":{"type":"number"}}, "required":["value"], "additionalProperties":False}
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["output_config"]["format"] == {"type":"json_schema", "schema":schema}
        return httpx.Response(200, json={"content":[{"type":"text", "text":'{"value":4.5}'}], "stop_reason":"end_turn"})
    async def run():
        async with providers.AnthropicClient(api_key="fixture", transport=httpx.MockTransport(respond)) as client:
            result = await client.responses.create(model=providers.ANTHROPIC_MODEL, instructions="Format input", input=[{"role":"user","content":"four point five"}],
                max_output_tokens=2400, text={"format":{"type":"json_schema","name":"review_input","strict":True,"schema":schema}})
            assert json.loads(result.output_text) == {"value":4.5}
    asyncio.run(run())
    assert len(calls) == 1


def test_anthropic_authentication_failure_is_not_retried_or_sent_elsewhere():
    requests = []
    def reject(request):
        requests.append(str(request.url))
        return httpx.Response(401, json={"error":{"type":"authentication_error"}})
    async def run():
        async with providers.AnthropicClient(api_key="fixture", transport=httpx.MockTransport(reject)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.responses.create(model=providers.ANTHROPIC_MODEL, instructions="Answer", input=[{"role":"user","content":"Hello"}], max_output_tokens=50)
    asyncio.run(run())
    assert requests == ["https://api.anthropic.com/v1/messages"]
