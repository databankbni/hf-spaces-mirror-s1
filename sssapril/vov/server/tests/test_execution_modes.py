"""
ExecutionModeService 单元测试

覆盖：
1. 加载 execution_modes.json
2. 三种 autonomy_level × 三种 variant 都能正确返回 system_suffix
3. 优先级：project_override > variant 参数 > 环境变量 > default
4. 不存在的 variant 回退到 default
5. 不存在的 autonomy_level 返回空字符串
6. 热重载：修改 mtime 后重读
7. get_mode_info 返回正确元数据
"""
import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def reset_service():
    """每个测试前重置单例"""
    from app.config import ExecutionModeService
    ExecutionModeService.reset()
    yield
    ExecutionModeService.reset()


@pytest.fixture
def clean_env():
    """清理 AGENTFLOW_EXEC_VARIANT 环境变量"""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENTFLOW_EXEC_VARIANT", None)
        yield


def test_load_config():
    """测试配置文件能被加载"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    modes = service._config.get("modes", {})
    assert "full_auto" in modes
    assert "semi_auto" in modes
    assert "manual" in modes


def test_full_auto_default_variant():
    """full_auto 默认用 balanced 变体"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    suffix = service.get_system_suffix(autonomy_level="full_auto")
    assert "## 自主模式 - 全自动" in suffix
    assert "平衡" in suffix


def test_semi_auto_default_variant():
    """semi_auto 默认用 balanced 变体"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    suffix = service.get_system_suffix(autonomy_level="semi_auto")
    assert "## 自主模式 - 半自动" in suffix


def test_manual_default_variant():
    """manual 默认用 balanced 变体"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    suffix = service.get_system_suffix(autonomy_level="manual")
    assert "## 自主模式 - 手动" in suffix


def test_explicit_variant_strict():
    """显式指定 strict 变体"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    suffix = service.get_system_suffix(autonomy_level="full_auto", variant="strict")
    assert "严格" in suffix
    assert "立即开始工具调用" in suffix


def test_explicit_variant_conservative():
    """显式指定 conservative 变体"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    suffix = service.get_system_suffix(autonomy_level="full_auto", variant="conservative")
    assert "保守" in suffix
    assert "5 个工具调用" in suffix


def test_unknown_variant_falls_back_to_default(clean_env):
    """不存在的 variant 回退到 default"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    suffix = service.get_system_suffix(autonomy_level="full_auto", variant="nonexistent")
    # 应该回退到 default (balanced)
    assert "平衡" in suffix


def test_unknown_autonomy_level_returns_empty(clean_env):
    """不存在的 autonomy_level 返回空字符串"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    suffix = service.get_system_suffix(autonomy_level="unknown_mode")
    assert suffix == ""


def test_project_override_takes_priority(clean_env):
    """项目级 override 优先级最高"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    # 即便 variant 参数是 balanced，项目级 override 是 strict
    suffix = service.get_system_suffix(
        autonomy_level="full_auto",
        variant="balanced",
        project_override="strict",
    )
    assert "严格" in suffix


def test_env_variable_override_mode_specific(clean_env):
    """环境变量：full_auto_strict 形式只切 full_auto"""
    os.environ["AGENTFLOW_EXEC_VARIANT"] = "full_auto_strict"
    from app.config import ExecutionModeService
    ExecutionModeService.reset()
    service = ExecutionModeService.instance()

    # full_auto 应该用 strict
    suffix_full = service.get_system_suffix(autonomy_level="full_auto")
    assert "严格" in suffix_full

    # semi_auto 不受 full_auto_strict 影响
    suffix_semi = service.get_system_suffix(autonomy_level="semi_auto")
    assert "严格" not in suffix_semi


def test_env_variable_override_bare(clean_env):
    """环境变量：裸 strict 形式切所有 mode 的 strict"""
    os.environ["AGENTFLOW_EXEC_VARIANT"] = "strict"
    from app.config import ExecutionModeService
    ExecutionModeService.reset()
    service = ExecutionModeService.instance()

    for level in ("full_auto", "semi_auto", "manual"):
        suffix = service.get_system_suffix(autonomy_level=level)
        assert "严格" in suffix, f"{level} should use strict, got: {suffix[:50]}"


def test_env_variable_default_value(clean_env):
    """环境变量：设 default 等同不设"""
    os.environ["AGENTFLOW_EXEC_VARIANT"] = "default"
    from app.config import ExecutionModeService
    ExecutionModeService.reset()
    service = ExecutionModeService.instance()

    suffix = service.get_system_suffix(autonomy_level="full_auto")
    # 应该用 default (balanced)
    assert "平衡" in suffix


def test_priority_chain(clean_env):
    """优先级链：project_override > variant > env > default"""
    from app.config import ExecutionModeService
    os.environ["AGENTFLOW_EXEC_VARIANT"] = "conservative"
    ExecutionModeService.reset()
    service = ExecutionModeService.instance()

    # 全部参数都给：project_override 是 strict，应该胜出
    suffix = service.get_system_suffix(
        autonomy_level="full_auto",
        variant="balanced",  # 次优先级
        project_override="strict",  # 最高优先级
    )
    assert "严格" in suffix


def test_get_mode_info():
    """get_mode_info 返回正确元数据"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    info = service.get_mode_info(autonomy_level="full_auto")
    assert info["mode"] == "full_auto"
    assert info["variant"] == "balanced"
    assert info["intensity"] == "medium"
    assert "label" in info


def test_list_variants():
    """list_variants 列出所有变体"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    variants = service.list_variants(autonomy_level="full_auto")
    assert "strict" in variants
    assert "balanced" in variants
    assert "conservative" in variants
    assert len(variants) == 3


def test_hot_reload_on_file_change(tmp_path):
    """热重载：修改 mtime 后自动重读"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    original_mtime = service._config_mtime

    # 模拟文件被修改（touch）
    service._config_path.touch()
    # 强制 mtime 推进（touch 不一定更新）
    import time
    time.sleep(0.1)
    new_mtime = service._config_path.stat().st_mtime
    # 设置一个更早的 mtime 模拟"文件被修改"
    service._config_mtime = new_mtime - 1

    service._maybe_reload()
    # 触发后 mtime 应该更新
    assert service._config_mtime >= new_mtime


# === ContextBuilder 集成测试 ===

@pytest.mark.asyncio
async def test_context_builder_includes_execution_suffix():
    """ContextBuilder.format_for_llm 应该包含 execution mode suffix"""
    # 这个测试需要 mock 整个 chain，需要更复杂的 setup
    # 先标记为 todo，用 e2e 测试覆盖
    pytest.skip("需要数据库 fixture，由 e2e 测试覆盖")


def test_all_prompts_non_empty():
    """所有变体的 system_suffix 都不为空"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    for mode in ("full_auto", "semi_auto", "manual"):
        for variant in service.list_variants(mode):
            suffix = service.get_system_suffix(autonomy_level=mode, variant=variant)
            assert len(suffix) > 50, f"{mode}/{variant} suffix too short: {len(suffix)} chars"


def test_prompts_distinct():
    """不同变体的 prompt 内容应该明显不同"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    # 不同 mode 用了不同变体名，统一用 list_variants
    for mode in ("full_auto", "semi_auto", "manual"):
        variants = service.list_variants(mode)
        suffixes = {v: service.get_system_suffix(autonomy_level=mode, variant=v) for v in variants}
        # 任意两个变体都不相等
        for i, v1 in enumerate(variants):
            for v2 in variants[i + 1:]:
                assert suffixes[v1] != suffixes[v2], (
                    f"{mode}/{v1} == {mode}/{v2}"
                )


def test_prompts_have_distinct_keywords():
    """每个变体都有可识别的关键词"""
    from app.config import ExecutionModeService
    service = ExecutionModeService.instance()
    keywords = {
        ("full_auto", "strict"):       "立即开始工具调用",
        ("full_auto", "balanced"):     "不要等用户催",
        ("full_auto", "conservative"): "5 个工具调用",
        ("semi_auto", "strict"):       "等 lead 指示",
        ("semi_auto", "balanced"):     "主动建议",
        ("manual", "strict"):          "不要主动调用任何工具",
    }
    for (mode, variant), kw in keywords.items():
        suffix = service.get_system_suffix(autonomy_level=mode, variant=variant)
        assert kw in suffix, f"{mode}/{variant} should contain '{kw}'"
