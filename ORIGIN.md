# Engine provenance

SWOTFlow Lite is an independent application and repository based on the user's
GeeUp / SWOTFlow v0.9.1 engine at commit
53ae120ba5a91ad5d10522887ffce4c1cbdd3517 (https://github.com/iameztoy/GeeUp).

The swotflow package retains the tested source selection, extraction, paired
mosaicking, manifests, verification, cleanup and Statistics implementations.
Some compatibility modules/dependencies remain internal; Lite launches only the
four-tab interface in swotflow_lite. It does not launch ChromeDriver. Keeping the
engine avoids rewriting scientific processing merely to simplify the interface.

Lite has its own versions, project marker, batch checkpoints, defaults, launchers
and GitHub releases. It does not modify the installed GeeUp application or open
GeeUp projects for migration. Investigation data, credentials and private user
settings are excluded from this repository.

Per-user engine state is isolated under SWOTFlowLite. Its optional storage
override is SWOTFLOW_LITE_DATA_HOME; the original app's override is ignored.
The root engineering documents retained from GeeUp describe compatibility-engine
features, including features not exposed in Lite. Start with README.md and
docs/lite-setup.md for this application's supported workflow.

Lite v0.3.0 adds an optional unlimited-row mode to the inherited Statistics
collector; its default behavior remains compatible. The Lite interface reads
those tables alongside its own batch, Cloud and NASA histories. Full-period tile
completion and display refresh are Lite-specific; source processing, upload,
cleanup and Resume implementations remain inherited.

Lite v0.4.0 exposes the inherited native zone/hemisphere mosaic algorithm through
a Lite-specific multi-band batch scheduler. It calls the same download,
duplicate-selection, extraction, mosaic, upload and guarded-cleanup stage engines;
it does not alter their scientific pixel algorithm. The inherited upload filter now
uses known original source tiles instead of guessing them from a grouped output's
N/S suffix. Grouped Cloud manifests also identify the grouping mode and source
tiles. The original GeeUp repository/installation is unchanged.

Lite v0.4.2 ports the shared lossless mosaic encoding, encoding provenance and oversized-staging diagnostics from the GeeUp v0.9.2 candidate. The full application UI is not included.
