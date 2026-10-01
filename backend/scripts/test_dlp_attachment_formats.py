#!/usr/bin/env python3
"""Live DLP attachment-format harness (prod / prod-like).

Uploads fixture files that contain ONLY a custom-guidance codename in the file
body (message is clean), then:
  1. checks extraction_status / extracted_chars
  2. POST /api/dlp/scan with attachments → expects require_confirm|block
  3. (optional) negative control without the codename → allow

Usage (on prod, with .env.prod sourced, OR from laptop against prod):

  export BASE_URL=https://unichat.example.com
  export ADMIN_EMAIL=... ADMIN_PASSWORD=...
  python scripts/test_dlp_attachment_formats.py

  # or restore-safe against a named workspace:
  python scripts/test_dlp_attachment_formats.py --workspace-id <uuid>

Requires network + credentials. Does NOT hard-fail the process on a single
format miss — prints a table and exits 1 if any positive case failed.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

CODENAME = "AURORA-7-DLPTEST"
GUIDANCE = (
    f"Flag any mention of the internal codename {CODENAME} as restricted. "
    "Generic product talk without that codename is public."
)
CLEAN_MSG = "please summarize this file for me"


def _session(base: str, email: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"X-CSRF-Token": "1", "Accept": "application/json"})
    # Operator break-glass login (cookies + optional body tokens).
    r = s.post(
        f"{base}/api/auth/login",
        json={"email": email, "password": password},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"login {r.status_code}: {r.text[:300]}")
    return s


def _active_workspace(s: requests.Session, base: str) -> dict:
    """Pick a workspace and pin it as active (chat gate reads active_workspace_id)."""
    me = s.get(f"{base}/api/auth/me", timeout=30)
    me.raise_for_status()
    data = me.json()
    user = data.get("user") or data
    wid = user.get("active_workspace_id") or data.get("active_workspace_id")

    items: list = []
    for path in ("/api/workspaces/list", "/api/workspaces"):
        ws = s.get(f"{base}{path}", timeout=30)
        if ws.status_code == 200:
            body = ws.json()
            items = body if isinstance(body, list) else (
                body.get("workspaces") or body.get("items") or []
            )
            if items:
                break

    chosen = None
    if wid:
        for w in items:
            if str(w.get("id") or w.get("_id")) == str(wid):
                chosen = w
                break
        if chosen is None:
            chosen = {"_id": wid, "id": wid}
    if chosen is None:
        # Prefer personal (owned by operator) so we never mutate a real company.
        for w in items:
            if w.get("type") == "personal":
                chosen = w
                break
        if chosen is None and items:
            chosen = items[0]
    if chosen is None:
        raise RuntimeError("no workspace found for operator")

    cid = str(chosen.get("id") or chosen.get("_id"))
    # Pin active workspace so chat chokepoint DLP uses this policy.
    pin = s.put(
        f"{base}/api/users/active-workspace",
        json={"workspace_id": cid},
        timeout=30,
    )
    if pin.status_code >= 400:
        print(f"  warn: could not pin active workspace: {pin.status_code}")
    return chosen


def _get_policy(s: requests.Session, base: str, wid: str) -> dict:
    r = s.get(f"{base}/api/workspaces/{wid}/dlp/policy", timeout=30)
    r.raise_for_status()
    body = r.json()
    return body.get("policy") or body.get("dlp") or body


def _put_policy(s: requests.Session, base: str, wid: str, policy: dict) -> None:
    r = s.put(
        f"{base}/api/workspaces/{wid}/dlp/policy",
        json=policy,
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"PUT policy {r.status_code}: {r.text[:400]}")


def _build_fixtures(tmpdir: Path) -> list[tuple[str, Path, str]]:
    """Return list of (label, path, mime)."""
    out: list[tuple[str, Path, str]] = []

    p = tmpdir / "secret.txt"
    p.write_text(f"Quarterly notes.\nInternal ref: {CODENAME}\nEnd.\n", encoding="utf-8")
    out.append(("txt", p, "text/plain"))

    p = tmpdir / "secret.csv"
    p.write_text(f"name,code\nalice,{CODENAME}\nbob,public\n", encoding="utf-8")
    out.append(("csv", p, "text/csv"))

    try:
        import docx
        p = tmpdir / "secret.docx"
        d = docx.Document()
        d.add_paragraph("Executive summary")
        d.add_paragraph(f"Codename for ops freeze: {CODENAME}")
        d.save(str(p))
        out.append((
            "docx", p,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ))
    except Exception as exc:  # noqa: BLE001
        print(f"  skip docx fixture: {exc}")

    try:
        from openpyxl import Workbook
        p = tmpdir / "secret.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "item"
        ws["B1"] = "note"
        ws["A2"] = "1"
        ws["B2"] = CODENAME
        wb.save(str(p))
        out.append((
            "xlsx", p,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ))
    except Exception as exc:  # noqa: BLE001
        print(f"  skip xlsx fixture: {exc}")

    # Legacy .doc: write a plain-text payload with .doc extension so the soft
    # decode / ole recovery path can still surface the codename without needing
    # a full Word binary author. Real OLE .doc is covered by unit tests.
    p = tmpdir / "secret.doc"
    p.write_bytes(f"Legacy memo body includes {CODENAME} for audit.\n".encode("utf-8"))
    out.append(("doc", p, "application/msword"))

    # Negative control (txt)
    p = tmpdir / "clean.txt"
    p.write_text("Quarterly notes.\nNo internal codes.\nEnd.\n", encoding="utf-8")
    out.append(("txt-clean", p, "text/plain"))

    return out


def _upload(s: requests.Session, base: str, path: Path, mime: str) -> dict:
    with open(path, "rb") as fh:
        r = s.post(
            f"{base}/api/uploads/file",
            files={"file": (path.name, fh, mime)},
            timeout=120,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"upload {path.name} → {r.status_code}: {r.text[:300]}")
    body = r.json()
    return body.get("upload") or body


def _scan(
    s: requests.Session,
    base: str,
    *,
    wid: str,
    text: str,
    upload_id: str,
) -> dict:
    r = s.post(
        f"{base}/api/dlp/scan",
        json={
            "text": text,
            "workspace_id": wid,
            "source": "chat",
            "attachments": [{"upload_id": upload_id}],
            "lang": "en",
        },
        timeout=120,
    )
    if r.status_code >= 400:
        return {"_http": r.status_code, "_body": r.text[:500]}
    return r.json()


def _chat_send_gate(
    s: requests.Session,
    base: str,
    *,
    text: str,
    upload_id: str,
    name: str,
    mime: str,
) -> dict:
    """Hit the real chat chokepoint (message + attachment text) without streaming.

    Expects 402/403 on DLP/budget blocks, or 200 if allowed (we stub no real need
    for a completion — if DLP misses, OpenRouter may still be called; keep text
    short and prefer scanning first).
    """
    # Resolve a quick model config id from catalog if available.
    config_id = "quick:google/gemini-3.5-flash-lite"
    try:
        mr = s.get(f"{base}/api/models", timeout=30)
        if mr.status_code == 200:
            body = mr.json()
            # Any shape is fine — keep default quick id.
            _ = body
    except Exception:  # noqa: BLE001
        pass
    payload = {
        "message": text,
        "config_id": config_id,
        "attachments": [{
            "upload_id": upload_id,
            "name": name,
            "type": "document",
            "mime_type": mime,
            "is_pdf": False,
        }],
        "lang": "en",
    }
    r = s.post(f"{base}/api/chat/send", json=payload, timeout=180)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {"_raw": r.text[:400]}
    return {"_http": r.status_code, **(body if isinstance(body, dict) else {"body": body})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("BASE_URL", "https://unichat.example.com"))
    ap.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", ""))
    ap.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
    ap.add_argument("--workspace-id", default=os.environ.get("DLP_TEST_WORKSPACE_ID", ""))
    ap.add_argument("--skip-policy", action="store_true", help="do not mutate DLP policy")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    if not args.email or not args.password:
        print("ADMIN_EMAIL and ADMIN_PASSWORD required", file=sys.stderr)
        return 2

    print(f"== DLP attachment format test against {base}")
    s = _session(base, args.email, args.password)
    if args.workspace_id:
        wid = args.workspace_id
        print(f"workspace (forced): {wid}")
    else:
        ws = _active_workspace(s, base)
        wid = str(ws.get("_id") or ws.get("id"))
        print(f"workspace: {wid} ({ws.get('name')})")

    prev_policy = None
    if not args.skip_policy:
        prev_policy = _get_policy(s, base, wid)
        print("saving previous DLP policy; applying test guidance…")
        test_policy = {
            "enabled": True,
            "sensitivity": "balanced",
            "mode": "enforce",
            "llm_classifier": {
                "enabled": True,
                "guidance_prompt": GUIDANCE,
                "action_thresholds": {
                    "confidential": "require_confirm",
                    "restricted": "require_confirm",
                },
            },
        }
        # Merge onto previous so we don't wipe custom_patterns etc.
        merged = dict(prev_policy) if isinstance(prev_policy, dict) else {}
        merged.update({k: v for k, v in test_policy.items() if k != "llm_classifier"})
        lc = dict((prev_policy or {}).get("llm_classifier") or {})
        lc.update(test_policy["llm_classifier"])
        merged["llm_classifier"] = lc
        _put_policy(s, base, wid, merged)

    results: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory() as td:
            fixtures = _build_fixtures(Path(td))
            for label, path, mime in fixtures:
                row: dict[str, Any] = {"format": label, "file": path.name}
                try:
                    up = _upload(s, base, path, mime)
                    row["upload_id"] = up.get("id") or up.get("_id")
                    row["extraction_status"] = up.get("extraction_status")
                    row["extracted_chars"] = up.get("extracted_chars")
                    row["text_preview"] = (up.get("text_preview") or "")[:80]

                    scan = _scan(
                        s, base, wid=wid, text=CLEAN_MSG, upload_id=row["upload_id"],
                    )
                    if "_http" in scan:
                        row["scan_http"] = scan["_http"]
                        row["scan_body"] = scan["_body"]
                        row["scan_action"] = None
                        row["scan_matches"] = 0
                    else:
                        result = scan.get("result") or {}
                        action = result.get("highest_action") or "allow"
                        matches = result.get("matches") or []
                        row["scan_action"] = action
                        row["scan_matches"] = len(matches)
                        row["match_sources"] = sorted({
                            (m.get("source") or m.get("rule_id") or "?") for m in matches
                        })

                    # Real chokepoint (message + extracted attachment text).
                    gate = _chat_send_gate(
                        s, base,
                        text=CLEAN_MSG,
                        upload_id=row["upload_id"],
                        name=path.name,
                        mime=mime,
                    )
                    row["gate_http"] = gate.get("_http")
                    row["gate_code"] = gate.get("code") or gate.get("error")
                    is_clean = label.endswith("-clean")
                    gate_blocked = (
                        gate.get("_http") in (402, 403)
                        and str(gate.get("code") or "").startswith("dlp")
                    )
                    # Prefer gate as source of truth for file-body secrets;
                    # scan is also checked when the deployed backend joins attachments.
                    if is_clean:
                        row["pass"] = (not gate_blocked) and (
                            row.get("scan_action") in (None, "allow")
                            or row.get("scan_matches", 0) == 0
                            or row.get("scan_http")  # old backend may 400 empty path
                        )
                    else:
                        scan_hit = (
                            row.get("scan_action") in ("block", "require_confirm", "warn")
                            and (row.get("scan_matches") or 0) > 0
                        )
                        # PASS if gate DLP-blocks OR (deployed) scan hits.
                        # Gate is required for "real" protection; scan is UX.
                        row["pass"] = bool(gate_blocked or scan_hit)
                        row["highest_action"] = row.get("scan_action") or row.get("gate_code")
                        row["match_count"] = row.get("scan_matches")
                except Exception as exc:  # noqa: BLE001
                    row["error"] = str(exc)
                    row["pass"] = False
                results.append(row)
                status = "PASS" if row.get("pass") else "FAIL"
                print(
                    f"  [{status}] {label:10} extract={row.get('extraction_status')} "
                    f"chars={row.get('extracted_chars')} "
                    f"scan={row.get('scan_action')}/{row.get('scan_matches')} "
                    f"gate={row.get('gate_http')}:{row.get('gate_code')} "
                    f"{row.get('error') or ''}"
                )
    finally:
        if prev_policy is not None and not args.skip_policy:
            print("restoring previous DLP policy…")
            try:
                # Strip server-only fields that PUT may reject.
                restore = {
                    k: v for k, v in prev_policy.items()
                    if k in {
                        "enabled", "sensitivity", "mode", "rule_overrides",
                        "custom_patterns", "llm_classifier",
                    }
                }
                _put_policy(s, base, wid, restore)
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN: policy restore failed: {exc}", file=sys.stderr)

    print("\n== Summary")
    print(json.dumps(results, indent=2, default=str))
    failed = [r for r in results if not r.get("pass")]
    if failed:
        print(f"\n{len(failed)} failure(s)", file=sys.stderr)
        return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
