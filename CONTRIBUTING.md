# Contributing

Create an environment for development with `tox`:

```shell
tox devenv -e lint
source venv/bin/activate
```

## Testing

This project uses `tox` for managing test environments. There are some pre-configured environments
that can be used for linting and formatting code when you're preparing contributions to the charm:

```shell
tox run -e static        # Static analysis
tox run -e lint          # code style
tox run -e unit          # unit tests
tox                      # runs 'format', 'lint', and 'unit' environments
```
