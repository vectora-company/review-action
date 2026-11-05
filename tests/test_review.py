"""Contrato de scripts/review.sh contra um painel simulado.

O painel (HTTP real em localhost), o `gh` e o `vectora-cli` são substituídos por
dublês; o script roda de verdade em bash.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review.sh"
REPOSITORY = "acme/widgets"
DIFF = "diff --git a/a.py b/a.py\n+print('hi')\n"

HOSTED = {
    "mode": "hosted",
    "provider": "anthropic",
    "model": "claude-sonnet-5",
    "api_key": "sk-secret-key",
    "review_style": "balanced",
}


@dataclass
class Panel:
    """Respostas programáveis do painel e registro das chamadas recebidas."""

    config: tuple[int, dict] = (200, HOSTED)
    submit: tuple[int, dict] = (202, {"job_id": "job-1"})
    jobs: list[tuple[int, dict]] = field(default_factory=list)
    requests: list[tuple[str, str, str, str]] = field(default_factory=list)
    url: str = ""
    stub_dir: str = ""


def _cli_tarball(stub_dir: str) -> bytes:
    script = (
        "#!/usr/bin/env bash\n"
        f"STUB_DIR='{stub_dir}'\n"
        'printf "%s\\n" "$ANTHROPIC_API_KEY" > "$STUB_DIR/cli_key"\n'
        'printf "%s\\n" "${GH_TOKEN:-absent}" > "$STUB_DIR/cli_gh_token"\n'
        'printf "%s\\n" "$*" > "$STUB_DIR/cli_args"\n'
        'cat > "$STUB_DIR/cli_stdin"\n'
        'echo "Looks fine."\n'
    ).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("vectora-cli")
        info.size = len(script)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(script))
    return buffer.getvalue()


@pytest.fixture
def panel():
    state = Panel()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, payload: dict | bytes) -> None:
            body = (
                payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            )
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _record(self) -> str:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else ""
            auth = self.headers.get("Authorization", "")
            state.requests.append((self.command, self.path, auth, body))
            return body

        def do_GET(self) -> None:
            self._record()
            if self.path.startswith("/gha-bot/config"):
                self._send(*state.config)
            elif self.path == "/gha-bot/download/latest":
                self._send(200, _cli_tarball(state.stub_dir))
            elif self.path.startswith("/gha-bot/review/"):
                status = state.jobs.pop(0) if len(state.jobs) > 1 else state.jobs[0]
                self._send(*status)
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            self._record()
            if self.path == "/gha-bot/review":
                self._send(*state.submit)
            else:
                self._send(404, {"error": "not_found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()


GH_STUB = r"""#!/usr/bin/env bash
printf '%s
' "$*" >> "$STUB_DIR/gh_calls"
case "$1" in
  pr) cat "$STUB_DIR/pr.diff" ;;
  api)
    input=""; method=GET; endpoint=""
    shift
    while [ $# -gt 0 ]; do
      case "$1" in
        --input) input="$2"; shift ;;
        --method) method="$2"; shift ;;
        --paginate|--jq) [ "$1" = "--jq" ] && shift ;;
        *) endpoint="$1" ;;
      esac
      shift
    done
    if [ -z "$input" ]; then cat "$STUB_DIR/existing_ids" 2>/dev/null || true; exit 0; fi
    if [ "$method" = PATCH ] && [ -f "$STUB_DIR/patch_fails" ]; then exit 1; fi
    jq -r .body "$input" > "$STUB_DIR/comment_body"
    echo "$method $endpoint" >> "$STUB_DIR/comment_calls" ;;
esac
"""


@dataclass
class Run:
    code: int
    out: str
    stub: Path

    def read(self, name: str) -> str:
        return (self.stub / name).read_text(encoding="utf-8")

    def exists(self, name: str) -> bool:
        return (self.stub / name).exists()


@pytest.fixture
def run_review(tmp_path, panel):
    stub = tmp_path / "stub"
    stub.mkdir()
    gh = stub / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    (stub / "pr.diff").write_text(DIFF)

    panel.stub_dir = stub.as_posix()

    def _run(**overrides: str) -> Run:
        env = {
            **os.environ,
            "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
            "STUB_DIR": str(stub),
            "INPUT_TOKEN": "vb-token",
            "INPUT_GITHUB_TOKEN": "ghs-token",
            "INPUT_PANEL_URL": panel.url,
            "INPUT_SKIP_DRAFT": "true",
            "INPUT_SKIP_MARKER": "[skip vectora]",
            "REPOSITORY": REPOSITORY,
            "PR_NUMBER": "7",
            "PR_TITLE": "feat: add thing",
            "PR_DRAFT": "false",
            "PR_HEAD_REPOSITORY": REPOSITORY,
            "RUNNER_TEMP": str(tmp_path / "runner"),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "REVIEW_POLL_INTERVAL": "0",
            "SELF_HOSTED_TIMEOUT_SECONDS": "5",
            "GH_TOKEN": "leak-me",
            **overrides,
        }
        for name in ("runner",):
            (tmp_path / name).mkdir(exist_ok=True)
        proc = subprocess.run(
            [shutil.which("bash") or "bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )
        return Run(proc.returncode, proc.stdout + proc.stderr, stub)

    return _run


def _output(tmp_path: Path) -> str:
    path = tmp_path / "output"
    return path.read_text() if path.exists() else ""


# --- modo hosted -----------------------------------------------------------------


def test_hosted_review_runs_the_cli_and_posts_a_comment(run_review, panel, tmp_path):
    result = run_review()

    assert result.code == 0, result.out
    comment = result.read("comment_body")
    assert comment.startswith("<!-- vectora-bot-review -->\nLooks fine.")
    assert "POST repos/acme/widgets/issues/7/comments" in result.read("comment_calls")
    assert "skipped=false" in _output(tmp_path)
    config_request = panel.requests[0]
    assert config_request[1] == "/gha-bot/config?repository=acme%2Fwidgets"
    assert config_request[2] == "Bearer vb-token"


def test_hosted_cli_gets_the_diff_on_stdin_and_a_clean_environment(run_review):
    result = run_review()

    assert result.code == 0, result.out
    assert DIFF in result.read("cli_stdin")
    assert "untrusted" in result.read("cli_stdin")
    assert result.read("cli_args").strip() == "run --model anthropic:claude-sonnet-5"
    assert result.read("cli_key").strip() == "sk-secret-key"
    # O vectora-cli não recebe o token do GitHub nem outros secrets do job.
    assert result.read("cli_gh_token").strip() == "absent"


def test_existing_review_comment_is_edited_not_duplicated(run_review):
    stub = None

    def prepare(result_stub: Path) -> None:
        (result_stub / "existing_ids").write_text("11\n42\n")

    # Cria o ambiente primeiro para poder semear o dublê do gh.
    first = run_review()
    stub = first.stub
    prepare(stub)
    (stub / "comment_calls").unlink()

    result = run_review()

    assert result.code == 0, result.out
    calls = result.read("comment_calls")
    assert "PATCH repos/acme/widgets/issues/comments/42" in calls
    assert "POST" not in calls


def test_comment_falls_back_to_a_new_one_when_editing_fails(run_review):
    first = run_review()
    (first.stub / "existing_ids").write_text("42\n")
    (first.stub / "patch_fails").write_text("")
    (first.stub / "comment_calls").unlink()

    result = run_review()

    assert result.code == 0, result.out
    assert (
        result.read("comment_calls").strip()
        == "POST repos/acme/widgets/issues/7/comments"
    )


# --- modo self-hosted ----------------------------------------------------------------


def test_self_hosted_posts_a_job_and_polls_until_done(run_review, panel):
    panel.config = (
        200,
        {"mode": "self-hosted", "job_endpoint": f"{panel.url}/gha-bot/review"},
    )
    panel.jobs = [
        (200, {"status": "pending"}),
        (200, {"status": "done", "review_text": "Review from my machine."}),
    ]

    result = run_review()

    assert result.code == 0, result.out
    assert "Review from my machine." in result.read("comment_body")
    post = next(r for r in panel.requests if r[0] == "POST")
    payload = json.loads(post[3])
    assert payload["diff"] == DIFF
    assert payload["metadata"]["repository"] == REPOSITORY
    assert payload["metadata"]["pull_request"] == "7"
    assert not result.exists("cli_args")


def test_self_hosted_failed_job_fails_the_step(run_review, panel):
    panel.config = (200, {"mode": "self-hosted"})
    panel.jobs = [(200, {"status": "failed", "error": "modelo indisponível"})]

    result = run_review()

    assert result.code != 0
    assert "modelo indisponível" in result.out
    assert not result.exists("comment_body")


def test_self_hosted_offline_instance_is_reported(run_review, panel):
    panel.config = (200, {"mode": "self-hosted"})
    panel.submit = (502, {"error": "not_delivered", "job_id": "j"})

    result = run_review()

    assert result.code != 0
    assert "offline" in result.out


def test_self_hosted_times_out_when_the_job_never_finishes(run_review, panel):
    panel.config = (200, {"mode": "self-hosted"})
    panel.jobs = [(200, {"status": "pending"})]

    result = run_review(SELF_HOSTED_TIMEOUT_SECONDS="1", REVIEW_POLL_INTERVAL="1")

    assert result.code != 0
    assert "não terminou" in result.out


# --- pular a revisão ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"PR_DRAFT": "true"}, "rascunho"),
        ({"PR_TITLE": "wip [skip vectora]"}, "[skip vectora]"),
        ({"INPUT_TOKEN": "", "PR_HEAD_REPOSITORY": "fork/widgets"}, "fork"),
    ],
)
def test_skipped_reviews_never_touch_the_panel(
    run_review, panel, tmp_path, overrides, reason
):
    result = run_review(**overrides)

    assert result.code == 0, result.out
    assert reason in result.out
    assert panel.requests == []
    assert "skipped=true" in _output(tmp_path)


def test_draft_is_reviewed_when_skip_draft_is_off(run_review):
    result = run_review(PR_DRAFT="true", INPUT_SKIP_DRAFT="false")

    assert result.code == 0, result.out
    assert result.exists("comment_body")


def test_empty_marker_disables_title_skipping(run_review):
    result = run_review(INPUT_SKIP_MARKER="", PR_TITLE="x [skip vectora]")

    assert result.code == 0, result.out
    assert result.exists("comment_body")


def test_pr_title_is_data_not_shell_code(run_review, tmp_path):
    marker = tmp_path / "pwned"
    title = f'feat: "; touch {marker}; echo "$(touch {marker})'

    result = run_review(PR_TITLE=title)

    assert result.code == 0, result.out
    assert not marker.exists()


def test_empty_diff_is_skipped(run_review):
    first = run_review()
    (first.stub / "pr.diff").write_text("")
    (first.stub / "comment_body").unlink()

    result = run_review()

    assert result.code == 0, result.out
    assert "não tem alterações" in result.out
    assert not result.exists("comment_body")


# --- erros do painel ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "hint"),
    [
        (401, "unauthorized", "revogado"),
        (403, "pro_required", "Pro"),
        (404, "not_configured", "ainda não foi configurado"),
        (409, "reconfigure_required", "reconfigure"),
        (403, "repo_scope_forbidden", "outro repositório"),
    ],
)
def test_panel_errors_are_translated(run_review, panel, status, code, hint):
    panel.config = (status, {"error": code})

    result = run_review()

    assert result.code != 0
    assert f"HTTP {status}" in result.out
    assert hint in result.out
    assert not result.exists("comment_body")


def test_missing_token_fails_for_same_repository_prs(run_review):
    result = run_review(INPUT_TOKEN="")

    assert result.code != 0
    assert "VECTORA_BOT_TOKEN" in result.out


@pytest.mark.parametrize(
    "broken",
    [
        {"mode": "weird"},
        {
            "mode": "hosted",
            "provider": "anthropic",
            "model": "m",
            "review_style": "balanced",
        },
        {**HOSTED, "provider": "ollama"},
    ],
)
def test_invalid_hosted_configuration_is_rejected(run_review, panel, broken):
    panel.config = (200, broken)

    result = run_review()

    assert result.code != 0
    assert not result.exists("comment_body")


def test_api_key_is_masked_in_the_log(run_review):
    result = run_review()

    assert "::add-mask::sk-secret-key" in result.out
    assert "leak-me" not in result.out


def test_empty_review_is_an_error(run_review, panel):
    panel.config = (200, {"mode": "self-hosted"})
    panel.jobs = [(200, {"status": "done", "review_text": ""})]

    result = run_review()

    assert result.code != 0
    assert "vazia" in result.out


def test_long_reviews_are_truncated_to_the_comment_limit(run_review, panel):
    panel.config = (200, {"mode": "self-hosted"})
    panel.jobs = [(200, {"status": "done", "review_text": "x" * 70000})]

    result = run_review()

    assert result.code == 0, result.out
    body = result.read("comment_body")
    assert len(body) < 65536
    assert "truncada" in body
