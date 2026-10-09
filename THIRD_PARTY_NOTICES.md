# Third-party notices

## Card templates

`assets/card_templates/` contains cropped card artwork used by the optional
card-image matcher. The crops are derived from official game card images and
are included only as recognition data. They are not original artwork by the
Camp Vision contributors. Check the game publisher's terms and local law
before redistributing these files or using them commercially.

The `tools/update_card_templates.py` helper can rebuild the templates from the
official card-image endpoint instead of relying on the checked-in crops.

## Dependencies

Runtime dependencies are listed in `pyproject.toml` and `requirements.txt`.
Each dependency remains under its own license.
