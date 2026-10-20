"""Sample data for local demos on memory storage (DEV_SEED=true). Never used with Supabase."""
from __future__ import annotations

from .deps import AppContext, ensure_profile

DEMO_PASSWORD = "truemark-demo-1"


def seed(c: AppContext) -> None:
    admin_email = next(iter(sorted(c.settings.admin_email_set)), "admin@truemark.test")
    c.settings.admin_emails = ",".join(sorted(c.settings.admin_email_set | {admin_email}))
    admin = c.auth.sign_up(admin_email, DEMO_PASSWORD, "Demo Admin", "TrueMark")
    ensure_profile(c, admin)

    school = c.auth.sign_up("registrar@greenfield.test", DEMO_PASSWORD, "Ngozi Eze", "Greenfield Secondary School")
    profile = ensure_profile(c, school)
    c.store.profile_update(profile["id"], {"status": "approved"})
    profile = c.store.profile_get(profile["id"])

    pending = c.auth.sign_up("office@harbourview.test", DEMO_PASSWORD, "Tunde Bello", "Harbourview College")
    ensure_profile(c, pending)

    samples = [
        ("Amara Okafor", "Mechanical Engineering", "A", "2026-06-15"),
        ("Ifeoma Nwosu", "Technical Drawing", "B+", "2026-06-15"),
        ("Emeka Udoh", "Mathematics", "A-", "2026-07-02"),
        ("Ọlaṣubomi Adéyemí", "Physics", "B", "2026-07-02"),
    ]
    for name, course, grade, issued in samples:
        c.service.issue(profile, {"student_name": name, "course": course, "grade": grade, "issued_on": issued})
    print(f"[dev seed] admin: {admin_email} / {DEMO_PASSWORD}   school: registrar@greenfield.test / {DEMO_PASSWORD}")
