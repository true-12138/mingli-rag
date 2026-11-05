# -*- coding: utf-8 -*-
"""Agent State：版本要稳定、要对改动敏感、要能指出改了哪个文件。"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import agent_state


def _snapshot_to(tmp_path: Path):
    """把真实的 prompts/ 与 agent_config.json 复制到临时目录，避免测试改仓库文件。"""
    prompt_dir = tmp_path / "prompts"
    shutil.copytree(agent_state.DEFAULT_PROMPT_DIR, prompt_dir)
    config_path = tmp_path / "agent_config.json"
    shutil.copy(agent_state.DEFAULT_CONFIG_PATH, config_path)
    return prompt_dir, config_path


def test_version_is_stable_for_same_files(tmp_path):
    prompt_dir, config_path = _snapshot_to(tmp_path)
    a = agent_state.manifest(prompt_dir, config_path)
    b = agent_state.manifest(prompt_dir, config_path)

    assert a["version"] == b["version"]
    assert len(a["version"]) == 64
    assert set(a["files"]) == {
        "prompts/" + name for name in agent_state.PROMPT_FILES.values()
    }


def test_editing_one_prompt_changes_version_and_diff_names_it(tmp_path):
    prompt_dir, config_path = _snapshot_to(tmp_path)
    before = agent_state.manifest(prompt_dir, config_path)

    target = prompt_dir / "planner.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n补一条规则。\n", encoding="utf-8")
    after = agent_state.manifest(prompt_dir, config_path)

    assert after["version"] != before["version"]
    delta = agent_state.diff(before, after)
    assert delta["same"] is False
    assert delta["changed_files"] == ["prompts/planner.md"]
    assert delta["config_changed"] == []


def test_config_change_changes_version(tmp_path):
    prompt_dir, config_path = _snapshot_to(tmp_path)
    before = agent_state.manifest(prompt_dir, config_path)

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg["max_steps"] = int(cfg["max_steps"]) + 1
    config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    after = agent_state.manifest(prompt_dir, config_path)

    assert after["version"] != before["version"]
    delta = agent_state.diff(before, after)
    assert delta["changed_files"] == []
    assert delta["config_changed"] == ["max_steps"]


def test_load_prompt_returns_file_content_verbatim(tmp_path):
    prompt_dir, _ = _snapshot_to(tmp_path)
    expected = (prompt_dir / "verifier.md").read_text(encoding="utf-8")
    assert agent_state.load_prompt("verifier", prompt_dir) == expected


def test_unregistered_prompt_name_is_rejected():
    try:
        agent_state.load_prompt("not_registered")
    except KeyError as exc:
        assert "未登记" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("未登记的提示词应该直接报错，而不是静默返回空串")
