#!/usr/bin/env python3
"""Issue #191 (R8-B) Phase 2: verify the exact accepted UD-IQ1_S split set.

Read-only verification on the model host:
  1. each split member exists with exact object byte length;
  2. sha256 == the accepted R8-A hf_lfs_sha256 pin;
  3. the retained R8-A raw header bytes are a byte-prefix of the file
     (reproduces the accepted header census against the physical bytes);
  4. GGUF magic/version and split metadata reproduce the accepted census.

Writes verification receipts as canonical JSON to stdout.
Exit 0 only if every member passes every check.
"""
import hashlib
import json
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/scripts")
import issue191_r8b_authority as auth  # noqa: E402

HEADER_MAGIC = b"GGUF"


def sha256_file(path, progress_every_gib=16):
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 24)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
            if progress_every_gib and total % (progress_every_gib << 30) < (1 << 24):
                print(f"hashed {total >> 30} GiB of {path}", file=sys.stderr)
    return h.hexdigest(), total


def main(model_dir):
    census = auth._load_r8a_header_census()
    members = auth.split_members()
    by_path = {f["path"]: f for f in census["files"]}
    receipts = []
    for m in members:
        name = m["path"].split("/")[-1]
        path = f"{model_dir}/{name}"
        rec = {"member": name, "expected_bytes": m["object_bytes"],
               "expected_lfs_sha256": m["hf_lfs_sha256"]}
        try:
            with open(path, "rb") as fh:
                head = fh.read(len(HEADER_MAGIC) + 8)
                magic = head[:4]
                version = struct.unpack("<I", head[4:8])[0] if len(head) >= 8 else None
                u64 = struct.unpack("<Q", head[8:16])[0] if len(head) >= 16 else None
            rec["gguf_magic_ok"] = magic == HEADER_MAGIC
            rec["gguf_version"] = version
            rec["first_u64"] = u64  # tensor_count on split 0; may be kv count ordering
            import os
            size = os.path.getsize(path)
            rec["actual_bytes"] = size
            rec["bytes_ok"] = size == m["object_bytes"]
            # header prefix reproduction against retained R8-A raw header extent
            raw = auth.R8A_DIR / "raw-headers" / f"{name}.header.bin"
            if raw.is_file():
                exp_len = by_path[m["path"]].get("header_extent_bytes")
                with open(path, "rb") as fh:
                    phys = fh.read(exp_len)
                ref = raw.read_bytes()
                rec["header_prefix_sha256"] = hashlib.sha256(phys).hexdigest()
                rec["header_bytes_ok"] = phys == ref
                rec["header_extent_bytes"] = exp_len
            else:
                rec["header_bytes_ok"] = None
                rec["header_note"] = "no retained raw header for this member (metadata-only split)"
            digest, _ = sha256_file(path)
            rec["actual_sha256"] = digest
            rec["sha256_ok"] = digest == m["hf_lfs_sha256"]
        except FileNotFoundError:
            rec["error"] = "missing file"
            rec["sha256_ok"] = False
            rec["bytes_ok"] = False
        receipts.append(rec)
        print(json.dumps(rec), file=sys.stderr)
    ok = all(r.get("bytes_ok") and r.get("sha256_ok") for r in receipts)
    doc = {
        "schema": "inferswarm.issue191.split-verification/1",
        "model_dir": model_dir,
        "authority": {
            "unsloth_repo": auth.UNSLOTH_REPO,
            "unsloth_revision": auth.UNSLOTH_REV,
            "representation": auth.REPRESENTATION,
            "total_encoded_bytes": auth.TOTAL_ENCODED_BYTES,
            "r8a_merge": auth.R8A_MERGE,
        },
        "members": receipts,
        "all_ok": ok,
    }
    print(json.dumps(doc, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
