# Codex Code Review smoke test

This file is a non-production test to verify whether Codex Automatic Review responds to a pull request and subsequent pushes.

## Scope

- Documentation only; no application code, migrations, CI, secrets, or runtime configuration changes.
- The pull request must not be merged. Close it after verifying review behavior.
- Expected result: Codex posts a review after a qualifying PR event or new push, depending on repository settings.

## Verification checklist

- [ ] The test pull request is open and targets `main`.
- [ ] Automatic Review is enabled for this repository.
- [ ] A Codex review appears after a qualifying event.
- [ ] The test pull request is closed without merging.

## Push trigger

This follow-up commit was pushed after opening the pull request to exercise the `On every push` trigger.
