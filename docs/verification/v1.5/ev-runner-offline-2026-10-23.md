# V1.5 EV runner offline verification

2026-10-23; code: current saved workspace.

Command: `.venv\Scripts\python.exe -m pytest backend/tests/guide/test_v15_evaluation_tool.py -q -p no:cacheprovider`. Exit=0; actual result: `5 passed, 1 warning in 131.84s (0:02:11)`.

Private providers only, normal SQLite/admission/audits and all 26 fixed input subscenarios. Checks IO consumption before errors, per-case/global bounds, explicit CLI flags, no preview credentials, immutable occupied slots/reports, exact row ACCEPTED/EDITED and isolated stale-original rejection, necessary over-budget samples send zero Chat, semantic reviews remain pending. Temporary databases and reports cleaned; no real APIs/user services or user data changes.

Initial fixture timing/profile fields were corrected. The EDITED verifier initially compared raw Markdown, which correctly escapes interior spaces as &#32;; it now checks actual plain table cells while retaining byte-exact non-target row checks. Product table serializer/provenance were not relaxed.
