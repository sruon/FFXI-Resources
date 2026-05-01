# FFXI Resources

Automated FFXI DAT file parser. Publishes versioned releases on each client update.

## Credits
- InoUno for [xi-tinkerer](https://github.com/InoUno/xi-tinkerer), used to parse efficiently many DAT files
- atom0s for [XiEvents](https://github.com/atom0s/XiEvents), used to decomp events and various DAT related snippets
- The Windower team for [ResourceExtractor](https://github.com/Windower/ResourceExtractor) and [POLUtils](https://github.com/Windower/POLUtils) for general DAT parsing knowledge

## Local development

Requires Python 3.11+. 
Integration with `xi-tinkerer` goes through pre-built wheels but you may need a Rust toolchain if they don't work.

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
