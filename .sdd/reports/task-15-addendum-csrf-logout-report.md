# Task 15 Addendum: CSRF Enforcement on POST /logout

## Gap

`POST /logout` in `app/auth/routes.py` depended only on `Depends(get_current_user)`.
Every other mutating route (POST/DELETE under `/api/*`) also depends on
`Depends(require_csrf)`. The project plan states as a hard global constraint:
"All mutating routes (POST/DELETE) require both a valid session AND a matching
CSRF header — no exceptions." A security review confirmed `POST /logout` with
no `X-CSRF-Token` header returned 200 instead of 403.

## Fix

`app/auth/routes.py`:
- Imported `require_csrf` alongside `get_current_user` from `app.auth.dependencies`.
- Added `_csrf=Depends(require_csrf)` as an additional parameter on the `logout`
  route function, matching the exact pattern used by every other mutating route
  in `app/files/routes.py` (e.g. `rename_file`, `move_file`, `delete_file`,
  `upload_file`), which all combine `user=Depends(get_current_user)` with
  `_csrf=Depends(require_csrf)`.
- `require_csrf` (in `app/auth/dependencies.py`) already depends on
  `get_current_user` internally and reads `request.state.session`, which FastAPI's
  dependency cache ensures is only computed once per request even though both
  `get_current_user` and `require_csrf` are declared as separate parameters — no
  duplicate session lookups.

Resulting signature:

```python
@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    ...
```

## Tests

`tests/test_auth_routes.py`:
- Updated `test_logout_clears_session` to send `X-CSRF-Token: client.cookies["csrf_token"]`
  on the `POST /logout` call, since it previously relied on the old permissive
  behavior (no CSRF header) and would now receive 403 instead of 200.
- Added `test_logout_requires_csrf`: logs in fully (password + TOTP), then calls
  `POST /logout` with a valid session cookie but no `X-CSRF-Token` header, and
  asserts the response is 403 and that `session_token` remains present in the
  client's cookie jar (i.e. logout did not succeed and the session was not
  invalidated).

## Test Output

`pytest tests/test_auth_routes.py -v`: 6 passed
(`test_login_flow_success`, `test_login_wrong_password`,
`test_login_lockout_after_repeated_failures`, `test_login_verify_wrong_code`,
`test_logout_clears_session`, `test_logout_requires_csrf`)

`pytest -v` (full suite): 64 passed, 0 failed, 192 warnings (pre-existing
deprecation warnings unrelated to this change — `PydanticDeprecatedSince20`,
`asyncio.iscoroutinefunction` deprecation, FastAPI `on_event` deprecation).

## Files Touched

- `app/auth/routes.py` — added CSRF dependency to `POST /logout`.
- `tests/test_auth_routes.py` — updated existing logout test to send CSRF
  header; added new test asserting 403 when the header is missing.
