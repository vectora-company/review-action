# Contributing

## Setup

You need `bash`, `curl`, `jq`, `tar`, [`gh`](https://cli.github.com),
[`uv`](https://docs.astral.sh/uv/) and `shellcheck`.

```bash
uv sync
uv run pytest
uv run ruff check tests
shellcheck scripts/review.sh
```

The tests run `scripts/review.sh` for real against a simulated panel (a local
HTTP server) with doubles for `gh` and `vectora-cli`, so no network or account
is needed.

## Changing the action

- The logic lives in `scripts/review.sh`; `action.yml` only maps inputs and
  event data to environment variables. Never interpolate `${{ ... }}` inside a
  `run:` script.
- Follow the panel contract in `services/src/gha-bot/routes.ts`
  (`/gha-bot/config`, `/gha-bot/download/latest`, the self-hosted job
  endpoints). A change to the contract needs a matching test.
- Every behavior needs a happy-path test and an error-path test in
  `tests/test_review.py`.
- Add the new input to the README table and to `action.yml`.

## Pull requests

Use Conventional Commits for the title (`fix:`, `feat:`, `ci:`...). Describe
the change and how you checked it.

## Releases

Push a `vX.Y.Z` tag; the `Release` workflow moves the `vX` tag to it.
