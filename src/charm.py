#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Placeholder charm."""

from ops import CharmBase
from ops.main import main


class PlaceHolderCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)


if __name__ == "__main__":
    main(PlaceHolderCharm)
