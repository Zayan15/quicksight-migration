# QuickSight Dataset Mapping & Dashboard Migration

## Overview

A Python toolkit for preparing cross-account QuickSight dataset mappings and orchestrating migration of analyses and dashboards through templates, with custom-theme handling and resource-sharing steps.

**Technologies:** Python · AWS CLI · Streamlit · Amazon QuickSight · JSON

**Engineering focus:** Cross-account automation, resource mapping, migration orchestration, and AWS permission management.

## Features

- Matches source analysis dataset placeholders to target datasets by case-insensitive name and writes a JSON mapping.
- Obtains account identity from the selected AWS profiles and validates profile access.
- Creates or updates a source template and grants the target account access to it.
- Includes target theme reuse/creation, target analysis and dashboard creation, and user-sharing operations.
- Generates versioned resource identifiers and timestamped analysis names.
- Includes a Streamlit interface for mapping generation and migration invocation.

## Limitations

- The interface passes the selected source and target profiles to the migration script. This argument alignment has been checked statically; live migration is unverified.
- The region is fixed in the scripts. Name-based matching can be ambiguous when dataset names repeat.
- Fixed delays are used between some operations rather than polling for successful resource readiness. A final success message does not independently verify that all asynchronous creation operations completed.
- The migration changes resources and permissions, including target-account template access and user edit/delete permissions. These actions were inspected but not executed.
- Source was reviewed statically and parsed for Python syntax; no live AWS migration or deployment was tested.

Live AWS migration has not been verified. Account configuration and credentials are not included.

## Local setup

Requires Python 3 and AWS credentials configured for an account you are authorized to use. Use a sandbox account with synthetic resources for demonstrations.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The AWS CLI must also be installed and the source and target profiles authenticated. Target datasets must already exist. The scripts currently use a fixed region.

```sh
streamlit run app.py
```

## Data handling

Local configuration, credentials, generated reports, spreadsheets, and asset bundles are excluded from this repository. Do not commit real account configuration, customer data, or secrets. AWS access uses configured local profiles or the SDK credential chain; no credentials are supplied.

## Validation

Python syntax was checked without executing application code. No AWS requests or deployment tests were run. The dependency list is not version-locked.
