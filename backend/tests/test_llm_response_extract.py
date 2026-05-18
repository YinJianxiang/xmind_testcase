"""extract_json_object / extract_text_* 与 TS 实现对齐的单测。"""

from app.services import llm_response_extract as ex


def test_extract_json_object_plain_braces():
    assert ex.extract_json_object('prefix {"a":1} suffix') == '{"a":1}'


def test_extract_json_object_prefers_json_fence():
    raw = """说明一下
```json
{"x": 1}
```
尾巴"""
    assert ex.extract_json_object(raw).strip() == '{"x": 1}'


def test_extract_json_object_generic_fence():
    raw = """```
{"y": 2}
```"""
    assert ex.extract_json_object(raw) == '{"y": 2}'


def test_extract_json_object_no_braces_returns_trimmed_source():
    s = "  no json here  "
    assert ex.extract_json_object(s) == "no json here"


def test_extract_text_from_model_response_string_content():
    assert ex.extract_text_from_model_response({"content": "  hello  "}) == "hello"


def test_extract_text_from_model_response_block_content():
    result = {
        "content": [
            {"text": "a"},
            "b",
        ]
    }
    assert ex.extract_text_from_model_response(result) == "a\nb"


def test_extract_text_from_model_response_falls_back_to_agent_shape():
    agent = {"messages": [{"role": "user", "content": "u"}, {"role": "assistant", "content": "  ans  "}]}
    assert ex.extract_text_from_model_response(agent) == "ans"


def test_extract_text_from_agent_result_last_message():
    data = {"messages": [{"content": "old"}, {"content": [{"text": "line"}]}]}
    assert ex.extract_text_from_agent_result(data) == "line"


def test_extract_text_object_with_no_usable_content_returns_empty():
    class Obj:
        content = None

    assert ex.extract_text_from_model_response(Obj()) == ""


def test_collect_tool_messages_graphoutput_and_serialized_dict():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.types import GraphOutput

    msgs = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"name": "x", "id": "1", "args": {}}]),
        ToolMessage(content='{"code":0}', tool_call_id="1", name="x"),
    ]
    assert len(ex.collect_tool_messages_from_agent_result({"messages": msgs})) == 1
    go = GraphOutput(value={"messages": msgs}, interrupts=())
    assert len(ex.collect_tool_messages_from_agent_result(go)) == 1

    lc_style = {
        "messages": [
            {"type": "tool", "data": {"content": '{"k":1}', "tool_call_id": "t1", "name": "wiki_v1_node_search"}}
        ]
    }
    collected = ex.collect_tool_messages_from_agent_result(lc_style)
    assert len(collected) == 1
    assert collected[0]["name"] == "wiki_v1_node_search"

