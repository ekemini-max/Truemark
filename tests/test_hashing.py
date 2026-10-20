import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.hashing import canonical_json, compute_hash, issuer_ref, normalize

BASE = {
    "record_code": "TM-2026-AAAA-BBBB",
    "institution": "Greenfield Secondary School",
    "student_name": "Amara Okafor",
    "course": "Mechanical Engineering",
    "grade": "A",
    "issued_on": "2026-06-15",
}


def test_hash_is_deterministic_and_order_independent():
    shuffled = dict(reversed(list(BASE.items())))
    assert compute_hash(BASE, "salt") == compute_hash(shuffled, "salt")
    assert compute_hash(BASE, "salt").startswith("0x") and len(compute_hash(BASE, "salt")) == 66


@pytest.mark.parametrize("field,value", [("grade", "B"), ("issued_on", "2026-06-20"), ("student_name", "Amara Okafo"), ("course", "Civil Engineering"), ("institution", "Other School"), ("record_code", "TM-2026-AAAA-BBBC")])
def test_any_change_changes_the_hash(field, value):
    assert compute_hash({**BASE, field: value}, "salt") != compute_hash(BASE, "salt")


def test_salt_changes_the_hash():
    assert compute_hash(BASE, "a") != compute_hash(BASE, "b")


def test_harmless_whitespace_and_unicode_form_do_not_change_hash():
    noisy = {**BASE, "student_name": "  Amara   Okafor ", "grade": "A "}
    assert compute_hash(noisy, "s") == compute_hash(BASE, "s")
    precomposed, combining = "Ol\u1ea1", "Ola\u0323"  # the same name typed two ways (a with dot below)
    assert precomposed != combining
    assert compute_hash({**BASE, "student_name": precomposed}, "s") == compute_hash({**BASE, "student_name": combining}, "s")
    assert normalize("e\u0301") == normalize("\u00e9")


def test_issuer_ref_is_pseudonymous():
    ref = issuer_ref("11111111-1111-1111-1111-111111111111")
    assert ref.startswith("0x") and len(ref) == 66 and "Greenfield" not in ref


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_demo_computes_same_hash_as_python():
    """app/static/js/demo.js must produce the same fingerprint as the server."""
    demo = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "demo.js"
    script = f"""
      global.window = {{}}; global.document = {{ addEventListener() {{}}, querySelector() {{ return null; }} }};
      require({json.dumps(str(demo))});
      const rec = {json.dumps(BASE)};
      console.log(window.TrueMarkDemo.fingerprint(rec, "salt"));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == compute_hash(BASE, "salt")
    unicode_rec = {**BASE, "student_name": "Ọlaṣubomi Adéyemí"}
    script2 = script.replace(json.dumps(BASE), json.dumps(unicode_rec))
    out2 = subprocess.run(["node", "-e", script2], capture_output=True, text=True, timeout=30)
    assert out2.stdout.strip() == compute_hash(unicode_rec, "salt")
