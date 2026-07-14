"""
:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from collections.abc import Iterator

import pytest

from byceps.byceps_app import BycepsApp
from byceps.services.site.models import Site, SiteID

from tests.helpers import create_site


@pytest.fixture(scope='package')
def totalverplant_site(party, board) -> Site:
    return create_site(
        SiteID('totalverplant'),
        party.brand_id,
        title='total-verpLANt',
        server_name='totalverplant.test',
        party_id=party.id,
        board_id=board.id,
    )


@pytest.fixture(scope='package')
def totalverplant_site_app(
    database, make_site_app, totalverplant_site
) -> Iterator[BycepsApp]:
    app = make_site_app('totalverplant.test', totalverplant_site.id)
    with app.app_context():
        yield app
