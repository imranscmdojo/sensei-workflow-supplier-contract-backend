import io
import os
import time
import json
import re
import base64
import json5
import secrets
import smtplib
import html as _html
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime
from fastapi import BackgroundTasks, FastAPI, Form, UploadFile, File, Header, HTTPException, Depends, Body
from typing import Optional, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import firebase_admin
from firebase_admin import auth, credentials
from dotenv import load_dotenv

# Load .env for local development
load_dotenv()

# =========================
# SECRET MANAGER
# =========================

def get_secret(secret_id: str, project_id: str) -> str:
    """Get secret from Google Secret Manager

    The google.cloud.secretmanager import is lazy AND retried: a sibling venv's
    google namespace package occasionally wins the in-process namespace race
    (resolving to a google/cloud without secretmanager). Popping the namespace
    and retrying re-resolves against this venv's site-packages.
    """
    import sys as _sys
    for _attempt in range(4):
        try:
            from google.cloud import secretmanager
            break
        except ImportError:
            _sys.modules.pop("google.cloud", None)
            _sys.modules.pop("google", None)
            import time as _time
            _time.sleep(0.25 * (_attempt + 1))
    else:
        from google.cloud import secretmanager
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception:
        return ""

# Import agents
from agents.supplier_contract_review import SupplierContractReviewAgent

# =========================
# CONFIG
# =========================

PROJECT_ID = os.environ.get("PROJECT_ID", "test-rag-corpus-project")
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "sensei-ask-project")
LOCATION = os.environ.get("LOCATION", "us-west1")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://www.scmsensei.ai")
RAG_CORPUS = os.environ.get(
    "RAG_CORPUS",
    "projects/test-rag-corpus-project/locations/us-west1/ragCorpora/137359788634800128"
)

# SMTP (same vars as the Next.js app's notification mailer)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "muhammad@scmdojo.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)


SENSEI_LOGO_B64 = (
    "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"
)

def send_feedback_email(
    to_email: str,
    review_title: str,
    reviewer_email: str,
    clause_name: str,
    comment: str,
    review_url: str,
) -> None:
    """Email the review owner when external feedback arrives. Failures are logged, never thrown."""
    if os.environ.get("SMTP_DISABLED", "").lower() in ("1", "true", "yes"):
        print("[feedback-email] SMTP_DISABLED — skipping owner notification.")
        return
    if not to_email:
        print("[feedback-email] No owner email on review — cannot notify.")
        return
    if not SMTP_PASS:
        print("[feedback-email] SMTP_PASS not configured — skipping owner notification.")
        return

    clause = f"<b>{_html.escape(clause_name)}</b>" if clause_name else "<i>(general review feedback)</i>"
    body = comment.replace("\n", "<br/>")

    # CID reference — logo attached as an inline image below (Gmail/Outlook strip data: URIs)
    mark = """<img src="cid:sensei-logo" alt="Sensei" width="44" height="44" style="display:block;"/>"""

    html = f"""
    <div style="background:#f2f3fb;padding:32px 16px;font-family:Arial,Helvetica,sans-serif;">
      <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e7e9f2;">
        <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:20px 32px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
            <tr>
              <td style="vertical-align:middle;padding-right:14px;">{mark}</td>
              <td style="vertical-align:middle;">
                <div style="font-size:20px;font-weight:800;letter-spacing:0.04em;color:#ffffff;">SENSEI</div>
                <div style="font-size:12px;color:#d9def5;margin-top:4px;">Smart Procurement Intelligence</div>
              </td>
            </tr>
          </table>
        </div>
        <div style="padding:32px;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#7c3aed;">New contract review feedback</div>
          <div style="font-size:22px;font-weight:700;color:#1f2333;margin-top:10px;">External feedback received</div>
          <div style="font-size:15px;line-height:1.7;color:#3d4258;margin-top:16px;">
            On <b>{_html.escape(review_title)}</b> — {clause} from <b>{_html.escape(reviewer_email or "an external reviewer")}</b>.
          </div>
          <div style="margin-top:16px;background:#f6f7fc;border-left:4px solid #7c3aed;border-radius:8px;padding:16px 18px;font-size:14px;line-height:1.6;color:#1f2333;">{body}</div>
        </div>
        <div style="background:#f8f9fd;padding:18px 32px;border-top:1px solid #eef0f6;">
          <div style="font-size:12px;color:#8a8fa8;">&copy; {datetime.now().year} SCM Sensei AI</div>
        </div>
      </div>
    </div>
    """

    msg = MIMEMultipart("related")
    msg["Subject"] = f"New feedback on {review_title}"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(comment, "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)

    try:
        logo = MIMEImage(base64.b64decode(SENSEI_LOGO_B64), _subtype="png")
        logo.add_header("Content-ID", "<sensei-logo>")
        logo.add_header("Content-Disposition", "inline; filename=\"sensei-logo.png\"")
        msg.attach(logo)
    except Exception as exc:
        print(f"[feedback-email] Could not attach logo: {exc}")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            if SMTP_PORT == 587:
                server.starttls()
                server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        print(f"[feedback-email] Sent owner notification to {to_email}")
    except Exception as exc:  # noqa: BLE001
        print(f"[feedback-email] Failed to send owner notification: {exc}")


def notify_feedback_owner(
    to_email: str,
    review_title: str,
    reviewer_email: str,
    clause_name: str,
    comment: str,
    review_url: str,
) -> None:
    """Run as a FastAPI background task so feedback saves are never blocked by SMTP."""
    try:
        send_feedback_email(
            to_email=to_email,
            review_title=review_title,
            reviewer_email=reviewer_email,
            clause_name=clause_name,
            comment=comment,
            review_url=review_url,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[feedback-email] notify task raised: {exc}")


def send_feedback_decision_email(
    to_email: str,
    review_title: str,
    clause_name: str,
    decision: str,
    comment: str,
    applied: bool,
    review_url: str,
) -> None:
    """Email the external reviewer when the review owner accepts or declines
    their feedback. Failures are logged, never thrown."""
    if os.environ.get("SMTP_DISABLED", "").lower() in ("1", "true", "yes"):
        print("[feedback-decision-email] SMTP_DISABLED — skipping reviewer notification.")
        return
    if not to_email:
        print("[feedback-decision-email] No reviewer email on feedback — cannot notify.")
        return
    if not SMTP_PASS:
        print("[feedback-decision-email] SMTP_PASS not configured — skipping reviewer notification.")
        return

    accepted = decision == "accepted"
    label = "Accepted" if accepted else "Declined"
    accent = "#059669" if accepted else "#DC2626"
    if accepted:
        verdict_line = (
            "accepted your feedback and <b>applied the change</b> to the contract."
            if applied
            else "accepted your feedback."
        )
    else:
        verdict_line = "declined to apply this feedback to the contract for now."

    clause = f"<b>{_html.escape(clause_name)}</b>" if clause_name else "<i>(general review feedback)</i>"
    body = comment.replace("\n", "<br/>") if comment else ""
    mark = """<img src="cid:sensei-logo" alt="Sensei" width="44" height="44" style="display:block;"/>"""
    body_block = (
        f'<div style="margin-top:16px;background:#f6f7fc;border-left:4px solid {accent};border-radius:8px;padding:16px 18px;font-size:14px;line-height:1.6;color:#1f2333;">{body}</div>'
        if body
        else ""
    )

    html = f"""
    <div style="background:#f2f3fb;padding:32px 16px;font-family:Arial,Helvetica,sans-serif;">
      <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e7e9f2;">
        <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:20px 32px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
            <tr>
              <td style="vertical-align:middle;padding-right:14px;">{mark}</td>
              <td style="vertical-align:middle;">
                <div style="font-size:20px;font-weight:800;letter-spacing:0.04em;color:#ffffff;">SENSEI</div>
                <div style="font-size:12px;color:#d9def5;margin-top:4px;">Smart Procurement Intelligence</div>
              </td>
            </tr>
          </table>
        </div>
        <div style="padding:32px;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:{accent};">Feedback {label}</div>
          <div style="font-size:22px;font-weight:700;color:#1f2333;margin-top:10px;">Your feedback was {label}</div>
          <div style="font-size:15px;line-height:1.7;color:#3d4258;margin-top:16px;">
            The review owner for <b>{_html.escape(review_title)}</b> on {clause} {verdict_line}
          </div>
          {body_block}
        </div>
        <div style="background:#f8f9fd;padding:18px 32px;border-top:1px solid #eef0f6;">
          <a href="{_html.escape(review_url or APP_BASE_URL)}"
             style="display:inline-block;background:{accent};color:#ffffff;font-size:14px;font-weight:700;padding:12px 22px;border-radius:8px;text-decoration:none;margin-bottom:12px;">
            View the review
          </a>
          <div style="font-size:12px;color:#8a8fa8;">&copy; {datetime.now().year} SCM Sensei AI</div>
        </div>
      </div>
    </div>
    """

    msg = MIMEMultipart("related")
    msg["Subject"] = f"Your feedback on {review_title} was {label}"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(comment or "", "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)

    try:
        logo = MIMEImage(base64.b64decode(SENSEI_LOGO_B64), _subtype="png")
        logo.add_header("Content-ID", "<sensei-logo>")
        logo.add_header("Content-Disposition", "inline; filename=\"sensei-logo.png\"")
        msg.attach(logo)
    except Exception as exc:  # noqa: BLE001
        print(f"[feedback-decision-email] Could not attach logo: {exc}")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            if SMTP_PORT == 587:
                server.starttls()
                server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        print(f"[feedback-decision-email] Sent {decision} notification to {to_email}")
    except Exception as exc:  # noqa: BLE001
        print(f"[feedback-decision-email] Failed to send reviewer notification: {exc}")


def notify_feedback_decision(
    to_email: str,
    review_title: str,
    clause_name: str,
    decision: str,
    comment: str,
    applied: bool,
    review_url: str,
) -> None:
    """Background wrapper for notifying the external reviewer of accept/decline."""
    try:
        send_feedback_decision_email(
            to_email=to_email,
            review_title=review_title,
            clause_name=clause_name,
            decision=decision,
            comment=comment,
            applied=applied,
            review_url=review_url,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[feedback-decision-email] notify task raised: {exc}")

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://localhost:8089",
    "http://local.sensei.com:8080",
    "https://sensei-dev.scmdojo.com",
    "https://sensei.scmdojo.com",
    "https://www.scmdojo.com",
    'https://scmsensei.ai',
    'https://www.scmsensei.ai',
    'https://dev.scmsensei.ai'
]

# =========================
# APP
# =========================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Firebase Admin
if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {
        'projectId': FIREBASE_PROJECT_ID,
    })

# =========================
# HEALTH CHECK
# =========================

@app.get("/health")
async def health_check():
    """Health check endpoint for deployment verification"""
    return {
        "status": "healthy",
        "service": "supplier-contract-backend",
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "project_id": PROJECT_ID,
            "firebase_project_id": FIREBASE_PROJECT_ID,
            "location": LOCATION,
            "rag_corpus_configured": bool(RAG_CORPUS)
        }
    }

# =========================
# AUTH (available for future gated endpoints)
# =========================

async def verify_firebase_token(authorization: str = Header(None)):
    """Verify Firebase ID token from Authorization header"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.replace("Bearer ", "")
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


# =========================
# FILE EXTRACTION
# =========================

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".csv", ".md", ".xlsx"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB (scanned PDFs run large)


def _looks_like_zip(data: bytes) -> bool:
    """True when the buffer begins with a ZIP/PK header (a real .docx)."""
    return data[:2] == b"PK"


def _looks_like_ole_doc(data: bytes) -> bool:
    """True when the buffer begins with the OLE Compound Document header
    (legacy binary .doc produced by Word 97-2003)."""
    return data[:8] == bytes.fromhex("d0cf11e0a1b11ae1")


def _extract_legacy_doc_text(data: bytes) -> str:
    """Best-effort text extraction from a legacy binary Word (.doc) file.

    The Cloud Run image has no external converters (antiword/catdoc), so this
    pulls printable text runs out of the OLE blob: binary .doc stores body text
    as UTF-16-LE (or single-byte ANSI) runs. Works well for ordinary documents
    (including simple "test" files); returns "" if nothing plausible is found
    so the caller can ask the user to paste text instead.
    """
    def runs(utf16: bool) -> list:
        out = []
        cur = []
        step = 2 if utf16 else 1
        for i in range(0, len(data) - step + 1, step):
            if utf16:
                cp = data[i] | (data[i + 1] << 8)
            else:
                cp = data[i]
            ok = cp in (0x20, 0x09) or (0x21 <= cp <= 0x7E) or (0xA0 <= cp <= 0xFF)
            if ok:
                cur.append(chr(cp))
            else:
                if len(cur) >= 4:
                    out.append("".join(cur))
                cur = []
        if len(cur) >= 4:
            out.append("".join(cur))
        return out

    utf16 = runs(True)
    ansi = runs(False)

    def score(run_list: list) -> tuple:
        words = 0
        chars = 0
        for r in run_list:
            parts = r.split()
            if not parts:
                continue
            words += len(parts)
            chars += sum(len(p) for p in parts)
        return chars, words

    chosen = utf16 if score(utf16) >= score(ansi) else ansi
    lines = []
    for r in chosen:
        stripped = r.strip()
        if stripped and stripped.split():
            lines.append(stripped)
    text = "\n".join(lines)
    return re.sub(r"[ \t]+", " ", text)


def _repair_sys_path():
    """Re-add known site-packages dirs if sys.path got clobbered.

    Intermittently the project setup (two sibling venvs + Vertex AI's sys.path
    handling) can drop this venv's site-packages from sys.path at runtime,
    which would make lazy third-party imports like pypdfium2 or rapidocr fail
    with ModuleNotFoundError. This ensures the dev venv and the Cloud Run image
    site-packages are always importable. It is a cheap no-op otherwise.
    """
    import sys as _sys

    ver = "python%d.%d" % _sys.version_info[:2]
    candidates = []
    here = os.path.dirname(os.path.abspath(__file__))
    if here:
        candidates.append(os.path.join(here, ".venv", "lib", ver, "site-packages"))
    if _sys.prefix:
        candidates.append(os.path.join(_sys.prefix, "lib", ver, "site-packages"))
    exe_dir = os.path.dirname(os.path.dirname(_sys.executable)) if _sys.executable else ""
    if exe_dir and os.path.isdir(exe_dir):
        candidates.append(os.path.join(exe_dir, "lib", ver, "site-packages"))
    candidates.append("/usr/local/lib/%s/site-packages" % ver)
    for d in candidates:
        if d and os.path.isdir(d) and d not in _sys.path:
            _sys.path.insert(0, d)


_OCR_POOL = None
_OCR_POOL_LOCK = None
_VISION_RETRY_AT = 0.0


# =====================================================================
# Google Cloud Vision OCR (primary, cloud-based — fast for large scans)
# ---------------------------------------------------------------------
# Credentials setup (run once):
#   1. Create a service account in GCP -> IAM & Admin -> Service Accounts.
#   2. Grant it the "Cloud Vision API User" role and download its JSON key.
#   3. Tell google-cloud-vision where the key is, e.g.:
#        export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
#   On Cloud Run / GAE / GCE the credentials are picked up automatically from
#   the ambient metadata server, so no key file is needed in production.
# Vision must be enabled for the project:
#   gcloud services enable vision.googleapis.com
# The local RapidOCR pipeline below remains as an automatic fallback whenever
# Vision isn't reachable/configured, so nothing breaks for unauthenticated runs.
# =====================================================================

_VISION_FEATURE = None


def _vision_text_feature():
    from google.cloud import vision_v1 as vision

    global _VISION_FEATURE
    if _VISION_FEATURE is None:
        _VISION_FEATURE = vision.Feature(type_=vision.Feature.Type.TEXT_DETECTION)
    return _VISION_FEATURE


def _stage_pdf_to_gcs(data: bytes) -> str:
    """Upload a PDF to the configured OCR staging bucket; returns a gs:// URI.

    The async_batch_annotate_files endpoint requires the PDF to be reachable at
    a Google Cloud Storage URI (invoking content upload now returns
    "GcsSource is required"). Used only when VISION_GCS_BUCKET is set; returns
    "" otherwise so the caller falls back to per-page annotate_image.
    """
    bucket_name = os.environ.get("VISION_GCS_BUCKET", "").strip()
    if not bucket_name:
        return ""
    try:
        _repair_sys_path()
        from google.cloud import storage

        blob_name = f"contract_ocr/{secrets.token_hex(10)}.pdf"
        blob = storage.Client().bucket(bucket_name).blob(blob_name)
        blob.upload_from_string(data, content_type="application/pdf")
        return f"gs://{bucket_name}/{blob_name}"
    except Exception as exc:  # noqa: BLE001
        print(f"[vision] gcs staging failed ({exc})")
        return ""


def _ocr_pdf_text_vision(data: bytes, max_pages: int = 150) -> str:
    """OCR a scanned PDF with Google Cloud Vision (no local CPU cost).

    Pages are rendered at 150 DPI (fast, local) and OCRed by Google Cloud
    Vision; page requests run concurrently so response is near-instant and no
    CPU OCR inference ever happens. When VISION_GCS_BUCKET is configured the
    whole PDF is first staged to GCS and processed with a single
    `async_batch_annotate_files` job (Vision's PDF support requires a GCS
    source), which is the fastest path and needs no local rendering at all.

    Returns "" whenever Vision is unavailable or fails so the caller falls back
    to the local RapidOCR pipeline.
    """
    _repair_sys_path()

    import fitz
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from google.cloud import vision_v1 as vision

    pdf = fitz.open(stream=data, filetype="pdf")
    page_count = min(int(pdf.page_count), max_pages)
    if page_count <= 0:
        pdf.close()
        return ""

    try:
        vision_project = os.environ.get("VISION_PROJECT_ID") or PROJECT_ID
        client = vision.ImageAnnotatorClient(
            client_options={"quota_project_id": vision_project}
        )

        def page_png_bytes(page_idx: int) -> bytes:
            page = pdf.load_page(page_idx)
            return page.get_pixmap(dpi=150).tobytes("png")

        # 1) Whole-file async batch via GCS (fastest; no local rendering).
        gcs_uri = _stage_pdf_to_gcs(data)
        if gcs_uri:
            try:
                op = client.async_batch_annotate_files(
                    requests=[
                        vision.AsyncAnnotateFileRequest(
                            input_config=vision.InputConfig(
                                gcs_source=vision.GcsSource(uri=gcs_uri),
                                mime_type="application/pdf",
                            ),
                            features=[_vision_text_feature()],
                        )
                    ]
                )
                res = op.result(timeout=300)
                pages = []
                for page_resp in res.responses[0].responses:
                    if page_resp.error.message:
                        pages.append("")
                    else:
                        pages.append(page_resp.full_text_annotation.text or "")
                text = "\n\n".join(p for p in pages if p).strip()
                if text:
                    pdf.close()
                    _delete_gcs_blob(gcs_uri)
                    return text
            except Exception as exc:  # noqa: BLE001
                print(f"[vision] gcs async batch failed ({exc}); page-parallel fallback")
            _delete_gcs_blob(gcs_uri)

        # 2) Universal path: concurrent per-page annotate_image.
        feature = _vision_text_feature()

        def ocr_page(page_idx: int):
            image = vision.Image(content=page_png_bytes(page_idx))
            request = vision.AnnotateImageRequest(image=image, features=[feature])
            resp = client.annotate_image(request=request)
            if resp.error.message:
                return page_idx, ""
            return page_idx, resp.full_text_annotation.text or ""

        parts = {}
        n = max(4, min(16, page_count))
        with ThreadPoolExecutor(max_workers=n) as ex:
            for fut in as_completed([ex.submit(ocr_page, i) for i in range(page_count)]):
                idx, text = fut.result()
                parts[idx] = text

        text = "\n\n".join(parts.get(i, "") for i in range(page_count) if parts.get(i))
        pdf.close()
        return text
    except Exception as exc:  # noqa: BLE001
        print(f"[vision] OCR failed ({exc}); falling back to local RapidOCR")
        try:
            pdf.close()
        except Exception:  # noqa: BLE001
            pass
        return ""


def _delete_gcs_blob(gcs_uri: str):
    """Best-effort cleanup of a staged OCR file (no-op if removal fails)."""
    try:
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return
        _repair_sys_path()
        from google.cloud import storage

        parts = gcs_uri[5:].split("/", 1)
        bucket, blob_name = parts[0], parts[1]
        storage.Client().bucket(bucket).blob(blob_name).delete()
    except Exception as exc:  # noqa: BLE001
        print(f"[vision] gcs cleanup failed ({exc})")


def _get_ocr_pool(workers: int):
    """Return the lazily-created, reused ProcessPoolExecutor for OCR.

    A pool sized to the CPU count is created once and shared across requests.
    Using processes (not threads) avoids GIL contention on onnxruntime/OpenCV
    and on rapidocr's Python-level postprocessing, so pages on separate cores
    actually run in parallel. 'spawn' is used instead of fork to avoid
    deadlocking a forked child on pre-initialized OpenBLAS/OpenMP worker
    threads. Workers live in ocr_worker.py (not main.py) so each subprocess
    starts fast and never re-imports the FastAPI app.
    """
    import multiprocessing
    import threading
    from concurrent.futures import ProcessPoolExecutor

    from ocr_worker import _ocr_worker_init

    global _OCR_POOL, _OCR_POOL_LOCK
    if _OCR_POOL is None:
        if _OCR_POOL_LOCK is None:
            _OCR_POOL_LOCK = threading.Lock()
        with _OCR_POOL_LOCK:
            if _OCR_POOL is None:
                ctx = multiprocessing.get_context("spawn")
                _OCR_POOL = ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=ctx,
                    initializer=_ocr_worker_init,
                )
    return _OCR_POOL


def _ocr_pdf_text(data: bytes, max_pages: int = 150) -> str:
    """OCR an image-only (scanned) PDF into readable text.

    Primary path: Google Cloud Vision (whole-file batch for small PDFs,
    concurrent per-page annotate_image for larger ones). The local RapidOCR
    process-pool pipeline below is the automatic fallback so extraction always
    works even without Vision credentials/quota.
    """
    from concurrent.futures import as_completed

    _repair_sys_path()

    # Primary: Google Cloud Vision (fast, off-CPU). A process-level cooldown
    # (60s) skips repeated Vision attempts after a confirmed failure, so a
    # disabled/quota-less install doesn't pay the API timeout on every request,
    # yet a freshly-enabled API is picked up without a server restart.
    global _VISION_RETRY_AT
    vision_text = ""
    if time.monotonic() >= _VISION_RETRY_AT:
        vision_text = _ocr_pdf_text_vision(data, max_pages)
        if not vision_text:
            _VISION_RETRY_AT = time.monotonic() + 60
    if vision_text:
        return vision_text

    import pypdfium2 as pdfium
    from ocr_worker import _ocr_worker_page

    pdf = pdfium.PdfDocument(io.BytesIO(data))
    page_count = min(int(len(pdf)), max_pages)
    if page_count <= 0:
        return ""

    # Render pages to images first (single pass, cheap) so the heavier OCR can
    # run across parallel workers without pypdfium handle contention. 96 DPI
    # (well under the 150 DPI ceiling) + a 960px det cap is the measured sweet
    # spot: ~2x faster and slightly better text than 150 DPI full-res.
    scale = 96 / 72
    jobs = []
    for i in range(page_count):
        try:
            jobs.append((i, pdf[i].render(scale=scale).to_pil()))
        except Exception:  # noqa: BLE001 - skip a corrupt/unrenderable page
            jobs.append((i, None))

    parts: dict = {}
    n_workers = max(2, min(8, os.cpu_count() or 4))
    n_workers = min(n_workers, max(4, page_count))

    try:
        pool = _get_ocr_pool(n_workers)
        for fut in as_completed([pool.submit(_ocr_worker_page, j) for j in jobs]):
            idx, text = fut.result()
            parts[idx] = text
    except Exception as exc:  # noqa: BLE001 - fall back if pooling is unusable here
        print(f"[ocr] process pool unavailable ({exc}); falling back to threads")
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from rapidocr_onnxruntime import RapidOCR

        local = threading.local()

        def get_engine():
            engine = getattr(local, "engine", None)
            if engine is None:
                engine = RapidOCR(
                    max_side_len=960,
                    intra_op_num_threads=1,
                    print_verbose=False,
                )
                local.engine = engine
            return engine

        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            for fut in as_completed([ex.submit(_ocr_page_fallback, get_engine, j) for j in jobs]):
                idx, text = fut.result()
                parts[idx] = text

    return "\n\n".join(parts.get(i, "") for i in range(page_count) if parts.get(i))


def _ocr_page_fallback(get_engine, item):
    """Thread-based OCR fallback used only if ProcessPoolExecutor is unusable."""
    idx, img = item
    if img is None:
        return idx, ""
    try:
        result, _ = get_engine()(img)
        return idx, "\n".join(line[1] for line in result) if result else ""
    except Exception as exc:  # noqa: BLE001
        print(f"[ocr] page {idx} failed: {exc}")
        return idx, ""


def _extract_upload_text(file: UploadFile) -> str:
    """Extract readable text from an uploaded contract.

    Supported: PDF, DOCX, legacy DOC, TXT, CSV, MD, XLSX. Returns an empty
    string if the file has no extractable text (e.g. a scanned image-only PDF).
    """
    filename = (file.filename or "").lower()
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or 'unknown'}")

    data = file.file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    # Robustness: a ".doc" uploaded by Word is really OLE; a ".docx" is a zip;
    # a ".doc" that is actually a re-saved docx (or vice-versa) happens often.
    # Detect by content first so misnamed files still extract.
    effective_ext = ext
    if ext == ".doc" and _looks_like_zip(data):
        effective_ext = ".docx"
    elif ext == ".docx" and _looks_like_ole_doc(data):
        effective_ext = ".doc"

    try:
        if effective_ext in (".txt", ".csv", ".md"):
            return data.decode("utf-8", errors="ignore")
        if effective_ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            extracted = "\n".join((page.extract_text() or "") for page in reader.pages)
            # Image-only (scanned) PDFs expose little/no text layer (only stray
            # labels such as signature blocks), so OCR whenever the extracted
            # layer is empty or suspiciously thin per page.
            pages = len(reader.pages) or 1
            needs_ocr = len(extracted.strip()) < 40 or len(extracted.strip()) / pages < 50
            if needs_ocr:
                try:
                    ocr_text = _ocr_pdf_text(data)
                    if len(ocr_text.strip()) > len(extracted.strip()):
                        extracted = ocr_text
                except Exception as exc:  # noqa: BLE001 - OCR is best-effort
                    print(f"[extract] OCR fallback failed: {exc}")
            return extracted
        if effective_ext == ".doc":
            return _extract_legacy_doc_text(data)
        if effective_ext == ".docx":
            from docx import Document
            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs if p.text]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    parts.append(" | ".join(cells))
            return "\n".join(parts)
        if effective_ext == ".xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    vals = [str(v) for v in row if v is not None]
                    if vals:
                        parts.append(" | ".join(vals))
            return "\n".join(parts)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        raise HTTPException(status_code=400, detail=f"Could not read the uploaded file: {exc}")

    return ""


@app.post("/api/contracts/reviews/extract")
async def extract_contract_endpoint(
    file: UploadFile = File(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Extract readable text from an uploaded contract (PDF/DOCX/DOC/TXT/CSV/MD/XLSX).

    Pure extraction — no LLM, no RAG — so the frontend can always show the real
    source text before a review is generated.

    Returns:
        {"status": "success", "data": {"text": str, "name": str, "char_count": int,
                                       "extracted": bool}}
    """
    try:
        text = _extract_upload_text(file)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read the uploaded file: {exc}")

    return {
        "status": "success",
        "data": {
            "text": text,
            "name": file.filename or "",
            "char_count": len(text),
            "extracted": bool(text.strip()),
        },
    }


# =========================
# GENERATE REVIEW
# =========================

@app.post("/api/contracts/reviews/generate")
async def generate_review_endpoint(
    contract_text: str = Form(...),
    contract_type: str = Form(default="Supply Agreement"),
    user_side: str = Form(default="buyer"),
    focus_areas: str = Form(default=""),
    constraints: str = Form(default=""),
    must_not_lose: str = Form(default=""),
    client_id: str = Form(default=""),
    client_name: str = Form(default=""),
    deadline: str = Form(default=""),
    deal_context: str = Form(default=""),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Run a full clause-by-clause supplier contract review.

    Returns output matching output-schema.md under {"status", "data"}.
    """
    if not contract_text.strip():
        raise HTTPException(status_code=400, detail="contract_text is required")

    uid = decoded.get("uid") or ""
    if _is_free_user(uid) and _free_review_allowance_used(uid):
        raise HTTPException(
            status_code=403,
            detail=(
                "You've used your free contract review. "
                "Upgrade to Pro for unlimited reviews and Word exports."
            ),
        )

    agent = SupplierContractReviewAgent()
    try:
        result = await agent.generate_review(
            contract_text=contract_text,
            contract_type=contract_type,
            user_side=user_side,
            focus_areas=focus_areas,
            constraints=constraints,
            must_not_lose=must_not_lose,
            client_id=client_id,
            client_name=client_name,
            deadline=deadline,
            deal_context=deal_context,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Review generation failed: {exc}")

    # Server-authoritative allowance marker: the moment a review is successfully
    # generated for a free user, record it forever so deleting the review doc
    # later cannot unlock a second free contract.
    if _is_free_user(uid):
        _mark_free_review_used(uid)

    return {"status": "success", "data": result}


REDLINE_START_MARKER = "<<<REDLINE_START>>>"
REDLINE_END_MARKER = "<<<REDLINE_END>>>"


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extract_redlines(text: str):
    """Pull the trailing revision block out of a streamed follow-up answer."""
    match = re.search(
        re.escape(REDLINE_START_MARKER) + r"(.*?)" + re.escape(REDLINE_END_MARKER),
        text,
        flags=re.DOTALL,
    )
    if not match:
        return []
    try:
        obj = json.loads(match.group(1).strip())
    except Exception:  # noqa: BLE001
        try:
            obj = json5.loads(match.group(1).strip())
        except Exception:  # noqa: BLE001
            return []
    if isinstance(obj, dict):
        obj = [obj]
    result = []
    for item in obj:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "clause_id": str(item.get("clause_id") or ""),
                "proposed_language": str(item.get("proposed_language") or ""),
                "change_summary": str(item.get("change_summary") or ""),
            }
        )
    return [r for r in result if r["clause_id"] and r["proposed_language"]]


@app.post("/api/contracts/reviews/followup")
async def followup_review_endpoint(
    payload: Dict[str, Any] = Body(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Stream a follow-up answer about a completed review (SSE).

    Body:
        {"review": <output-schema JSON>, "question": "Can you soften the tone on the MOQ redline?"}

    Emits SSE events:
        data: {"type": "delta", "piece": "<streamed text>"}
        data: {"type": "done", "redlines": [...]}
        data: {"type": "error", "message": "..."}
    """
    review = payload.get("review")
    question = str(payload.get("question") or "").strip()
    if not isinstance(review, dict):
        raise HTTPException(status_code=400, detail="review object is required")
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    async def sse_gen():
        full = ""
        emitted = 0
        suppressed = False
        try:
            agent = SupplierContractReviewAgent()
            async for piece in agent.follow_up_stream(review, question):
                full += piece
                if suppressed:
                    continue
                idx = full.find(REDLINE_START_MARKER)
                if idx != -1:
                    safe = full[:idx]
                    if len(safe) > emitted:
                        yield _sse({"type": "delta", "piece": safe[emitted:]})
                        emitted = len(safe)
                    suppressed = True
                elif len(full) > emitted:
                    yield _sse({"type": "delta", "piece": full[emitted:]})
                    emitted = len(full)
            if not suppressed and len(full) > emitted:
                yield _sse({"type": "delta", "piece": full[emitted:]})
                emitted = len(full)
            yield _sse({"type": "done", "redlines": _extract_redlines(full)})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# =========================
# SHARE (PUBLIC READ-ONLY LINK)
# =========================

CONTRACT_REVIEWS_COLLECTION = "workflows/contract-review/projects"


def _fs_db():
    """Firestore client bound to the firebase-admin default app."""
    from firebase_admin import firestore as _fs
    return _fs.client()


def _project_ref(review_id: str):
    return _fs_db().collection(CONTRACT_REVIEWS_COLLECTION).document(review_id)


# =========================
# PLAN GATES (free vs pro)
# =========================

PRO_PLAN_NAMES = {"pro_monthly", "pro_annual", "enterprise"}
FREE_REVIEW_LIMIT = 1


def _user_plan(uid: str) -> str:
    """Best-effort read of the user's subscription plan from users/{uid}."""
    if not uid:
        return "free"
    try:
        snap = _fs_db().collection("users").document(uid).get()
        data = snap.to_dict() or {}
    except Exception:  # noqa: BLE001 - never break a request on plan lookup
        return "free"
    sub = data.get("subscription") or {}
    if not isinstance(sub, dict):
        return "free"
    plan = str(sub.get("plan") or "free").lower()
    tier = str(sub.get("tier") or "").lower()
    if tier in ("pro", "enterprise") or plan in PRO_PLAN_NAMES:
        return "pro"
    return "free"


def _is_free_user(uid: str) -> bool:
    return _user_plan(uid) == "free"


def _mark_free_review_used(uid: str) -> None:
    """Permanently flag a user as having consumed their free review allowance.

    Server-authoritative: written by the backend with the Admin SDK so it cannot
    be lost by a flaky client write, and it survives deleting the review doc.
    """
    if not uid:
        return
    try:
        _fs_db().collection("users").document(uid).set(
            {"freeContractUsed": True}, merge=True
        )
    except Exception:  # noqa: BLE001 - a marker write failure must not crash the request
        pass


def _free_review_allowance_used(uid: str) -> bool:
    """True when a free user has consumed their one-for-life review allowance.

    Checks the persistent users/{uid}.freeContractUsed flag FIRST so deleting a
    review (which drops the live doc count to zero) never restores the ability
    to generate a second contract review. Also backfills the flag whenever the
    live review count already shows the allowance is spent (covers reviews whose
    marker was never written because the flag feature post-dated them).
    """
    if not uid:
        return False
    try:
        snap = _fs_db().collection("users").document(uid).get()
        data = snap.to_dict() or {}
        if data.get("freeContractUsed"):
            return True
    except Exception:  # noqa: BLE001 - fall through to the live count
        pass
    if _count_user_reviews(uid) >= FREE_REVIEW_LIMIT:
        _mark_free_review_used(uid)
        return True
    return False


def _count_user_reviews(uid: str) -> int:
    """Count reviews owned by a user (used by the free-tier generation limit)."""
    try:
        snaps = (
            _fs_db().collection(CONTRACT_REVIEWS_COLLECTION)
            .where("created_by", "==", uid)
            .get()
        )
        return len(snaps)
    except Exception:  # noqa: BLE001 - a count failure should not crash the request
        return 0


SHARE_EXPIRY_DAYS = {1, 2, 3, 7}


def _share_password_hash(password: str) -> str:
    import hashlib
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _check_share_password(share: Dict[str, Any], password: str) -> bool:
    import hashlib
    expected = share.get("password_hash") or ""
    if not expected:
        return True
    candidate = hashlib.sha256((password or "").encode("utf-8")).hexdigest()
    return secrets.compare_digest(candidate, expected)


def _share_is_revoked(share: Dict[str, Any]) -> bool:
    return bool((share or {}).get("revoked"))


def _share_is_expired(share: Dict[str, Any]) -> bool:
    expires = (share or {}).get("expires_at") or ""
    if not expires:
        return False
    try:
        return datetime.utcnow().isoformat() > expires
    except Exception:  # noqa: BLE001
        return False


def _share_has_password(share: Dict[str, Any]) -> bool:
    return bool((share or {}).get("password_hash"))


def _share_allow_download(share: Dict[str, Any]) -> bool:
    return bool((share or {}).get("allow_download"))


@app.post("/api/contracts/reviews/share")
async def share_review_endpoint(
    payload: Dict[str, Any] = Body(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Create (or update) a share token for a review owned by the caller.

    Body:
        {"review_id": "...",
         "password": "optional",            # empty string clears it
         "expiry_days": 1 | 2 | 3 | 7 | 0,  # 0 / absent = never
         "allow_download": true,            # allow .docx download on shared page
         "revoked": true}                   # admin revoke toggle (invalidate)

    Returns the current share settings. Idempotent: existing tokens keep their
    original value and are never regenerated on settings saves.
    """
    review_id = str(payload.get("review_id") or "").strip()
    if not review_id:
        raise HTTPException(status_code=400, detail="review_id is required")

    doc = _project_ref(review_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Review not found")

    data = doc.to_dict() or {}
    if data.get("created_by") != decoded["uid"]:
        raise HTTPException(status_code=403, detail="You do not own this review")

    share = data.get("share")
    current = share if isinstance(share, dict) else {}
    if not isinstance(current, dict):
        current = {}

    now = datetime.utcnow().isoformat()

    # Default expiry: first-created only. Once the link exists with an expiry,
    # keep that deadline fixed unless expiry_days is explicitly passed on an
    # update (constants below handled in the secret).
    expiry_days = payload.get("expiry_days")
    password = payload.get("password")

    updated: Dict[str, Any] = {}
    if isinstance(current.get("token"), str) and current["token"]:
        updated["token"] = current["token"]
    else:
        updated["token"] = secrets.token_urlsafe(24)
        updated["created_at"] = now

    # Expiry — computed from the *original* creation time so repeated saves do
    # not keep pushing the deadline out.
    base_time = current.get("created_at") or now
    if expiry_days is not None:
        try:
            days = int(str(expiry_days).strip())
        except (TypeError, ValueError):
            days = 0
        if days > 0 and days not in SHARE_EXPIRY_DAYS:
            raise HTTPException(status_code=400, detail="expiry_days must be one of 1, 2, 3, 7, or 0 (never).")
        if days > 0:
            from datetime import timedelta
            expires = (datetime.fromisoformat(base_time) + timedelta(days=days)).isoformat()
            updated["expires_at"] = expires
        else:
            updated["expires_at"] = ""
    else:
        updated.setdefault("expires_at", current.get("expires_at") or "")

    # Password — store a hash only; empty string clears it.
    if password is not None:
        pw = str(password).strip()
        if pw:
            updated["password_hash"] = _share_password_hash(pw)
        else:
            updated["password_hash"] = ""

    if payload.get("allow_download") is not None:
        updated["allow_download"] = bool(payload.get("allow_download"))

    if payload.get("revoked") is not None:
        updated["revoked"] = bool(payload.get("revoked"))

    _project_ref(review_id).update({"share": updated})

    return {
        "token": updated["token"],
        "created_at": updated.get("created_at"),
        "expires_at": updated.get("expires_at") or "",
        "password_set": bool(updated.get("password_hash")),
        "allow_download": bool(updated.get("allow_download")),
        "revoked": bool(updated.get("revoked")),
    }


@app.post("/api/contracts/reviews/share/revoke")
async def share_revoke_endpoint(
    payload: Dict[str, Any] = Body(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Toggle revoke-access on a share the caller owns. Used by the admin toggle."""
    review_id = str(payload.get("review_id") or "").strip()
    if not review_id:
        raise HTTPException(status_code=400, detail="review_id is required")

    doc = _project_ref(review_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Review not found")

    data = doc.to_dict() or {}
    if data.get("created_by") != decoded["uid"]:
        raise HTTPException(status_code=403, detail="You do not own this review")

    share = data.get("share")
    current = share if isinstance(share, dict) else {}
    if not isinstance(current, dict):
        current = {}
    token = current.get("token")
    if not token:
        raise HTTPException(status_code=404, detail="No share link exists to revoke")

    revoked = bool(payload.get("revoked", not bool(current.get("revoked"))))
    updated = {**current, "revoked": revoked}
    _project_ref(review_id).update({"share": updated})

    return {
        "token": token,
        "revoked": revoked,
        "password_set": bool(updated.get("password_hash")),
        "allow_download": bool(updated.get("allow_download")),
        "expires_at": updated.get("expires_at") or "",
    }


@app.get("/api/contracts/reviews/shared/{token}")
async def shared_review_endpoint(token: str):
    """Public, read-only review resolved by its share token. No auth required.

    Password-protected links return `locked: true` without the review body;
    the caller must then POST /share-unlock with the password to receive it.
    """
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    docs = (
        _fs_db().collection(CONTRACT_REVIEWS_COLLECTION)
        .where("share.token", "==", token)
        .limit(1)
        .get()
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Shared review not found or link expired")

    data = docs[0].to_dict() or {}
    share = data.get("share") or {}
    if not isinstance(share, dict):
        share = {}

    if _share_is_revoked(share):
        raise HTTPException(status_code=410, detail="This shared review link has been revoked by its owner.")

    if _share_is_expired(share):
        raise HTTPException(status_code=410, detail="This shared review link has expired.")

    locked = _share_has_password(share)
    allowed = [
        "id", "document_name", "parties", "contract_type", "user_side",
        "deadline", "review_basis", "review_basis_note", "overall_risk",
        "key_findings", "clauses", "negotiation_strategy", "next_steps",
        "created_at", "updated_at", "source_name",
    ]
    base = {
        "locked": locked,
        "requires_password": locked,
        "allow_download": _share_allow_download(share),
        "shared_at": share.get("created_at"),
        "expires_at": share.get("expires_at") or "",
    }
    if locked:
        base["review"] = None
        return base
    base["review"] = {k: data.get(k) for k in allowed}
    return base


@app.post("/api/contracts/reviews/shared/{token}/unlock")
async def shared_review_unlock_endpoint(token: str, payload: Dict[str, Any] = Body(...)):
    """Validate the share password and return the review body for a locked link."""
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    docs = (
        _fs_db().collection(CONTRACT_REVIEWS_COLLECTION)
        .where("share.token", "==", token)
        .limit(1)
        .get()
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Shared review not found or link expired")

    data = docs[0].to_dict() or {}
    share = data.get("share") or {}
    if not isinstance(share, dict):
        share = {}

    if _share_is_revoked(share):
        raise HTTPException(status_code=410, detail="This shared review link has been revoked by its owner.")
    if _share_is_expired(share):
        raise HTTPException(status_code=410, detail="This shared review link has expired.")

    if not _share_has_password(share):
        allowed = [
            "id", "document_name", "parties", "contract_type", "user_side",
            "deadline", "review_basis", "review_basis_note", "overall_risk",
            "key_findings", "clauses", "negotiation_strategy", "next_steps",
            "created_at", "updated_at", "source_name",
        ]
        return {"locked": False, "review": {k: data.get(k) for k in allowed},
                "shared_at": share.get("created_at"), "allow_download": _share_allow_download(share)}

    password = str(payload.get("password") or "")
    if not _check_share_password(share, password):
        raise HTTPException(status_code=401, detail="Incorrect password for this shared review.")

    allowed = [
        "id", "document_name", "parties", "contract_type", "user_side",
        "deadline", "review_basis", "review_basis_note", "overall_risk",
        "key_findings", "clauses", "negotiation_strategy", "next_steps",
        "created_at", "updated_at", "source_name",
    ]
    return {
        "locked": False,
        "review": {k: data.get(k) for k in allowed},
        "shared_at": share.get("created_at"),
        "allow_download": _share_allow_download(share),
    }


@app.get("/api/contracts/reviews/shared/{token}/download-redlines")
async def shared_download_redlines_endpoint(token: str, password: str = ""):
    """Public .docx download for a share link with allow_download enabled.

    Honors password (?password=), expiry and revoke settings.
    """
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    docs = (
        _fs_db().collection(CONTRACT_REVIEWS_COLLECTION)
        .where("share.token", "==", token)
        .limit(1)
        .get()
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Shared review not found or link expired")

    data = docs[0].to_dict() or {}
    share = data.get("share") or {}
    if not isinstance(share, dict):
        share = {}

    if _share_is_revoked(share):
        raise HTTPException(status_code=410, detail="This shared review link has been revoked by its owner.")
    if _share_is_expired(share):
        raise HTTPException(status_code=410, detail="This shared review link has expired.")
    if not _share_allow_download(share):
        raise HTTPException(status_code=403, detail="Download is disabled for this shared review.")
    if _share_has_password(share) and not _check_share_password(share, password):
        raise HTTPException(status_code=401, detail="Incorrect password for this shared review.")

    # Build a full review record (without exposing it) so the redlined export
    # can reopen the original docx / source text.
    review = dict(data)
    if "chat" in review:
        review.pop("chat", None)
    try:
        docx_bytes = _build_redlined_contract_docx(review)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not build the document: {exc}")

    raw_name = f"{str(data.get('document_name') or 'contract-review')} - redlined contract.docx"
    safe_name = re.sub(r"[^\x00-\x7f]", "-", raw_name).replace('"', "").replace("\\", "").replace("/", "-").strip("- ") or "contract-review.docx"

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# =========================
# EXTERNAL FEEDBACK (SHARED-LINK REVIEWERS)
# =========================

CONTRACT_REVIEW_FEEDBACK_COLLECTION = "contract-review-feedback"


def _feedback_collection():
    return _fs_db().collection(CONTRACT_REVIEW_FEEDBACK_COLLECTION)


def _feedback_payload(doc) -> Dict[str, Any]:
    data = doc.to_dict() or {}
    return {
        "id": doc.id,
        "review_id": data.get("review_id"),
        "review_title": data.get("review_title"),
        "clause_id": data.get("clause_id"),
        "clause_name": data.get("clause_name"),
        "comment": data.get("comment"),
        "proposed_language": data.get("proposed_language"),
        "status": data.get("status") or "pending",
        "decided_by": data.get("decided_by"),
        "decided_at": data.get("decided_at"),
        "applied_at": data.get("applied_at"),
        "created_by": data.get("created_by"),
        "created_by_email": data.get("created_by_email"),
        "created_at": data.get("created_at"),
    }


@app.post("/api/contracts/reviews/shared/{token}/feedback")
async def submit_shared_feedback(
    token: str,
    payload: Dict[str, Any] = Body(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
    background: BackgroundTasks = BackgroundTasks(),
):
    """Leave per-section feedback on a shared review. Requires a signed-in user."""
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    docs = (
        _fs_db().collection(CONTRACT_REVIEWS_COLLECTION)
        .where("share.token", "==", token)
        .limit(1)
        .get()
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Shared review not found or link expired")

    review_doc = docs[0]
    review_data = review_doc.to_dict() or {}

    comment = str(payload.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="comment is required")

    clause_id = str(payload.get("clause_id") or "").strip() or None
    clause_name = str(payload.get("clause_name") or "").strip() or None
    proposed_language = str(payload.get("proposed_language") or "").strip() or None

    try:
        # CollectionReference.add() returns (update_time, document_ref)
        _, ref = _feedback_collection().add({
            "review_id": review_doc.id,
            "review_title": review_data.get("document_name") or "Untitled contract",
            "owner_uid": review_data.get("created_by") or "",
            "clause_id": clause_id,
            "clause_name": clause_name,
            "comment": comment,
            "proposed_language": proposed_language,
            "status": "pending",
            "created_by": decoded.get("uid") or "",
            "created_by_email": decoded.get("email") or "",
            "created_at": datetime.utcnow().isoformat(),
        })
        created = ref.get()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save feedback: {exc}")

    share = review_data.get("share") or {}
    share_token = share.get("token") if isinstance(share, dict) else None
    review_url = f"{APP_BASE_URL}/agentic-workflows/contract-reviews/shared/{share_token}" if share_token \
        else f"{APP_BASE_URL}/agentic-workflows/contract-reviews"
    owner_email = review_data.get("created_by_email") or ""
    background.add_task(
        notify_feedback_owner,
        to_email=owner_email,
        review_title=review_data.get("document_name") or "Untitled contract",
        reviewer_email=decoded.get("email") or "",
        clause_name=clause_name or "",
        comment=comment,
        review_url=review_url,
    )

    return {"feedback": _feedback_payload(created)}


@app.get("/api/contracts/reviews/shared/{token}/feedback")
async def shared_feedback_endpoint(
    token: str,
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Return the signed-in viewer's own feedback on the shared review."""
    token = token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    docs = (
        _fs_db().collection(CONTRACT_REVIEWS_COLLECTION)
        .where("share.token", "==", token)
        .limit(1)
        .get()
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Shared review not found or link expired")

    review_id = docs[0].id
    snap = _feedback_collection().where("review_id", "==", review_id).get()
    mine = [
        _feedback_payload(d)
        for d in snap
        if (d.to_dict() or {}).get("created_by") == decoded.get("uid")
    ]
    mine.sort(key=lambda f: (f.get("created_at") or ""), reverse=True)
    return {"feedback": mine}


@app.get("/api/contracts/reviews/feedback")
async def owner_feedback_endpoint(
    review_id: str = "",
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Return feedback received on the caller's reviews (optionally one review)."""
    query = _feedback_collection().where("owner_uid", "==", decoded.get("uid") or "")
    if review_id:
        query = query.where("review_id", "==", review_id)
    snap = query.get()
    entries = [_feedback_payload(d) for d in snap]
    entries.sort(key=lambda f: (f.get("created_at") or ""), reverse=True)
    return {"feedback": entries}


@app.delete("/api/contracts/reviews/feedback/{feedback_id}")
async def delete_feedback_endpoint(
    feedback_id: str,
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Author or review owner may delete a feedback entry."""
    ref = _feedback_collection().document(feedback_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Feedback not found")

    data = doc.to_dict() or {}
    is_author = data.get("created_by") == decoded.get("uid")
    is_owner = data.get("owner_uid") == decoded.get("uid")
    if not is_author and not is_owner:
        raise HTTPException(status_code=403, detail="You cannot delete this feedback")

    ref.delete()
    return {"ok": True}


@app.post("/api/contracts/reviews/feedback/{feedback_id}/decision")
async def decide_feedback_endpoint(
    feedback_id: str,
    payload: Dict[str, Any] = Body(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
    background: BackgroundTasks = BackgroundTasks(),
):
    """Owner decides on external feedback: accept/decline, optionally applying
    the reviewer's feedback to the clause as the new redline.

    Body: {"decision": "accepted"|"declined", "apply": bool}
    When apply=True the matched clause's redline.proposed_language is replaced
    with the reviewer's feedback comment, mirroring the AI "apply to clause".
    The external reviewer is emailed the outcome.
    """
    ref = _feedback_collection().document(feedback_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Feedback not found")

    data = doc.to_dict() or {}
    is_owner = data.get("owner_uid") == decoded.get("uid")
    if not is_owner:
        raise HTTPException(status_code=403, detail="Only the review owner can decide on this feedback")

    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in ("accepted", "declined"):
        raise HTTPException(status_code=400, detail="decision must be 'accepted' or 'declined'")

    apply_flag = bool(payload.get("apply")) and decision == "accepted"
    now = datetime.utcnow().isoformat()
    review_id = data.get("review_id") or ""

    applied_clause_id = None
    applied_language = None

    review_name = data.get("review_title") or "Untitled contract"
    review_url = f"{APP_BASE_URL}/agentic-workflows/contract-reviews"
    if review_id:
        review_url = f"{APP_BASE_URL}/agentic-workflows/contract-reviews/{review_id}"
        try:
            rev_ref = _project_ref(review_id)
            rev_doc = rev_ref.get()
            if rev_doc.exists:
                rev_data = rev_doc.to_dict() or {}
                share = rev_data.get("share") or {}
                if isinstance(share, dict) and share.get("token"):
                    review_url = f"{APP_BASE_URL}/agentic-workflows/contract-reviews/shared/{share['token']}"
        except Exception as exc:  # noqa: BLE001
            print(f"[feedback-decision] Could not build shared review URL: {exc}")

    # Optionally persist the accepted feedback as the clause's new redline.
    if apply_flag:
        proposed = str(data.get("proposed_language") or data.get("comment") or "").strip()
        clause_id = str(data.get("clause_id") or "").strip()
        if proposed and clause_id and review_id:
            try:
                rev_ref = _project_ref(review_id)
                rev_doc = rev_ref.get()
                if rev_doc.exists:
                    rev_data = rev_doc.to_dict() or {}
                    review_clauses = rev_data.get("clauses") or []
                    updated = []
                    for cl in review_clauses:
                        cl = dict(cl or {})
                        if str(cl.get("clause_id") or "") == clause_id:
                            redline = dict(cl.get("redline") or {})
                            redline["proposed_language"] = proposed
                            cl["redline"] = redline
                            applied_clause_id = clause_id
                            applied_language = proposed
                        updated.append(cl)
                    rev_ref.update({"clauses": updated, "updated_at": now})
            except Exception as exc:  # noqa: BLE001
                print(f"[feedback-decision] Could not apply feedback to clause: {exc}")

    update_fields = {
        "status": decision,
        "decided_by": decoded.get("uid") or "",
        "decided_at": now,
    }
    if applied_clause_id:
        update_fields["applied_at"] = now
    ref.update(update_fields)

    was_pending = (data.get("status") or "pending") == "pending"
    reviewer_email = data.get("created_by_email") or ""
    if was_pending and reviewer_email:
        background.add_task(
            notify_feedback_decision,
            to_email=reviewer_email,
            review_title=review_name,
            clause_name=data.get("clause_name") or "",
            decision=decision,
            comment=data.get("comment") or "",
            applied=bool(applied_clause_id),
            review_url=review_url,
        )

    return {
        "feedback": _feedback_payload(ref.get()),
        "applied_clause_id": applied_clause_id,
        "applied_language": applied_language,
        "review_url": review_url,
    }


# =========================
# EXPORT REDLINES (DOCX)
# =========================

def _build_redlines_docx(review: Dict[str, Any]) -> bytes:
    """Render the review JSON to a Word document of redline recommendations."""
    from docx import Document
    from docx.shared import Pt, RGBColor

    RED = RGBColor(0xDC, 0x26, 0x26)
    GREEN = RGBColor(0x05, 0x96, 0x69)
    GREY = RGBColor(0x64, 0x74, 0x8B)

    doc = Document()
    doc.add_heading("Redline Recommendations", level=0)

    meta = doc.add_paragraph()
    meta.add_run("Document: ").bold = True
    meta.add_run(str(review.get("document_name") or "Untitled contract"))
    meta = doc.add_paragraph()
    meta.add_run("Parties: ").bold = True
    meta.add_run(str(review.get("parties") or "—"))
    meta = doc.add_paragraph()
    meta.add_run("Contract type: ").bold = True
    meta.add_run(str(review.get("contract_type") or "—"))
    meta = doc.add_paragraph()
    meta.add_run("Your side: ").bold = True
    meta.add_run(str(review.get("user_side") or "—"))
    meta = doc.add_paragraph()
    meta.add_run("Overall risk: ").bold = True
    meta.add_run(str(review.get("overall_risk") or "—").upper())
    basis = doc.add_paragraph()
    basis.add_run("Review basis: ").bold = True
    basis.add_run(str(review.get("review_basis_note") or review.get("review_basis") or "—"))
    basis.runs[-1].font.color.rgb = GREY

    findings = review.get("key_findings") or []
    if findings:
        doc.add_heading("Key findings", level=1)
        for f in findings:
            p = doc.add_paragraph(style="List Bullet")
            sev = str(f.get("severity", "")).upper()
            run = p.add_run(f"[{sev}] ")
            run.bold = True
            if sev == "RED":
                run.font.color.rgb = RED
            elif sev == "YELLOW":
                run.font.color.rgb = RED
            elif sev == "GREEN":
                run.font.color.rgb = GREEN
            p.add_run(str(f.get("summary", "")))

    doc.add_heading("Clause-by-clause redlines", level=1)
    for clause in review.get("clauses") or []:
        redline = clause.get("redline") or {}
        proposed = str(redline.get("proposed_language") or "").strip()
        if not proposed:
            continue  # GREEN / acceptable clauses carry no redline

        sev = str(clause.get("severity", "")).upper()
        heading = doc.add_heading(
            f"{clause.get('clause_name') or clause.get('clause_id')} — {sev}", level=2
        )
        if sev == "RED":
            heading.runs[0].font.color.rgb = RED
        elif sev == "YELLOW":
            heading.runs[0].font.color.rgb = RED

        for label, key in (
            ("Contract says", "contract_says"),
            ("Standard position", "standard_position"),
            ("Business impact", "business_impact"),
        ):
            p = doc.add_paragraph()
            p.add_run(f"{label}: ").bold = True
            p.add_run(str(clause.get(key) or "—"))

        current = str(redline.get("current_language") or "").strip()
        if current:
            p = doc.add_paragraph()
            p.add_run("Current language: ").bold = True
            run = p.add_run(current)
            run.font.color.rgb = RED
            run.font.strike = True

        p = doc.add_paragraph()
        p.add_run("Proposed redline: ").bold = True
        run = p.add_run(proposed)
        run.font.color.rgb = GREEN

        if redline.get("rationale"):
            p = doc.add_paragraph()
            p.add_run("Rationale: ").bold = True
            p.add_run(str(redline["rationale"]))
        if redline.get("priority"):
            p = doc.add_paragraph()
            p.add_run("Priority: ").bold = True
            p.add_run(str(redline["priority"]))
        if redline.get("fallback"):
            p = doc.add_paragraph()
            p.add_run("Fallback: ").bold = True
            p.add_run(str(redline["fallback"]))

    strategy = review.get("negotiation_strategy") or {}
    items = strategy.get("items") if isinstance(strategy, dict) else None
    tiers = (
        ("Tier 1 — Must-haves", strategy.get("tier_1_must_haves")),
        ("Tier 2 — Should-haves", strategy.get("tier_2_should_haves")),
        ("Tier 3 — Nice-to-haves", strategy.get("tier_3_nice_to_haves")),
    )
    if items or any(values for _, values in tiers) or strategy.get("sequencing_note"):
        doc.add_heading("Negotiation strategy", level=1)
        if items:
            table = doc.add_table(rows=1, cols=4)
            try:
                table.style = "Light Grid Accent 1"
            except Exception:  # noqa: BLE001 - style set depends on installed template
                try:
                    table.style = "Table Grid"
                except Exception:  # noqa: BLE001
                    pass
            hdr = table.rows[0].cells
            for cell, label in zip(hdr, ("Priority", "Issue", "Goal", "Fallback")):
                cell.text = label
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
            priority_label = {
                "must-have": "MUST",
                "should-have": "SHOULD",
                "nice-to-have": "NICE",
            }
            for item in items:
                if not isinstance(item, dict):
                    continue
                cells = table.add_row().cells
                prio = str(item.get("priority") or "").lower()
                cells[0].text = priority_label.get(prio, prio.upper() or "—")
                cells[1].text = str(item.get("issue") or "—")
                cells[2].text = str(item.get("goal") or "—")
                cells[3].text = str(item.get("fallback") or "—")
        else:
            for title, values in tiers:
                if not values:
                    continue
                p = doc.add_paragraph()
                p.add_run(f"{title}:").bold = True
                for value in values:
                    doc.add_paragraph(str(value), style="List Bullet")
        if strategy.get("sequencing_note"):
            doc.add_paragraph(str(strategy["sequencing_note"]))

    steps = review.get("next_steps") or []
    if steps:
        doc.add_heading("Next steps", level=1)
        for step in steps:
            doc.add_paragraph(str(step), style="List Number")

    note = doc.add_paragraph()
    note_run = note.add_run(
        "This analysis is a risk review generated by sensei. and is not legal advice. "
        "It should be reviewed by qualified legal counsel before being relied upon."
    )
    note_run.italic = True
    note_run.font.size = Pt(9)
    note_run.font.color.rgb = GREY

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@app.post("/api/contracts/reviews/export/redlines")
async def export_redlines_endpoint(
    payload: Dict[str, Any] = Body(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Export a review's redline recommendations as a Word (.docx) file.

    Body:
        {"review": <output-schema JSON>, "filename": "optional-name.docx"}

    Returns the .docx binary as an attachment.
    """
    review = payload.get("review")
    if not isinstance(review, dict):
        raise HTTPException(status_code=400, detail="review object is required")

    uid = decoded.get("uid") or ""
    if _is_free_user(uid):
        raise HTTPException(
            status_code=403,
            detail="Word export is a Pro feature. Upgrade to Pro to download redlines.",
        )

    try:
        data = _build_redlines_docx(review)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not build the document: {exc}")

    raw_name = str(payload.get("filename") or "").strip()
    if not raw_name:
        base = str(review.get("document_name") or "contract-review").strip() or "contract-review"
        raw_name = f"{base} - redlines.docx"
    if not raw_name.lower().endswith(".docx"):
        raw_name += ".docx"
    safe_name = re.sub(r"[^\x00-\x7f]", "-", raw_name).replace('"', "").replace("\\", "").replace("/", "-").strip("- ") or "contract-review.docx"

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# =========================
# REDLINED CONTRACT EXPORT (NATIVE TRACKED CHANGES)
# =========================

def _w_qn(tag: str) -> str:
    """Word namespace-qualified tag name (e.g. 'w:r', 'w:delText')."""
    from docx.oxml.ns import qn
    return qn(tag)


def _cr_norm(text: str) -> str:
    """Collapse whitespace and lowercase — used to match redline language to a
    contract paragraph regardless of line breaks / casing in the source."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _append_tracked_delete(paragraph_xml, text: str, author: str, rev_date: str, rev_ids: list) -> None:
    """Append a Word tracked <w:del> block wrapping the deleted text run.

    Mirrors the <w:ins> structure exactly: the deleted text lives inside a
    <w:r> that is wrapped by <w:del>, so MS Word renders the ORIGINAL text as a
    struck-through deletion, immediately followed by the inserted proposal.
    """
    r = _docx_el("w:r")
    rPr = _docx_el("w:rPr")
    color = _docx_el("w:color")
    color.set(_w_qn("w:val"), "008000")
    rPr.append(color)
    r.append(rPr)
    del_text = _docx_el("w:delText")
    del_text.set(_w_qn("xml:space"), "preserve")
    del_text.text = text
    r.append(del_text)

    del_el = _docx_el("w:del")
    rev_id = len(rev_ids) + 1
    rev_ids.append(rev_id)
    del_el.set(_w_qn("w:id"), str(rev_id))
    del_el.set(_w_qn("w:author"), author)
    del_el.set(_w_qn("w:date"), rev_date)
    del_el.append(r)
    paragraph_xml.append(del_el)


def _append_tracked_insert(paragraph_xml, text: str, author: str, rev_date: str, rev_ids: list) -> None:
    """Append a Word tracked <w:ins> run (proposed language) to a paragraph."""
    ins_el = _docx_el("w:ins")
    rev_id = len(rev_ids) + 1
    rev_ids.append(rev_id)
    ins_el.set(_w_qn("w:id"), str(rev_id))
    ins_el.set(_w_qn("w:author"), author)
    ins_el.set(_w_qn("w:date"), rev_date)

    r = _docx_el("w:r")
    rPr = _docx_el("w:rPr")
    color = _docx_el("w:color")
    color.set(_w_qn("w:val"), "FF0000")
    rPr.append(color)
    r.append(rPr)
    t = _docx_el("w:t")
    t.set(_w_qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    ins_el.append(r)
    paragraph_xml.append(ins_el)


def _docx_el(tag: str):
    """Create an OOXML element under the w: namespace."""
    from docx.oxml import OxmlElement
    return OxmlElement(tag)


def _ensure_table_borders(table):
    """Guarantee single gray borders on a table, even if the document's style
    set lacks a named 'Table Grid' style (common in reopened user .docx files)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn as _qn
    tblPr = table._tbl.tblPr
    borders = tblPr.find(_qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tblPr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = borders.find(_qn(f"w:{edge}"))
        if e is None:
            e = OxmlElement(f"w:{edge}")
            borders.append(e)
        e.set(_qn("w:val"), "single")
        e.set(_qn("w:sz"), "4")
        e.set(_qn("w:space"), "0")
        e.set(_qn("w:color"), "A0A0A0")


def _set_cell_shading(cell, fill_hex):
    """Set a background fill on a table cell (used for header rows)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn as _qn
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(_qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcPr.append(shd)
    shd.set(_qn("w:val"), "clear")
    shd.set(_qn("w:color"), "auto")
    shd.set(_qn("w:fill"), fill_hex)


def _apply_redline_to_paragraph(paragraph, current_language: str, proposed_language: str, author: str, rev_date: str, rev_ids: list) -> bool:
    """Replace the matched current language inside a single paragraph with
    tracked change markup (delete original + insert proposed), preserving the
    paragraph's numbering/style and any text before/after the span."""
    full = " ".join((paragraph.text or "").split())
    norm_full = _cr_norm(full)
    norm_current = _cr_norm(current_language)
    if not norm_current or norm_current not in norm_full:
        return False

    start = norm_full.find(norm_current)
    end = start + len(norm_current)

    prefix_norm = norm_full[:start]
    matched_norm = norm_full[start:end]
    suffix_norm = norm_full[end:]

    # Drop the original runs but keep pPr (numbering, alignment, style).
    p = paragraph._p
    for child in list(p):
        if child.tag == _w_qn("w:r") or child.tag == _w_qn("w:hyperlink"):
            p.remove(child)

    if prefix_norm:
        r = _docx_el("w:r")
        t = _docx_el("w:t")
        t.set(_w_qn("xml:space"), "preserve")
        t.text = prefix_norm
        r.append(t)
        p.append(r)
    _append_tracked_delete(p, matched_norm, author, rev_date, rev_ids)
    _append_tracked_insert(p, proposed_language, author, rev_date, rev_ids)
    if suffix_norm:
        r = _docx_el("w:r")
        t = _docx_el("w:t")
        t.set(_w_qn("xml:space"), "preserve")
        t.text = suffix_norm
        r.append(t)
        p.append(r)
    return True


def _docx_add_heading(doc, text: str, level: int):
    """Add a heading tolerant of documents whose style set lacks Heading styles.

    Redlined-contract export reopens the *user's* original .docx, which may not
    define Word's built-in "Heading 1"/"Heading 2" styles, whereas a blank
    python-docx Document() always does. Falls back to a bold paragraph when the
    named style is missing so we never crash on otherwise-fine source files.
    """
    style_name = {0: "Title", 1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}.get(level, f"Heading {level}")
    try:
        if style_name in (s.name for s in doc.styles):
            return doc.add_heading(text, level=level)
    except Exception:
        pass
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    if level in (1, 2):
        run.italic = False
    return p


def _strip_number_prefix(text: str) -> str:
    """Remove a leading numbering marker (e.g. '4.', '1.2', 'Section 3:') before
    comparing a line against known clause names."""
    return re.sub(r"^\s*(?:[a-z]+\s+)?\d+(?:\.\d+)*[.)\]:—–-]*\s*", "", text.strip(), flags=re.I)


def _heading_level(text: str) -> int | None:
    """Best-effort detect of a heading line in reconstructed contract text.
    Returns the Word heading level (1 = major section, 2 = sub heading) or None
    when the line is ordinary body/list content."""
    t = text.strip()
    if not t:
        return None
    if len(t) > 60:
        return None
    if t[-1] in ".!?;":
        return None
    if re.match(r"^(?:article|section|clause|exhibit|appendix|annex|part|chapter)\s+\S", t, re.I):
        return 1
    if t.isupper() and any(ch.isalpha() for ch in t):
        return 1
    if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", t):
        return 2
    return None


def _is_list_marker_line(text: str) -> bool:
    """True when a line starts a numbered/bulleted point (e.g. '1.', '1.1.2',
    '(a)', 'a)', '•'). Such lines become their own paragraph in the rebuilt
    document instead of merging into the surrounding body text."""
    t = text.strip()
    if not t:
        return False
    if re.match(r"^\s*(?:[-•▪◦*]|\d+(?:\.\d+)*[.)]|\(\s*[a-zA-Z0-9]+\s*\)|[a-zA-Z]{1,3}[.)])(?:\s|$)", t):
        return True
    return False


def _add_rebuilt_contract_body(doc, source_text: str, clauses: list) -> None:
    """Reconstruct the contract document with real heading styles.

    Lines whose text matches a known clause name (ignoring numbering prefixes)
    become Heading 2 sections; obvious major headings (all-caps / 'Article'
    style) become Heading 1; numbered/bulleted points become their own
    paragraphs. The remaining non-blank, consecutive lines are grouped into
    ordinary paragraphs so tracked-change matching stays intact.
    """
    heads: dict = {}
    for cl in clauses or []:
        name = str(cl.get("clause_name") or "").strip()
        if name:
            heads[_cr_norm(name)] = name
            stripped = _strip_number_prefix(name)
            if stripped and _cr_norm(stripped) != _cr_norm(name):
                heads.setdefault(_cr_norm(stripped), stripped)

    buffer: list = []

    def flush() -> None:
        if buffer:
            doc.add_paragraph(" ".join(buffer))
            buffer.clear()

    for raw_line in (source_text or "").split("\n"):
        s = raw_line.strip()
        if not s:
            flush()
            continue

        stripped = _strip_number_prefix(s)
        if _cr_norm(stripped) in heads:
            flush()
            _docx_add_heading(doc, heads[_cr_norm(stripped)], level=2)
            continue

        lvl = _heading_level(s)
        if lvl is not None:
            flush()
            _docx_add_heading(doc, s, level=lvl)
            continue

        if _is_list_marker_line(s):
            flush()
            doc.add_paragraph(s)
            continue

        buffer.append(s)

    flush()


def _restyle_clause_headings(doc, clauses: list) -> None:
    """When exporting from the user's original .docx, promote paragraphs whose
    text is exactly a reviewed clause name to Heading 2, so the redline clauses
    read as proper section headings rather than flat body text."""
    heads: dict = {}
    for cl in clauses or []:
        name = str(cl.get("clause_name") or "").strip()
        if name:
            heads[_cr_norm(name)] = name
            stripped = _strip_number_prefix(name)
            if stripped and _cr_norm(stripped) != _cr_norm(name):
                heads.setdefault(_cr_norm(stripped), stripped)

    style_name = {0: "Title", 1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}.get(2, "Heading 2")
    has_style = False
    try:
        has_style = style_name in (s.name for s in doc.styles)
    except Exception:  # noqa: BLE001
        pass

    for paragraph in doc.paragraphs:
        stripped = _strip_number_prefix(paragraph.text or "")
        if _cr_norm(stripped) in heads:
            if has_style:
                try:
                    paragraph.style = doc.styles[style_name]
                except Exception:  # noqa: BLE001
                    pass
            for run in paragraph.runs:
                run.bold = True


def _build_redlined_contract_docx(review: Dict[str, Any]) -> bytes:
    """Render the redline review as a Word report that mirrors the in-browser
    review page, in supplier contract order:
      * header — "Contract Review Summary", document name, parties — side
      * summary card — review basis plus Parties / Contract type / Deadline /
        Overall risk (with RED item count)
      * key findings
      * clause-by-clause cards — contract says / standard position / business
        impact, proposed redline (current struck, proposed added), negotiate
        guidance (posture, priority, ask for, fallback, why)
      * negotiation strategy
      * next steps
    """
    from docx import Document
    from docx.shared import Pt, RGBColor

    RED = RGBColor(0xDC, 0x26, 0x26)
    AMBER = RGBColor(0xB4, 0x6A, 0x00)
    GREEN = RGBColor(0x05, 0x96, 0x69)
    GREY = RGBColor(0x64, 0x74, 0x8B)
    HEADER_FILL = "EEF1F6"

    doc = Document()

    def color_for(sev: str) -> RGBColor:
        s = str(sev or "").lower()
        if s == "red":
            return RED
        if s == "yellow":
            return AMBER
        return GREEN

    def kv(label: str, value: str, value_color=None) -> None:
        p = doc.add_paragraph()
        r = p.add_run(f"{label}: ")
        r.bold = True
        vr = p.add_run(str(value or "—"))
        if value_color is not None:
            vr.font.color.rgb = value_color
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.keep_with_next = True

    def has_redline(clause: dict) -> bool:
        return bool(str((clause.get("redline") or {}).get("proposed_language") or "").strip())

    def posture(clause: dict) -> str:
        if not has_redline(clause):
            return "Hold as-is — section already acceptable"
        prio = (clause.get("redline") or {}).get("priority")
        if clause.get("severity") == "red":
            return "Must-win — open the negotiation here" if prio == "must-have" else "High priority — firm floor, limited give"
        if clause.get("severity") == "yellow":
            return "Improve — trade rather than block"
        return "Hold as-is — keep favorable language"

    def neg_priority(clause: dict) -> str:
        prio = (clause.get("redline") or {}).get("priority")
        if prio == "must-have":
            return "Tier 1 — Must-have"
        if prio == "should-have":
            return "Tier 2 — Should-have"
        if prio == "nice-to-have":
            return "Tier 3 — Nice-to-have"
        return "Hold"

    def neg_fallback(clause: dict) -> str:
        redline = clause.get("redline") or {}
        if has_redline(clause) and redline.get("fallback"):
            return str(redline["fallback"])
        return "None specified — hold position" if has_redline(clause) else "—"

    # ---- Header block ----------------------------------------------------
    eyebrow = doc.add_paragraph()
    er = eyebrow.add_run("CONTRACT REVIEW SUMMARY")
    er.bold = True
    er.font.size = Pt(10)
    er.font.color.rgb = GREY
    eyebrow.paragraph_format.space_after = Pt(4)

    _docx_add_heading(doc, str(review.get("document_name") or "Untitled contract"), level=0)

    sub = doc.add_paragraph()
    side = "Supplier side" if str(review.get("user_side")).lower() == "supplier" else "Buyer side"
    sr = sub.add_run(f"{review.get('parties') or '—'} — {side}")
    sr.font.color.rgb = GREY
    sr.font.size = Pt(10.5)
    sub.paragraph_format.space_after = Pt(12)

    # ---- Summary card ----------------------------------------------------
    basis_tag = doc.add_table(rows=1, cols=1)
    try:
        basis_tag.style = "Table Grid"
    except Exception:  # noqa: BLE001 - style may be missing in some templates
        pass
    _ensure_table_borders(basis_tag)
    _set_cell_shading(basis_tag.rows[0].cells[0], HEADER_FILL)
    basis_p = basis_tag.rows[0].cells[0].paragraphs[0]
    br = basis_p.add_run("Review basis: ")
    br.bold = True
    basis_p.add_run(str(review.get("review_basis_note") or review.get("review_basis") or "Standard-market position"))
    basis_p.paragraph_format.space_after = Pt(2)

    counts = {"red": 0, "yellow": 0, "green": 0}
    for c in review.get("clauses") or []:
        key = str(c.get("severity") or "green").lower()
        counts[key] = counts.get(key, 0) + 1

    risk = str(review.get("overall_risk") or "—").lower()
    if risk == "high":
        risk_label, risk_color = "High", RED
    elif risk == "medium":
        risk_label, risk_color = "Medium", AMBER
    elif risk == "low":
        risk_label, risk_color = "Low", GREEN
    else:
        risk_label, risk_color = str(review.get("overall_risk") or "—"), GREY
    if counts.get("red", 0):
        risk_label += f" — {counts['red']} RED item" + ("s" if counts["red"] != 1 else "")

    grid_rows = [
        ("Parties", review.get("parties") or "—", None),
        ("Contract type", review.get("contract_type") or "—", None),
        ("Deadline", review.get("deadline") or "—", None),
        ("Overall risk", risk_label, risk_color),
    ]
    grid = doc.add_table(rows=len(grid_rows), cols=2)
    try:
        grid.style = "Table Grid"
    except Exception:  # noqa: BLE001
        pass
    _ensure_table_borders(grid)
    for i, (label, value, color) in enumerate(grid_rows):
        lcell = grid.rows[i].cells[0]
        _set_cell_shading(lcell, HEADER_FILL)
        lr = lcell.paragraphs[0].add_run(label)
        lr.bold = True
        vcell = grid.rows[i].cells[1]
        vrun = vcell.paragraphs[0].add_run(str(value))
        if color is not None:
            vrun.font.color.rgb = color

    # ---- Key findings ----------------------------------------------------
    findings = review.get("key_findings") or []
    if findings:
        _docx_add_heading(doc, "Key findings", level=1)
        for f in findings:
            sev = str(f.get("severity") or "green").upper()
            p = doc.add_paragraph(style="List Bullet")
            r = p.add_run(f"[{sev}] ")
            r.bold = True
            r.font.color.rgb = color_for(sev)
            p.add_run(str(f.get("summary", "")))

    # ---- Clause-by-clause -------------------------------------------------
    clauses = review.get("clauses") or []
    _docx_add_heading(doc, "Clause-by-clause", level=1)
    for clause in clauses:
        name = str(clause.get("clause_name") or clause.get("clause_id") or "—")
        sev = str(clause.get("severity") or "green").upper()

        head = doc.add_paragraph()
        hr = head.add_run(name)
        hr.bold = True
        hr.font.size = Pt(13)
        tag = head.add_run(f"  [{sev}]")
        tag.bold = True
        tag.font.size = Pt(10)
        tag.font.color.rgb = color_for(sev)
        head.paragraph_format.space_before = Pt(14)
        head.paragraph_format.space_after = Pt(4)
        head.paragraph_format.keep_with_next = True

        kv("Contract says", clause.get("contract_says"))
        kv("Standard position", clause.get("standard_position"))
        kv("Business impact", clause.get("business_impact"))

        redline = clause.get("redline") or {}
        if has_redline(clause):
            box_label = doc.add_paragraph()
            blr = box_label.add_run("PROPOSED REDLINE")
            blr.bold = True
            blr.font.size = Pt(9)
            blr.font.color.rgb = GREY
            box_label.paragraph_format.space_before = Pt(6)
            box_label.paragraph_format.space_after = Pt(2)
            box_label.paragraph_format.keep_with_next = True

            if str(redline.get("current_language") or "").strip():
                cur = doc.add_paragraph()
                cr_run = cur.add_run(f"“{redline.get('current_language')}”")
                cr_run.font.color.rgb = RED
                cr_run.font.strike = True
                cur.paragraph_format.space_after = Pt(2)
                cur.paragraph_format.keep_with_next = True

            prop = doc.add_paragraph()
            pr = prop.add_run(f"“{redline.get('proposed_language')}”")
            pr.font.color.rgb = GREEN
            pr.bold = True
            prop.paragraph_format.space_after = Pt(2)
            prop.paragraph_format.keep_with_next = True

            meta_parts = []
            if redline.get("priority"):
                meta_parts.append(f"Priority: {str(redline['priority']).replace('-', ' ').upper()}")
            if redline.get("fallback"):
                meta_parts.append(f"Fallback: {redline['fallback']}")
            if meta_parts:
                mp = doc.add_paragraph()
                mpr = mp.add_run("  •  ".join(meta_parts))
                mpr.font.size = Pt(9)
                mpr.font.color.rgb = GREY
                mp.paragraph_format.space_after = Pt(6)

        neg_label = doc.add_paragraph()
        nlr = neg_label.add_run("NEGOTIATE")
        nlr.bold = True
        nlr.font.size = Pt(9)
        nlr.font.color.rgb = GREY
        neg_label.paragraph_format.space_before = Pt(6)
        neg_label.paragraph_format.space_after = Pt(2)
        neg_label.paragraph_format.keep_with_next = True

        kv("Posture", posture(clause))
        kv("Negotiation priority", neg_priority(clause))
        ask = (str(redline.get("proposed_language") or "").strip()
               if has_redline(clause) else "No change requested — hold current language")
        kv("Ask for", ask)
        kv("Fallback", neg_fallback(clause))
        if has_redline(clause) and str(redline.get("rationale") or "").strip():
            kv("Why", redline["rationale"])

    # ---- Negotiation strategy --------------------------------------------
    strategy = review.get("negotiation_strategy") or {}
    items = strategy.get("items") if isinstance(strategy, dict) else None
    tiers = (
        ("Tier 1 — Must-haves", strategy.get("tier_1_must_haves")),
        ("Tier 2 — Should-haves", strategy.get("tier_2_should_haves")),
        ("Tier 3 — Nice-to-haves", strategy.get("tier_3_nice_to_haves")),
    )
    if items or any(values for _, values in tiers) or strategy.get("sequencing_note"):
        _docx_add_heading(doc, "Negotiation strategy", level=1)
        if items:
            table = doc.add_table(rows=1, cols=4)
            try:
                table.style = "Light Grid Accent 1"
            except Exception:  # noqa: BLE001
                try:
                    table.style = "Table Grid"
                except Exception:  # noqa: BLE001
                    pass
            hdr = table.rows[0].cells
            for cell, label in zip(hdr, ("Priority", "Issue", "Goal", "Fallback")):
                cell.text = label
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
                _set_cell_shading(cell, HEADER_FILL)
            priority_label = {
                "must-have": "MUST",
                "should-have": "SHOULD",
                "nice-to-have": "NICE",
            }
            for item in items:
                if not isinstance(item, dict):
                    continue
                cells = table.add_row().cells
                prio = str(item.get("priority") or "").lower()
                cells[0].text = priority_label.get(prio, prio.upper() or "—")
                cells[1].text = str(item.get("issue") or "—")
                cells[2].text = str(item.get("goal") or "—")
                cells[3].text = str(item.get("fallback") or "—")
        else:
            for title, values in tiers:
                if not values:
                    continue
                p = doc.add_paragraph()
                p.add_run(f"{title}:").bold = True
                for value in values:
                    doc.add_paragraph(str(value), style="List Bullet")
        if strategy.get("sequencing_note"):
            doc.add_paragraph(str(strategy["sequencing_note"]))

    # ---- Next steps -------------------------------------------------------
    steps = review.get("next_steps") or []
    if steps:
        _docx_add_heading(doc, "Next steps", level=1)
        for step in steps:
            doc.add_paragraph(str(step), style="List Number")

    # ---- Footer note ------------------------------------------------------
    note = doc.add_paragraph()
    note_run = note.add_run(
        "This analysis is a risk review generated by sensei. and is not legal advice. "
        "It should be reviewed by qualified legal counsel before being relied upon."
    )
    note_run.italic = True
    note_run.font.size = Pt(9)
    note_run.font.color.rgb = GREY

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@app.post("/api/contracts/reviews/export/redlined-contract")
async def export_redlined_contract_endpoint(
    payload: Dict[str, Any] = Body(...),
    decoded: Dict[str, Any] = Depends(verify_firebase_token),
):
    """Export the review as a Word report mirroring the in-browser redline
    page: header, summary card, key findings, clause-by-clause, negotiation
    strategy and next steps.

    Body:
        {"review": <review record incl. source_text / optional source_docx_b64>,
         "filename": "optional-name.docx"}

    Returns the .docx binary as an attachment. Pro feature.
    """
    review = payload.get("review")
    if not isinstance(review, dict):
        raise HTTPException(status_code=400, detail="review object is required")

    uid = decoded.get("uid") or ""
    if _is_free_user(uid):
        raise HTTPException(
            status_code=403,
            detail="Word export is a Pro feature. Upgrade to Pro to download redlines.",
        )

    try:
        data = _build_redlined_contract_docx(review)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not build the document: {exc}")

    raw_name = str(payload.get("filename") or "").strip()
    if not raw_name:
        base = str(review.get("document_name") or "contract-review").strip() or "contract-review"
        raw_name = f"{base} - redlined contract.docx"
    if not raw_name.lower().endswith(".docx"):
        raw_name += ".docx"
    safe_name = re.sub(r"[^\x00-\x7f]", "-", raw_name).replace('"', "").replace("\\", "").replace("/", "-").strip("- ") or "contract-review.docx"

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8089)))
