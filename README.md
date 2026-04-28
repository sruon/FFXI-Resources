# FFXI Resources

Automated FFXI DAT file parser. Publishes versioned releases on each client update.

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
