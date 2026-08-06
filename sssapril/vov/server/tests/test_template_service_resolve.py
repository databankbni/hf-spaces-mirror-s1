"""Smoke test for resolve_extends helper.

验证模板中 agent 的 `extends` 继承链能被正确解析:
- 无 extends 的 agent passthrough
- 标量字段: 覆盖 / 继承
- 数组字段: +extends 追加 / 无 +extends 覆盖
- 链式继承
- 循环继承检测
- 无效 extends 引用检测
"""
from app.services.template_service import resolve_extends


def test_no_extends_passthrough():
    """没 extends 字段的 agent 保持原样"""
    agents = [{"id": "judge", "name": "法官", "role": "planner", "system_prompt": "你是法官"}]
    result = resolve_extends(agents)
    assert len(result) == 1
    assert result[0] == {"id": "judge", "name": "法官", "role": "planner", "system_prompt": "你是法官"}
    assert "extends" not in result[0]


def test_basic_inheritance():
    """基础继承: 标量覆盖, 标量继承"""
    agents = [
        {"id": "player", "name": "玩家", "role": "custom", "system_prompt": "你是玩家", "llm_config": {"temperature": 0.7}},
        {"id": "p1", "name": "玩家1", "extends": "player", "system_prompt": "你是玩家1"},
    ]
    result = resolve_extends(agents)
    assert len(result) == 2
    # player 不变
    assert result[0]["system_prompt"] == "你是玩家"
    assert result[0]["llm_config"] == {"temperature": 0.7}
    # p1: prompt 覆盖, temperature 继承
    assert result[1]["name"] == "玩家1"
    assert result[1]["system_prompt"] == "你是玩家1"
    assert result[1]["llm_config"] == {"temperature": 0.7}
    assert "extends" not in result[1]


def test_array_extends_append():
    """数组 +extends: 追加"""
    agents = [
        {"id": "player", "name": "玩家", "tools": ["set_memory", "get_memory"], "skill_refs": ["self-memory"]},
        {"id": "judge", "name": "法官", "extends": "player",
         "tools": ["create_task", "+extends"], "skill_refs": ["game-state", "+extends"]},
    ]
    result = resolve_extends(agents)
    assert result[1]["tools"] == ["set_memory", "get_memory", "create_task"]
    assert result[1]["skill_refs"] == ["self-memory", "game-state"]


def test_array_override():
    """数组无 +extends: 完全覆盖"""
    agents = [
        {"id": "player", "name": "玩家", "tools": ["set_memory", "get_memory"]},
        {"id": "judge", "name": "法官", "extends": "player", "tools": ["create_task", "list_tasks"]},
    ]
    result = resolve_extends(agents)
    assert result[1]["tools"] == ["create_task", "list_tasks"]


def test_array_extends_dedup():
    """+extends 去重"""
    agents = [
        {"id": "player", "name": "玩家", "tools": ["set_memory", "get_memory"]},
        {"id": "p1", "name": "玩家1", "extends": "player", "tools": ["set_memory", "+extends"]},
    ]
    result = resolve_extends(agents)
    assert result[1]["tools"] == ["set_memory", "get_memory"]  # set_memory 不重复


def test_chain_inheritance():
    """链式继承: A extends B, B extends C"""
    agents = [
        {"id": "base", "name": "基础", "tools": ["t1"], "skill_refs": ["s1"]},
        {"id": "mid", "extends": "base", "tools": ["t2", "+extends"], "skill_refs": ["s2", "+extends"], "system_prompt": "mid"},
        {"id": "leaf", "extends": "mid", "tools": ["t3", "+extends"], "system_prompt": "leaf"},
    ]
    result = resolve_extends(agents)
    assert result[2]["tools"] == ["t1", "t2", "t3"]
    assert result[2]["skill_refs"] == ["s1", "s2"]
    assert result[2]["system_prompt"] == "leaf"


def test_cycle_detection():
    """循环继承抛 ValueError"""
    agents = [
        {"id": "a", "extends": "b"},
        {"id": "b", "extends": "a"},
    ]
    try:
        resolve_extends(agents)
        assert False, "应该抛 ValueError"
    except ValueError as e:
        assert "循环" in str(e)


def test_invalid_extends_ref():
    """extends 指向不存在的 id 抛 ValueError"""
    agents = [
        {"id": "a", "extends": "not_found"},
    ]
    try:
        resolve_extends(agents)
        assert False, "应该抛 ValueError"
    except ValueError as e:
        assert "not_found" in str(e)


def test_duplicate_id_raises():
    """重复 id 抛 ValueError"""
    agents = [
        {"id": "player", "name": "玩家1"},
        {"id": "player", "name": "玩家2"},
    ]
    try:
        resolve_extends(agents)
        assert False, "应该抛 ValueError"
    except ValueError as e:
        assert "重复" in str(e)