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
