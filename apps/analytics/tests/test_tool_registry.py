import pytest

from app.services.agents.tool_registry import ToolRegistry, ToolSpec


async def dummy_tool(query: str, **_kwargs) -> dict:
    return {"result": f"searched for {query}"}


async def failing_tool(query: str, **_kwargs) -> dict:
    raise RuntimeError("Tool failed")


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    spec = ToolSpec(
        name="test_search",
        description="A test search tool",
        category="data",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    reg.register(spec, dummy_tool)
    return reg


@pytest.mark.asyncio
async def test_register_and_get(registry: ToolRegistry):
    spec = registry.get("test_search")
    assert spec is not None
    assert spec.name == "test_search"
    assert spec.category == "data"


@pytest.mark.asyncio
async def test_get_unknown_returns_none(registry: ToolRegistry):
    assert registry.get("nonexistent") is None


@pytest.mark.asyncio
async def test_list_tools(registry: ToolRegistry):
    all_tools = registry.list_tools()
    assert len(all_tools) == 1
    data_tools = registry.list_tools(category="data")
    assert len(data_tools) == 1
    action_tools = registry.list_tools(category="action")
    assert len(action_tools) == 0


@pytest.mark.asyncio
async def test_search_tools(registry: ToolRegistry):
    results = registry.search("search")
    assert len(results) == 1
    results = registry.search("nonexistent")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_execute_success(registry: ToolRegistry):
    result = await registry.execute("test_search", {"query": "marketing trends"})
    assert result.success is True
    assert result.output == {"result": "searched for marketing trends"}
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_execute_not_found(registry: ToolRegistry):
    result = await registry.execute("nonexistent", {})
    assert result.success is False
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_execute_error():
    reg = ToolRegistry()
    spec = ToolSpec(
        name="fail",
        description="always fails",
        category="data",
        parameters_schema={"type": "object"},
    )
    reg.register(spec, failing_tool)
    result = await reg.execute("fail", {"query": "test"})
    assert result.success is False
    assert "Tool failed" in result.error


@pytest.mark.asyncio
async def test_get_anthropic_schemas(registry: ToolRegistry):
    schemas = registry.get_tool_schemas_for_anthropic()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "test_search"
    assert "input_schema" in schemas[0]
    assert "description" in schemas[0]


@pytest.mark.asyncio
async def test_get_anthropic_schemas_filtered(registry: ToolRegistry):
    schemas = registry.get_tool_schemas_for_anthropic(tool_names=["test_search"])
    assert len(schemas) == 1
    schemas = registry.get_tool_schemas_for_anthropic(tool_names=["nonexistent"])
    assert len(schemas) == 0
