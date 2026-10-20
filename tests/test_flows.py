"""End-to-end scenarios, run against memory+mock, memory+EVM (in-process blockchain) and fake-Supabase+mock."""
import re

import pytest
from fastapi.testclient import TestClient

from conftest import ADMIN, PASSWORD, csrf, find_id, login, post, signup

CODE_RE = re.compile(r"TM-\d{4}-[A-Z0-9]{4}-[A-Z0-9]{4}")
ISSUE = {"student_name": "Amara Okafor", "course": "Mechanical Engineering", "grade": "A", "issued_on": "2026-06-15"}


def make_admin(app) -> TestClient:
    app.state.ctx.auth.sign_up(ADMIN, PASSWORD, "Boss", "TrueMark")
    client = TestClient(app)
    assert login(client, ADMIN).status_code == 303
    return client


def make_school(app, email="registrar@greenfield.test", institution="Greenfield Secondary School") -> TestClient:
    client = TestClient(app)
    assert signup(client, email, institution=institution).status_code == 303
    return client


def approve(admin: TestClient, school_email: str) -> None:
    html = admin.get("/admin/users?status=pending").text
    row = html[html.index(school_email) :]
    uid = find_id(row, "/admin/users/")
    r = post(admin, f"/admin/users/{uid}/status", {"status": "approved"})
    assert r.status_code == 303


def issue(school: TestClient, **overrides) -> tuple[str, str]:
    r = post(school, "/issue", {**ISSUE, **overrides})
    assert r.status_code == 303, r.text
    page = school.get(r.headers["location"]).text
    return find_id(r.headers["location"], "/records/"), CODE_RE.search(page).group(0)


# ------------------------------------------------------------------------------------------ journey


def test_full_lifecycle(backend):
    app, _ = backend
    admin = make_admin(app)
    school = make_school(app)

    # A new school can sign in but cannot issue until an admin approves it.
    assert "waiting for approval" in school.get("/dashboard").text
    assert school.get("/issue").status_code == 403

    # The admin sees the application and approves it.
    overview = admin.get("/admin").text
    assert "Greenfield Secondary School" in overview and "Waiting for approval" in overview
    approve(admin, "registrar@greenfield.test")
    assert "Issue a record" in school.get("/dashboard").text

    # Issue -> anchored.
    rid, code = issue(school)
    page = school.get(f"/records/{rid}").text
    assert "Active" in page and "Revoke this record" in page

    # Anyone can verify, no sign-in.
    public = TestClient(app)
    ok = public.get(f"/verify/{code}")
    assert ok.status_code == 200 and "This record is unaltered." in ok.text and "Amara Okafor" in ok.text
    assert public.get(f"/api/verify/{code}").json()["status"] == "valid"

    # The exact printed copy passes; an edited grade or date fails and shows what changed.
    same = post(public, f"/verify/{code}/check", {"institution": "Greenfield Secondary School", "student_name": "Amara Okafor",
                                                    "course": "Mechanical Engineering", "grade": "A", "issued_on": "2026-06-15"})
    assert "Your copy matches the anchored record." in same.text
    forged = post(public, f"/verify/{code}/check", {"institution": "Greenfield Secondary School", "student_name": "Amara Okafor",
                                                     "course": "Mechanical Engineering", "grade": "B", "issued_on": "2026-06-20"})
    assert "Your copy does not match the anchored record." in forged.text
    assert "2 details differ" in forged.text

    # Whitespace and unicode form do not count as tampering.
    spaced = post(public, f"/verify/{code}/check", {"institution": "Greenfield  Secondary School", "student_name": " Amara   Okafor ",
                                                     "course": "Mechanical Engineering", "grade": "A", "issued_on": "2026-06-15"})
    assert "Your copy matches the anchored record." in spaced.text

    # Someone edits the database row directly: the public page now reports it as altered.
    store = app.state.ctx.store
    store.record_update(rid, {"grade": "A+"})
    altered = public.get(f"/verify/{code}")
    assert "This record has been altered." in altered.text and "Amara Okafor" not in altered.text
    assert public.get(f"/api/verify/{code}").json()["status"] == "altered"
    store.record_update(rid, {"grade": "A"})
    assert "This record is unaltered." in public.get(f"/verify/{code}").text

    # The school revokes it.
    r = post(school, f"/records/{rid}/revoke", {"reason": "Issued to the wrong student"})
    assert r.status_code == 303
    revoked = public.get(f"/verify/{code}")
    assert "This record was revoked." in revoked.text
    assert "Your copy matches, but the record was revoked." in post(public, f"/verify/{code}/check", {
        "institution": "Greenfield Secondary School", "student_name": "Amara Okafor", "course": "Mechanical Engineering",
        "grade": "A", "issued_on": "2026-06-15"}).text
    assert "Revoke this record" not in school.get(f"/records/{rid}").text

    # Everything above left a trail the admin can read.
    audit = admin.get("/admin/audit").text
    for action in ("user.signup", "user.approved", "record.issue", "record.anchor", "record.revoke"):
        assert action in audit


def test_certificate_page_for_anchored_record(backend):
    app, _ = backend
    admin, school = make_admin(app), make_school(app)
    approve(admin, "registrar@greenfield.test")
    rid, code = issue(school)
    cert = school.get(f"/records/{rid}/certificate")
    assert cert.status_code == 200 and code in cert.text and "<svg" in cert.text and "Amara Okafor" in cert.text


def test_unknown_and_malformed_codes(backend):
    app, _ = backend
    public = TestClient(app)
    for code in ("TM-2026-AAAA-BBBB", "not-a-code", "<img src=x onerror=alert(1)>"):
        r = public.get(f"/verify/{code}")
        assert r.status_code == 200 and "No record has this ID." in r.text and "<img src=x" not in r.text
    assert public.get("/api/verify/TM-2026-AAAA-BBBB").status_code == 404
    assert public.get("/qr/not-a-code.svg").status_code == 404
    assert public.get("/qr/TM-2026-AAAA-BBBB.svg").headers["content-type"].startswith("image/svg")


# ------------------------------------------------------------------------------------------ permissions


def test_schools_cannot_see_each_others_records(backend):
    app, _ = backend
    admin = make_admin(app)
    a, b = make_school(app, "a@one.test", "School One"), make_school(app, "b@two.test", "School Two")
    approve(admin, "a@one.test")
    approve(admin, "b@two.test")
    rid, _ = issue(a)
    assert b.get(f"/records/{rid}").status_code == 404
    assert post(b, f"/records/{rid}/revoke", {"reason": "not mine"}).status_code == 404
    assert "Amara Okafor" not in b.get("/dashboard").text
    assert admin.get(f"/records/{rid}").status_code == 200  # admins can open any record


def test_only_admins_reach_admin_pages(backend):
    app, _ = backend
    admin = make_admin(app)
    school = make_school(app)
    approve(admin, "registrar@greenfield.test")
    for url in ("/admin", "/admin/users", "/admin/records", "/admin/audit"):
        assert school.get(url).status_code == 403
        assert TestClient(app).get(url, follow_redirects=False).status_code == 303  # anonymous -> sign in
        assert admin.get(url).status_code == 200
    uid = find_id(admin.get("/admin/users").text[admin.get("/admin/users").text.index("registrar@"):], "/admin/users/")
    assert post(school, f"/admin/users/{uid}/role", {"role": "admin"}).status_code == 403


def test_anonymous_visitors_are_sent_to_sign_in(backend):
    app, _ = backend
    anon = TestClient(app)
    for url in ("/dashboard", "/issue"):
        r = anon.get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_suspended_school_is_locked_out_and_can_be_restored(backend):
    app, _ = backend
    admin, school = make_admin(app), make_school(app)
    approve(admin, "registrar@greenfield.test")
    users = admin.get("/admin/users").text
    uid = find_id(users[users.index("registrar@") :], "/admin/users/")
    assert post(admin, f"/admin/users/{uid}/status", {"status": "suspended"}).status_code == 303
    assert "suspended" in school.get("/dashboard").text.lower()
    assert school.get("/issue").status_code == 403
    assert post(admin, f"/admin/users/{uid}/status", {"status": "approved"}).status_code == 303
    assert school.get("/issue").status_code == 200


def test_admin_cannot_demote_or_suspend_themselves(backend):
    app, _ = backend
    admin = make_admin(app)
    users = admin.get("/admin/users").text
    html_after_self = users[users.index(ADMIN) :]
    # The admin's own row has no action buttons, but a forged request must still be refused.
    uid = app.state.ctx.store.profile_list(limit=10)[0]["id"]
    assert post(admin, f"/admin/users/{uid}/status", {"status": "suspended"}).status_code == 303
    assert post(admin, f"/admin/users/{uid}/role", {"role": "issuer"}).status_code == 303
    assert admin.get("/admin").status_code == 200  # still an admin
    assert html_after_self


def test_admin_status_redirect_cannot_leave_the_site(backend):
    app, _ = backend
    admin = make_admin(app)
    uid = app.state.ctx.store.profile_list(limit=10)[0]["id"]
    r = post(admin, f"/admin/users/{uid}/status", {"status": "suspended", "back": "https://evil.example/"})
    assert r.headers["location"] == "/admin/users"


# ------------------------------------------------------------------------------------------ security


def test_state_changing_posts_need_a_csrf_token(backend):
    app, _ = backend
    school = make_school(app)
    csrf(school)
    assert school.post("/issue", data=ISSUE, follow_redirects=False).status_code == 403
    assert school.post("/logout", data={}, follow_redirects=False).status_code == 403
    assert school.post("/issue", data={**ISSUE, "csrf_token": "wrong"}, follow_redirects=False).status_code == 403


def test_login_is_rate_limited(backend):
    app, _ = backend
    anon = TestClient(app)
    codes = [post(anon, "/login", {"email": "nobody@x.test", "password": "wrong-password"}).status_code for _ in range(12)]
    assert codes[0] == 401 and 429 in codes


def test_wrong_password_and_open_redirect(backend):
    app, _ = backend
    make_school(app)
    anon = TestClient(app)
    bad = post(anon, "/login", {"email": "registrar@greenfield.test", "password": "nope-nope-nope"})
    assert bad.status_code == 401 and "Email or password is incorrect." in bad.text
    ok = post(anon, "/login", {"email": "registrar@greenfield.test", "password": PASSWORD, "next": "https://evil.example"})
    assert ok.status_code == 303 and ok.headers["location"] == "/dashboard"


def test_signup_validation(backend):
    app, _ = backend
    anon = TestClient(app)
    assert signup(anon, "not-an-email").status_code == 400
    assert signup(anon, "ok@x.test", password="short").status_code == 400
    assert signup(anon, "ok@x.test", institution="  ").status_code == 400
    assert signup(anon, "ok@x.test").status_code == 303
    again = signup(TestClient(app), "ok@x.test")
    assert again.status_code == 400 and "already exists" in again.text


def test_issue_validation_and_html_escaping(backend):
    app, _ = backend
    admin, school = make_admin(app), make_school(app)
    approve(admin, "registrar@greenfield.test")
    assert post(school, "/issue", {**ISSUE, "grade": ""}).status_code == 400
    assert post(school, "/issue", {**ISSUE, "issued_on": "31 June"}).status_code == 400
    assert post(school, "/issue", {**ISSUE, "issued_on": "2099-01-01"}).status_code == 400
    rid, code = issue(school, student_name='<img src=x onerror=alert(1)>')
    assert "<img src=x" not in TestClient(app).get(f"/verify/{code}").text
    assert "<img src=x" not in school.get(f"/records/{rid}").text


def test_security_headers_present(backend):
    app, _ = backend
    r = TestClient(app).get("/")
    assert r.headers["x-frame-options"] == "DENY" and "script-src 'self'" in r.headers["content-security-policy"]


def test_session_survives_expired_access_token(backend):
    app, fake = backend
    admin = make_admin(app)
    (fake or app.state.ctx.auth).expire_access_tokens()
    assert admin.get("/admin").status_code == 200  # silently refreshed


def test_reserved_admin_email_cannot_be_claimed_through_signup(backend):
    app, _ = backend
    anon = TestClient(app)
    r = signup(anon, ADMIN)
    if app.state.ctx.auth.allow_admin_signup:  # local demo auth only
        assert r.status_code == 303
    else:
        assert r.status_code == 400 and "reserved" in r.text


def test_signups_can_be_closed(backend):
    app, _ = backend
    app.state.ctx.settings.allow_signup = False
    r = signup(TestClient(app), "late@x.test")
    assert r.status_code == 400 and "closed" in r.text


# ------------------------------------------------------------------------------------------ admin lists


def test_admin_lists_search_and_paginate(backend):
    app, _ = backend
    admin, school = make_admin(app), make_school(app)
    approve(admin, "registrar@greenfield.test")
    for i in range(17):
        issue(school, student_name=f"Student {i:02d}", course="Physics" if i % 2 else "Chemistry")
    assert "Page 1 of 2" in school.get("/dashboard").text
    assert "Page 2 of 2" in school.get("/dashboard?page=2").text
    assert "Student 03" in school.get("/dashboard?q=student+03").text
    assert "No records match" in school.get("/dashboard?q=zzzz").text
    html = admin.get("/admin/records?status=active&q=physics").text
    assert "Physics" in html and "Chemistry" not in html
    assert "Greenfield Secondary School" in admin.get("/admin/records").text


# ------------------------------------------------------------------------------------------ bulk issuing


def test_bulk_issue_flows(backend):
    app, _ = backend
    admin = make_admin(app)
    school_a = make_school(app, "schoola@test.org", "School Alpha")
    school_b = make_school(app, "schoolb@test.org", "School Beta")
    unapproved = make_school(app, "unapproved@test.org", "School Unapproved")

    approve(admin, "schoola@test.org")
    approve(admin, "schoolb@test.org")

    # Template download
    tpl = school_a.get("/issue/bulk/template")
    assert tpl.status_code == 200 and "student_name,course,grade,issued_on" in tpl.text

    # 1. Unapproved school refused
    assert unapproved.get("/issue/bulk").status_code == 403

    # 2. Oversized file rejected (> 200 KB)
    big_csv = "student_name,course,grade,issued_on\n" + ("John Doe,CS,A,2026-01-01\n" * 10000)
    token_a = csrf(school_a)
    res_big = school_a.post("/issue/bulk", data={"csrf_token": token_a}, files={"file": ("big.csv", big_csv, "text/csv")})
    assert res_big.status_code == 400 and "File too large" in res_big.text

    # 3. Batch with one bad row issues NOTHING
    bad_csv = (
        "student_name,course,grade,issued_on\n"
        "Alice Smith,Mathematics,A,2026-05-10\n"
        "Bob Johnson,Physics,,2026-05-10\n"  # missing grade
    )
    token_a = csrf(school_a)
    res_bad = school_a.post("/issue/bulk", data={"csrf_token": token_a}, files={"file": ("bad.csv", bad_csv, "text/csv")})
    assert res_bad.status_code == 400
    assert "Row 2" in res_bad.text and "Grade or result is required." in res_bad.text
    # Check that Alice Smith was NOT issued
    assert "Alice Smith" not in school_a.get("/dashboard").text

    # 4. Successful batch issue
    good_csv = (
        "\ufeffstudent_name,course,grade,issued_on\n"  # test UTF-8 BOM
        "Alice Smith,Mathematics,A,2026-05-10\n"
        "Charlie Brown,History,B,2026-05-12\n"
    )
    token_a = csrf(school_a)
    res_good = school_a.post("/issue/bulk", data={"csrf_token": token_a}, files={"file": ("good.csv", good_csv, "text/csv")})
    assert res_good.status_code == 200
    assert "Bulk issue complete" in res_good.text
    assert "Alice Smith" in res_good.text and "Charlie Brown" in res_good.text

    # Audit log check
    audit = admin.get("/admin/audit").text
    assert "record.bulk_issue" in audit

    # 5. Verify record from batch
    dash = school_a.get("/dashboard").text
    code_match = CODE_RE.search(dash)
    assert code_match is not None
    code = code_match.group(0)
    public = TestClient(app)
    v = public.get(f"/verify/{code}")
    assert v.status_code == 200 and "This record is unaltered." in v.text

    # 6. School isolation: School B cannot see School A's bulk issue results/records
    assert "Alice Smith" not in school_b.get("/dashboard").text
