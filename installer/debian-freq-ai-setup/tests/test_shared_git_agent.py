"""Run as root in a private mount namespace with tmpfs at /etc/freq-shared-git."""
import grp
import importlib.machinery
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path("/etc/freq-shared-git")
    if os.geteuid() or not os.path.ismount(root):
        raise SystemExit("requires isolated tmpfs shared Git config")
    setup = importlib.machinery.SourceFileLoader("shared_setup",
        "/usr/local/libexec/freq-ai-setup/configure-shared-git").load_module()
    os.chown(root, 0, grp.getgrnam("freq-agents").gr_gid)
    root.chmod(0o750)
    agent = sys.argv[1]
    config = dict(name="Shared Fixture", email="fixture@example.invalid",
                  login="fixture-account", token="ghp_FAKE_NOT_A_REAL_CREDENTIAL")
    def sandbox(command):
        return subprocess.run(["runuser", "-u", agent, "--", "env", "FREQ_NO_BANNER=1",
            "SSH_ORIGINAL_COMMAND=cd; " + command, "/usr/local/sbin/freq-agent-sandbox"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    setup.publish(root, config, grp.getgrnam("freq-agents").gr_gid)
    result = sandbox("git var GIT_AUTHOR_IDENT")
    assert result.returncode == 0 and "Shared Fixture <fixture@example.invalid>" in result.stdout
    result = sandbox("printf 'protocol=https\\nhost=github.com\\n\\n' | GIT_TERMINAL_PROMPT=0 git credential fill")
    assert result.returncode == 0 and config["token"] in result.stdout
    result = sandbox("printf 'protocol=https\\nhost=github.com.evil\\n\\n' | GIT_TERMINAL_PROMPT=0 git credential fill")
    assert result.returncode != 0 and config["token"] not in result.stdout + result.stderr
    result = sandbox("gh --version")
    assert result.returncode == 0
    config.update(name="Rotated Fixture", email="rotated@example.invalid", token="ghp_ROTATED_FAKE")
    setup.publish(root, config, grp.getgrnam("freq-agents").gr_gid)
    result = sandbox("git var GIT_AUTHOR_IDENT")
    assert result.returncode == 0 and "Rotated Fixture <rotated@example.invalid>" in result.stdout
    result = sandbox("printf 'protocol=https\\nhost=github.com\\n\\n' | GIT_TERMINAL_PROMPT=0 git credential fill")
    assert result.returncode == 0 and config["token"] in result.stdout
    denied = subprocess.run(["runuser", "-u", "nobody", "--", "test", "-r",
                             str(root / "config.json")])
    assert denied.returncode != 0
    print("SHARED_GIT_AGENT_PASS identity=live rotation=live github-only=yes unrelated-user=denied")


if __name__ == "__main__":
    main()
