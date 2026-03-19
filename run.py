"""Run the pipeline on pallets/flask (full run with human review)."""

import sys

from gh_link_auditor.cli.main import main

sys.exit(main(["run", "https://github.com/pallets/flask", "--verbose", "--max-links", "20"]))
