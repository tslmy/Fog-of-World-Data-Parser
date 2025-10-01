# Fog of World Data Parser

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
![Coverage Status](coverage.svg)
![License](https://img.shields.io/github/license/tslmy/Fog-of-World-Data-Parser)

A parser for the data used by [Fog of World](https://fogofworld.app/).

![screenshot](./.github/screenshot.png)

Motivation for building this library can be found in this [blog post](https://www.zijun.dev/en/posts/fog-of-world-data-parser/).

> [!NOTE]
> Check out the web app for visualizing and editing the data of Fog of World App, [FogMachine](https://github.com/CaviarChen/fog-machine), made by the original author.

To update coverage badge, run:

```shell
uv run pytest --cov=src/ ; uv run coverage-badge -f -o coverage.svg
```
