from pathlib import Path

import pytest
from quickops.execution import (
    CommandPolicy,
    CommandPolicyError,
    CommandRisk,
    ControlledCommandExecutor,
    ManualCommandExecutor,
)


@pytest.fixture
def policy(tmp_path: Path) -> CommandPolicy:
    return CommandPolicy((tmp_path,))


def test_readonly_command_is_classified_and_executed(policy: CommandPolicy, tmp_path: Path) -> None:
    decision = policy.classify("uname -s")
    assert decision.risk == CommandRisk.READONLY

    result = ControlledCommandExecutor(policy, cwd=tmp_path).execute(decision)
    assert result.exit_code == 0
    assert result.output.strip()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rm file.txt", CommandRisk.HIGH),
        ("rm -rf cache", CommandRisk.CRITICAL),
        ("sudo uptime", CommandRisk.HIGH),
        ("sh -c uptime", CommandRisk.MEDIUM),
        ("uptime | cat", CommandRisk.PROHIBITED),
        ("/tmp/custom-tool --check", CommandRisk.MEDIUM),
        ("curl https://example.com", CommandRisk.MEDIUM),
        ("docker ps", CommandRisk.READONLY),
        ("docker compose logs", CommandRisk.READONLY),
        ("docker system prune", CommandRisk.CRITICAL),
        ("docker rm app", CommandRisk.HIGH),
        ("systemctl status nginx", CommandRisk.READONLY),
        ("systemctl restart nginx", CommandRisk.MEDIUM),
        ("kubectl get pods", CommandRisk.READONLY),
        ("kubectl delete pod app", CommandRisk.HIGH),
        ("git status", CommandRisk.READONLY),
        ("git branch", CommandRisk.READONLY),
        ("git reset --hard", CommandRisk.HIGH),
        ("cat /etc/hosts", CommandRisk.READONLY),
        ("nvidia-smi", CommandRisk.READONLY),
        ("nvidia-smi --query-gpu=memory.used", CommandRisk.READONLY),
        ("find . -delete", CommandRisk.HIGH),
        ("chmod -R 777 data", CommandRisk.HIGH),
        ("unknown-ops-command --check", CommandRisk.MEDIUM),
    ],
)
def test_common_operations_receive_impact_based_risk(
    policy: CommandPolicy, command: str, expected: CommandRisk
) -> None:
    decision = policy.classify(command)
    assert decision.risk == expected
    assert decision.reason


def test_workspace_creation_is_low_risk_and_external_creation_needs_approval(
    policy: CommandPolicy, tmp_path: Path
) -> None:
    allowed = policy.classify(f"touch {tmp_path / 'approved.txt'}")
    denied = policy.classify("touch /tmp/outside-quickops.txt")

    assert allowed.risk == CommandRisk.LOW
    assert denied.risk == CommandRisk.MEDIUM


def test_executor_refuses_prohibited_decision(policy: CommandPolicy, tmp_path: Path) -> None:
    with pytest.raises(CommandPolicyError):
        ControlledCommandExecutor(policy, cwd=tmp_path).execute(policy.classify("uptime | cat"))


def test_argv_classifier_allows_literal_shell_characters_but_rejects_control_tokens(
    policy: CommandPolicy,
) -> None:
    literal = policy.classify_argv(["echo", "$HOME"])
    compound = policy.classify_argv(["uptime", "|", "cat"])

    assert literal.risk == CommandRisk.READONLY
    assert compound.risk == CommandRisk.PROHIBITED


def test_manual_executor_preserves_native_shell_semantics(tmp_path: Path) -> None:
    executor = ManualCommandExecutor(cwd=tmp_path, shell="/bin/sh", system_name="linux")
    result = executor.execute("printf 'quickops\\n' | tr a-z A-Z")

    assert result.exit_code == 0
    assert result.output == "QUICKOPS\n"
    assert result.truncated is False


def test_manual_executor_truncates_output(tmp_path: Path) -> None:
    executor = ManualCommandExecutor(
        cwd=tmp_path,
        shell="/bin/sh",
        system_name="linux",
        max_output_bytes=4,
    )
    result = executor.execute("printf 123456")

    assert result.exit_code == 0
    assert result.truncated is True
    assert result.output.startswith("1234")


def test_windows_manual_executor_uses_cmd_without_subprocess_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class Completed:
        stdout = b"ok"
        stderr = b""
        returncode = 0

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> Completed:
        captured["argv"] = argv
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr("quickops.execution.subprocess.run", fake_run)
    executor = ManualCommandExecutor(
        cwd=tmp_path,
        system_name="windows",
        shell="cmd.exe",
    )
    result = executor.execute("echo hello && echo world")

    assert result.exit_code == 0
    assert captured["argv"] == (
        "cmd.exe",
        "/D",
        "/S",
        "/C",
        "echo hello && echo world",
    )
    assert captured["shell"] is False
