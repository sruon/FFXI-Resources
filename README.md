# FFXI Resources

Automated FFXI DAT file parser. Publishes versioned releases on each client update.

## Local development

Requires Python 3.11+. Wheels are pulled from GitHub Releases — no Rust toolchain needed.

```sh
pip install -e .
```

Output format spec: [docs/FORMATS.md](docs/FORMATS.md).

## Release Notifications

Install the [FFXI Resources Release Notifier](https://github.com/apps/ffxi-resources-release-notifier) on your repository, then add a workflow:

```yaml
on:
  repository_dispatch:
    types: ["sruon/FFXI-Resources release"]

jobs:
  on-release:
    runs-on: ubuntu-latest
    steps:
      - run: echo "${{ github.event.action }}"
```
