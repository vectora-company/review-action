# Security policy

## Reporting a vulnerability

Do not open a public issue. Open a private
[GitHub Security Advisory](https://github.com/vectora-ltda/review-action/security/advisories/new)
for this repository. Include the affected version (`@v1`, a tag or a commit),
the workflow that triggers it, the impact and, if possible, a minimal
reproduction. Remove credentials and personal data before sending.

## Supported versions

Only the latest `v1.x` release receives fixes. The `v1` tag always points to it.

## Security model

- `VECTORA_BOT_TOKEN` is read from an Environment secret and only sent to the
  Vectora panel over HTTPS (plain HTTP is accepted for loopback addresses only).
- In hosted mode the provider API key is masked in the log and handed only to
  the `vectora-cli` process, started with a minimal environment: it does not
  receive `GITHUB_TOKEN` or any other secret of the job.
- The pull request title and diff are untrusted input. They reach the script
  through environment variables, never through shell interpolation, and the
  review prompt tells the model not to follow instructions found inside them.
- The downloaded `vectora-cli` archive is rejected if it contains absolute or
  `..` paths. The binary is served by the Vectora panel without a signature;
  pin `panel-url` to a deployment you trust.
- Use `pull_request_target` only without checking out or running pull request
  code, as the README describes.
