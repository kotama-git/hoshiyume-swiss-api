# Third-party notices

## Swiss Ephemeris

This service uses Swiss Ephemeris through `pyswisseph` and chooses the GNU Affero General Public License, version 3 or later, licensing option.

- Upstream source: https://github.com/aloistr/swisseph
- Ephemeris dataset commit: `9083a12d59e98034fb2337061481ac8800c16e64`
- Included-at-build dataset files: `sepl_18.se1`, `semo_18.se1`
- License information: https://www.astro.com/swisseph/

The exact upstream files and their expected SHA-256 values are declared in `scripts/fetch_ephemeris.py`. The data files are downloaded during the container build and are not stored in this repository.

## Python dependencies

The service dependency versions and constraints are declared in `pyproject.toml`. Each dependency remains subject to its own license and copyright notices.
