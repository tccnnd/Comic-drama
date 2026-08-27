"""
HOW TO APPLY THIS FILE
======================
This is NOT a standalone module.  It contains only the new/changed lines that
need to be inserted into  backend/project_models.py.

1. Open  backend/project_models.py  in your editor.
2. Add  ``import re``  at the top (after the existing stdlib imports).
3. Insert the validation block below immediately after your imports /
   constants section, before the first function definition.
4. Replace the body of  ``project_dir()``  with the two lines shown.

The rest of project_models.py is unchanged.
"""

import re

# ---------------------------------------------------------------------------
# Project-ID validation – defence against path-traversal via crafted IDs
# ---------------------------------------------------------------------------
_PROJECT_ID_PATTERN = re.compile(r"^proj_[0-9]{8}_[0-9]{6}_[a-f0-9]{6}$")


def _validate_project_id(project_id: str) -> None:
    """Raise ValueError if *project_id* does not match the expected format.

    Prevents ``../``-style traversal from reaching the filesystem.
    FastAPI callers will see this as a 500 unless you catch it at the route
    layer – add an HTTPException wrapper there if you want a 400 response:

        try:
            _validate_project_id(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    """
    if not _PROJECT_ID_PATTERN.match(project_id):
        raise ValueError(
            f"Invalid project_id format {project_id!r}. "
            "Expected: proj_YYYYMMDD_HHMMSS_xxxxxx"
        )


# ---------------------------------------------------------------------------
# REPLACEMENT for the existing project_dir() function
# ---------------------------------------------------------------------------
# (WORKSPACE is already defined in the original file – keep that line as-is)

def project_dir(project_id: str):          # return type Path – keep original annotation
    _validate_project_id(project_id)
    return WORKSPACE / project_id           # WORKSPACE unchanged
