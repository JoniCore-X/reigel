"""Isolated PDF text extraction for /ia attachments.

Runs as its own process (``python -I reigel/pdf_worker.py <pages> <chars>``) so the
parent can kill it on a timeout: a hostile PDF can never hang or exhaust the web
worker. Reads the PDF bytes from stdin and writes one JSON object to stdout.
Only the standard library and pypdf are imported; nothing is rendered, executed
or written to disk. Encrypted files, JavaScript, embedded files, XFA forms and
launch actions are refused before any text is extracted.
"""
from __future__ import annotations

import io
import json
import sys

# Far below pypdf's defaults (75 MB): an upload is at most a few MB, so a stream
# that inflates past these limits is treated as hostile.
LIMITS = {
    "maximum_declared_stream_length": 16_000_000,
    "array_based_stream_maximum_output_length": 16_000_000,
    "zlib_maximum_output_length": 16_000_000,
    "zlib_maximum_recovery_input_length": 2_000_000,
    "lzw_maximum_output_length": 16_000_000,
    "run_length_maximum_output_length": 16_000_000,
    "jbig2_maximum_output_length": 1_000_000,
    "brotli_maximum_output_length": 16_000_000,
    "image_maximum_buffer_size": 16_000_000,
    "stream_decoding_work_maximum_length": 64_000_000,
    "stream_parsing_work_maximum_count": 1_000_000,
    "array_maximum_element_count": 50_000,
    "dictionary_maximum_element_count": 50_000,
    "page_tree_maximum_entries": 5_000,
    "page_tree_maximum_depth": 32,
    "outline_maximum_entries": 5_000,
    "form_fields_maximum_entries": 5_000,
    "named_destinations_maximum_entries": 5_000,
    "xform_maximum_invocations_per_extraction": 200,
    "xfa_decoding_work_maximum_length": 1_000_000,
    "jbig2dec_binary": None,  # Never call an external decoder.
}
ACTIVE_NAMES = ("/JavaScript", "/EmbeddedFiles")
ACTIVE_ACTIONS = {"/JavaScript", "/Launch", "/ImportData", "/SubmitForm", "/Rendition"}


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=True))
    sys.stdout.flush()


def resolve(value):
    try:
        return value.get_object() if value is not None else None
    except Exception:
        return None


def has_active_action(action, depth=0):
    action = resolve(action)
    if depth > 8 or not hasattr(action, "get"):
        return False
    if action.get("/S") in ACTIVE_ACTIONS or "/JS" in action:
        return True
    following = resolve(action.get("/Next"))
    items = following if isinstance(following, list) else [following] if following is not None else []
    return any(has_active_action(item, depth + 1) for item in items)


def refuse_active_content(reader):
    """Return a refusal code for scripts, embedded files, XFA or launch actions."""
    root = resolve(reader.trailer.get("/Root"))
    if not hasattr(root, "get"):
        return "unreadable"
    names = resolve(root.get("/Names"))
    if hasattr(names, "get") and any(key in names for key in ACTIVE_NAMES):
        return "active"
    if has_active_action(root.get("/OpenAction")) or "/AA" in root:
        return "active"
    form = resolve(root.get("/AcroForm"))
    if hasattr(form, "get") and "/XFA" in form:
        return "active"
    for page in reader.pages:
        if "/AA" in page:
            return "active"
        annotations = resolve(page.get("/Annots")) or []
        if not isinstance(annotations, list):
            continue
        for item in annotations[:500]:
            annotation = resolve(item)
            if not hasattr(annotation, "get"):
                continue
            if annotation.get("/Subtype") in {"/FileAttachment", "/Movie", "/Sound", "/RichMedia", "/Screen"}:
                return "active"
            if has_active_action(annotation.get("/A")) or "/AA" in annotation:
                return "active"
    return None


def extract(data, max_pages, max_chars):
    import pypdf
    from pypdf.errors import FileNotDecryptedError, LimitReachedError, PyPdfError

    with pypdf.apply_configuration(**LIMITS):
        try:
            reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                return {"ok": False, "code": "encrypted"}
            pages = len(reader.pages)
            if pages < 1:
                return {"ok": False, "code": "unreadable"}
            if pages > max_pages:
                return {"ok": False, "code": "pages", "pages": pages}
            refusal = refuse_active_content(reader)
            if refusal:
                return {"ok": False, "code": refusal}
            parts, total, truncated = [], 0, False
            for page in reader.pages:
                value = page.extract_text() or ""
                parts.append(value)
                total += len(value) + 2
                if total > max_chars:
                    truncated = True
                    break
            text = "\n\n".join(parts)
            if len(text) > max_chars:
                text, truncated = text[:max_chars], True
            return {"ok": True, "pages": pages, "text": text, "truncated": truncated}
        except FileNotDecryptedError:
            return {"ok": False, "code": "encrypted"}
        except LimitReachedError:
            return {"ok": False, "code": "limits"}
        except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError,
                OverflowError, MemoryError, UnicodeError, AssertionError):
            return {"ok": False, "code": "unreadable"}


def main(argv):
    try:
        max_pages, max_chars = int(argv[1]), int(argv[2])
    except (IndexError, ValueError):
        emit({"ok": False, "code": "unreadable"})
        return 2
    sys.setrecursionlimit(2000)
    data = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        emit({"ok": False, "code": "size"})
        return 0
    emit(extract(data, max_pages, max_chars))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
