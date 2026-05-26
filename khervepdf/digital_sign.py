"""Real PDF digital signing via pyHanko.

Unlike the Signature tool — which stamps a freehand ink scribble as
an image annotation — this writes a *cryptographic* PKCS#7 signature
into the PDF: the resulting file shows the green tick in any reader
that supports signature validation (Acrobat, Foxit, etc.).

Identity comes from a PKCS#12 (.p12 / .pfx) certificate the user
already has — that's the file your CA / authority issued you.

Falls back to a clear error when pyHanko isn't installed so the
import doesn't break the rest of the app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from pyhanko.pdf_utils.incremental_writer import (
        IncrementalPdfFileWriter,
    )
    from pyhanko.sign import signers
    from pyhanko.sign.fields import SigFieldSpec, append_signature_field
    from pyhanko.sign.signers import PdfSignatureMetadata, PdfSigner
    _OK = True
    _IMPORT_ERROR = ""
except Exception as e:  # ImportError or downstream issue
    _OK = False
    _IMPORT_ERROR = str(e)


def is_available() -> bool:
    return _OK


def import_error() -> str:
    return _IMPORT_ERROR


def sign_pdf(input_path: Path, output_path: Path,
             p12_path: Path, p12_password: str,
             field_name: str = "Signature1",
             reason: str = "",
             location: str = "",
             contact_info: str = "") -> tuple[bool, str]:
    """Apply a PKCS#7 detached signature using the certificate /
    private key bundle in `p12_path`. Writes the signed PDF to
    `output_path`. Returns (ok, message)."""
    if not _OK:
        return False, "pyHanko is not installed"
    if not Path(p12_path).exists():
        return False, f"Certificate not found: {p12_path}"
    try:
        signer = signers.SimpleSigner.load_pkcs12(
            pfx_file=str(p12_path),
            passphrase=p12_password.encode("utf-8")
            if p12_password else None,
        )
    except Exception as e:
        return False, f"Could not load certificate: {e}"
    try:
        with open(input_path, "rb") as inf:
            w = IncrementalPdfFileWriter(inf)
            # Append a sig field if the doc doesn't already have
            # one with this name. (sign_pdf will raise otherwise.)
            try:
                append_signature_field(
                    w, SigFieldSpec(sig_field_name=field_name),
                )
            except Exception:
                # Already exists or wasn't needed — ignore.
                pass
            meta = PdfSignatureMetadata(
                field_name=field_name,
                reason=reason or None,
                location=location or None,
                contact_info=contact_info or None,
            )
            pdf_signer = PdfSigner(meta, signer=signer)
            with open(output_path, "wb") as outf:
                pdf_signer.sign_pdf(w, output=outf)
        return True, "Signed"
    except Exception as e:
        return False, str(e)
