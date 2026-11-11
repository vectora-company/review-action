# Vectora Bot Review Action

GitHub Action that asks Vectora Bot to review a pull request and publishes the
result as one editable issue comment. It requires an active Vectora Pro
subscription and a `VECTORA_BOT_TOKEN` from the Vectora dashboard.

## Requirements

- A Vectora Pro account with the GitHub Bot configured at
  [bot.vectora.company](https://bot.vectora.company).
- A `VECTORA_BOT_TOKEN`. Limit it to the repositories that should use the bot
  when creating the token.
- A GitHub Actions runner on Ubuntu x64. The hosted review path downloads the
  Linux x64 `vectora-cli` binary.
- `curl`, `gh`, `jq`, and `tar`. GitHub's `ubuntu-24.04` runner includes them.

## Install

1. In the Vectora Bot dashboard, configure a provider and model, choose a
   review style, and create a token. Copy the token when it is shown.
2. In the repository, create a GitHub Environment named `vectora-bot` and add
   the token as the `VECTORA_BOT_TOKEN` environment secret.
3. Add `.github/workflows/vectora-review.yml`:

```yaml
name: Vectora Bot Review

on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]

permissions:
  issues: write
  pull-requests: read

concurrency:
  group: vectora-bot-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    runs-on: ubuntu-24.04
    environment: vectora-bot
    steps:
      - uses: vectora-company/review-action@v1
        with:
          token: ${{ secrets.VECTORA_BOT_TOKEN }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

The action does not need to check out the pull request. Do not add a checkout
of the PR head or run scripts from the PR in this workflow: `pull_request_target`
has access to the environment secret and write permission to publish the
comment. The action reads the diff through GitHub's API and treats it as review
input; it does not execute the changed code.

The environment can require approval before its secret is released. This is
useful for public repositories that accept pull requests from outside
contributors.

## Review modes

The action requests the current configuration from the Vectora Services API
for every run:

- **Hosted:** Vectora returns the configured provider, model, style, and
  provider API key to the runner. The action masks the key, downloads the
  current Linux x64 `vectora-cli`, and runs a one-shot review. The provider key
  is available to the review process on the ephemeral GitHub runner.
- **Self-hosted:** when self-hosted review is enabled and the Vectora instance
  is connected, the action sends the diff to the Vectora Services gateway,
  waits for the result, and publishes it. The provider key stays on the
  self-hosted Vectora instance. If the instance is offline, Services can return
  the hosted configuration instead.

On later runs, the action edits its previous comment, identified by an HTML
marker, instead of adding another comment. It skips draft pull requests by
default and also skips a PR whose title contains `[skip vectora]`.

## Inputs

| Name | Required | Default | Description |
|---|---:|---|---|
| `token` | yes | — | `VECTORA_BOT_TOKEN`; store it in a GitHub Environment secret. |
| `github-token` | yes | — | Token for reading the PR diff and creating/updating the comment. |
| `panel-url` | no | `https://bot.vectora.company` | HTTPS base URL of the Vectora Bot API. |
| `skip-draft` | no | `true` | Skip review while the PR is a draft. |
| `skip-marker` | no | `[skip vectora]` | Skip when this text appears in the PR title. Set to an empty string to disable. |
| `self-hosted-timeout-seconds` | no | `600` | Maximum wait for self-hosted review; accepted range is 1–21600 seconds. |

## Outputs

| Name | Description |
|---|---|
| `skipped` | `true` when no review was posted: draft PR, skip marker, an empty diff, a diff above 6 MB, or a fork PR without access to the token. |

The action never fails a run for those skip cases; it fails when the panel,
the provider or GitHub reject a request that should have worked, and the error
message names the cause (revoked token, missing Pro subscription, repository
scope, and so on).

## Limits and behavior

- Diffs above 6 MB are skipped, matching the limit the panel enforces.
- Reviews longer than 60,000 characters are truncated to fit a GitHub comment.
- Only one comment is kept per PR. If the previous comment cannot be edited,
  a new one is posted.
- The hosted `vectora-cli` runs with a minimal environment: it receives the
  provider key but not the GitHub token.
- `.github/vectora-review.yml` is not read by this action; trigger rules such
  as `on_request` are not implemented here.

## Permissions and fork pull requests

The example uses only the permissions needed by this action: `pull-requests:
read` to fetch the diff and `issues: write` to create or update the comment.
`pull_request_target` runs with the base repository's token permissions, even
for pull requests from forks. That is why this example does not check out or
execute pull request code. The Vectora token is stored in the `vectora-bot`
environment, so environment protection rules can require a maintainer's
approval before the job gets access to it.

## Troubleshooting

- **401/403 from configuration:** check that the token is active, the Vectora
  Pro subscription is active, and the token's repository scope includes this
  repository.
- **404/409 from configuration:** configure the provider and model in the
  dashboard again.
- **Hosted CLI download fails:** check the Services deployment and the public
  `gha-bot` binary in R2.
- **Self-hosted review times out:** confirm the Vectora instance is connected
  and that its GitHub Bot integration is enabled. Increase
  `self-hosted-timeout-seconds` if the review legitimately takes longer.
- **Comment permission error:** keep `issues: write` in the workflow
  permissions and confirm repository Actions policy permits `GITHUB_TOKEN` to
  write issue comments.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
