# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## GitHub is used for everything

GitHub is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `master`.
2. If you've changed something, update the documentation.
3. Make sure your code passes lint checks (using `prek`).
4. Test your contribution.
5. Issue that pull request!

## Setting up

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run `uv sync` in the repo root.
It will create a virtualenv with all required packages. glocaltokens needs Python 3.12 or newer;
uv downloads a matching Python if you do not have one.

## Checks

We use [ruff](https://docs.astral.sh/ruff/) and [dprint](https://dprint.dev/)
to make sure the code follows the style, and mypy and pylint to check it.

You can run all checks with [prek](https://prek.j178.dev/), a faster drop-in replacement for `pre-commit`,
using the settings included in the repository.

Activate the `prek` git hook:

```console
$ uvx prek install
```

Now the checks will run every time you commit.

You can also run the checks on all repository files manually with this command:

```console
$ uvx prek run --all-files
```

## Tests

The checks above also run the tests. To run only the tests:

```console
$ uv run pytest
```

When writing unittests please follow the good practises like:

- Use `faker` to fake the data. See [examples](https://faker.readthedocs.io/en/master/)
- Use `unittest.mock` to patch objects/methods. See [examples](https://realpython.com/python-mock-library/)

## Labels and releases

Release notes are drafted automatically from merged pull requests. Labels decide where each pull request goes
in the notes and which version comes next:

- `breaking`: a major version.
- `feature`: a minor version.
- Anything else: a patch version.
- `skip-release`: leaves the pull request out of the release notes.

The next release uses the biggest of these among the pull requests merged since the last release.

Pull requests that only change dependencies, documentation, tests or GitHub files are labelled automatically.
Pull requests that change Python code need a label from a maintainer, such as `bug`, `feature` or `refactoring`.

## Report bugs using GitHub's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

Debug logs from `verbose=True` help a lot, but check them for anything private before you post them.

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.
