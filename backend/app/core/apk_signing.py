"""APK signer identity — SHA-256 of the signing certificate.

Reads the APK Signature Scheme v3/v2 block directly (pure Python, no
apksigner/JDK). Android only installs an update signed by the same
certificate as the installed app, so the release pipeline compares this
fingerprint across releases before a binary can reach devices. This is
an identity read, not signature verification — devices still verify.
"""

import hashlib
import struct

_MAGIC = b"APK Sig Block 42"
_V2_ID = 0x7109871A
_V3_ID = 0xF05368C0


def _lp(buf: bytes, off: int) -> tuple[bytes, int]:
    (n,) = struct.unpack_from("<I", buf, off)
    end = off + 4 + n
    if end > len(buf):
        raise ValueError("truncated length-prefixed field")
    return buf[off + 4:end], end


def _first_cert(scheme_value: bytes) -> bytes:
    signers, _ = _lp(scheme_value, 0)
    signer, _ = _lp(signers, 0)
    signed_data, _ = _lp(signer, 0)
    _digests, off = _lp(signed_data, 0)
    certificates, _ = _lp(signed_data, off)
    cert, _ = _lp(certificates, 0)
    return cert


def signer_sha256(apk: bytes) -> str | None:
    """Lower-case hex SHA-256 of the first signer certificate (v3, else
    v2). None when the APK carries no v2/v3 signing block or is malformed."""
    try:
        eocd = apk.rfind(b"PK\x05\x06")
        if eocd < 0:
            return None
        (cd_offset,) = struct.unpack_from("<I", apk, eocd + 16)
        if cd_offset < 24 or apk[cd_offset - 16:cd_offset] != _MAGIC:
            return None
        (block_size,) = struct.unpack_from("<Q", apk, cd_offset - 24)
        start = cd_offset - block_size - 8
        if start < 0:
            return None
        pairs = apk[start + 8:cd_offset - 24]
        found: dict[int, bytes] = {}
        off = 0
        while off + 12 <= len(pairs):
            (n,) = struct.unpack_from("<Q", pairs, off)
            (pid,) = struct.unpack_from("<I", pairs, off + 8)
            if pid in (_V2_ID, _V3_ID):
                found[pid] = pairs[off + 12:off + 8 + n]
            off += 8 + n
        value = found.get(_V3_ID) or found.get(_V2_ID)
        return hashlib.sha256(_first_cert(value)).hexdigest() if value else None
    except (struct.error, ValueError, IndexError):
        return None
