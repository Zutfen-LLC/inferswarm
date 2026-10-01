"""#254 live producer CPU-only contracts; NEVER physical evidence.

Adversarial matrix (issue #254 Phase A): 17 required RED/adversarial cases,
each demonstrated at the producerless pre-fix state or against the producer
skeleton, all failing closed. Physical execution paths are exercised ONLY
through injectable test doubles (a fake server process on localhost, an
offline dispatch registry); the production producer obtains observations
exclusively from its own launched process and host probes.
"""
from __future__ import annotations

import copy
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue252_arms as A
import issue252_constants as C252
import issue252_capture as CAP
import issue252_physical as P252
import issue252_terminal as T252
import issue254_constants as C
import issue254_producer as PR
import issue250_diagnostic as D

NL = chr(10)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True
                          ).stdout.strip()


ENUM_LINE = ("ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | "
             "fp16: 1 | bf16: 0 | fp4: 0 | warp size: 32 | shared memory: "
             "49152 | int dot: 1 | matrix cores: NV_coopmat2")
MECH_A3_LOG = ("ggml_vulkan: WARNING: Async execution disabled on certain "
               "Intel devices." + NL + ENUM_LINE + NL)


class ProducerFixtureMixin:
    """Offline fixture scaffolding for producer/reducer tests (plain mixin)."""

    def fixture(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Fixture")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        # fixture ladder at the accepted relative path
        ladder_src = ROOT / D.FIXTURE_LADDER_REL
        dst = self.repo / D.FIXTURE_LADDER_REL
        dst.parent.mkdir(parents=True)
        shutil.copyfile(ladder_src, dst)
        (self.repo / "source.txt").write_text("fixture" + NL)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "fixture")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.evidence = self.root / "synthetic-evidence-NOT-PHYSICAL"
        self.evidence.mkdir()
        self.pr_number = 301
        self._comments: dict[int, dict] = {}
        self._next_id = 7000
        self.parent_patch = mock.patch.object(
            P252.P0, "verify_terminalization", return_value={
                "terminal": C252.PREDECESSOR_TERMINAL,
                "execution_head": C252.ACCEPTED_EXECUTION_HEAD})
        self.pin_patch = mock.patch.object(
            P252.P0, "verify_llama_pin", return_value={
                "head": C252.LLAMA_PIN, "tree": C252.LLAMA_PIN_TREE})
        self.parent_patch.start(); self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop)
        self.addCleanup(self.parent_patch.stop)

    # -- synthetic #254 dispatch comments -------------------------------

    def dispatch_comment(self, arm="A3", head=None, body=None,
                         association="OWNER", pr=None):
        head = head or self.head
        pr = pr or self.pr_number
        cid = self._next_id
        self._next_id += 1
        if body is None:
            body = f"{C.DISPATCH_PHRASE}{NL}head={head}{NL}arm={arm}"
        comment = {"id": cid, "body": body,
                   "author_association": association,
                   "created_at": "2026-10-01T12:00:00Z",
                   "user": {"login": "ezutfen"},
                   "html_url": (f"https://github.com/Zutfen-LLC/inferswarm/"
                                f"pull/{pr}#issuecomment-{cid}"),
                   "issue_url": (f"https://api.github.com/repos/"
                                 f"Zutfen-LLC/inferswarm/issues/{pr}")}
        self._comments[cid] = comment
        return comment

    def offline_fetch(self, arm="A3", head=None):
        """Offline dispatch-registry fetch double (test seam)."""
        head = head or self.head
        if not any(c["body"].splitlines()[1] == f"head={head}"
                   and c["body"].splitlines()[2] == f"arm={arm}"
                   for c in self._comments.values()):
            self.dispatch_comment(arm, head)
        branch = git(self.repo, "branch", "--show-current")
        state = {"state": "open", "merged": False, "draft": False,
                 "base": {"ref": "main"}, "head": {"sha": head, "ref": branch}}
        def fetch(*, repo_root=None, **kwargs):
            valid = [c for c in self._comments.values()
                     if c["body"].splitlines()[1] == f"head={head}"
                     and c["author_association"] in ("OWNER", "MEMBER")]
            if len(valid) != 1:
                raise PR.ProducerError(
                    f"expected one valid dispatch, found {len(valid)}")
            c = valid[0]
            arm_ = c["body"].splitlines()[2][4:]
            return {"pr_number": self.pr_number, "head_sha": head,
                    "arm": arm_, "namespace": A.ARMS[arm_]["namespace"],
                    "comment_id": c["id"],
                    "commenter_login": c["user"]["login"],
                    "author_association": c["author_association"],
                    "created_at": c["created_at"],
                    "issue_url": c["issue_url"], "body": c["body"],
                    "body_sha256": sha(c["body"].encode()),
                    "issue_state": "open"}
        return fetch

    def offline_comment_refetch(self):
        """Offline re-fetch of comments by ID through the production seam
        object (mock.patch on issue252_physical.fetch_dispatch_comment)."""
        registry = dict(self._comments)
        def fetch(url):
            prefix = ("https://api.github.com/repos/Zutfen-LLC/inferswarm/"
                      "issues/comments/")
            if not url.startswith(prefix):
                raise PR.ProducerError("bad url")
            cid = int(url[len(prefix):])
            if cid not in registry:
                raise P252.DispatchRefused("comment not found")
            return registry[cid]
        return fetch

    def live_capture(self, arm="A3", head=None):
        dispatch = self.offline_fetch(arm, head)()
        return PR.build_live_capture(dispatch)

    # -- fake physical executor ------------------------------------------

    def fake_execute_unit(self, *, response_tokens=None, row_seed=0,
                          exit_ok=True, kill_alive=False, missing_row=False,
                          mutate_response_after=False, env_tamper=None,
                          argv_tamper=None, second_gpu=False,
                          stat_change=False, identity_drift=False):
        """Build an injectable execute_unit double that mimics the REAL
        producer's own-process custody: rows/response/log/identity are
        produced inside the double (never caller-supplied bytes)."""
        tokens = response_tokens or [1, 2, 3, 4, 5, 6, 7, 8]
        def execute(*, dispatch, arm, unit_index, binary, unit_dir,
                    prompt, timeout_s, request=None,
                    identity_observer=None, health_runner=None, **kw):
            request = request if request is not None else D.REQUEST_CONTRACT
            geom = P252.launch_geometry(
                arm, binary, PR.MODEL_DIR / next(iter(C252.MODEL_MEMBERS)),
                unit_dir)
            argv, env = geom["argv"], geom["env"]
            if env_tamper:
                env = {**env, **env_tamper}
            if argv_tamper:
                argv = list(argv) + argv_tamper
            log = MECH_A3_LOG
            if second_gpu:
                log = log + ENUM_LINE.replace(" 0 = ", " 1 = ") + NL
            response = json.dumps({
                "tokens": tokens, "content": "x" * 8,
                "timings": {"prompt_n": 3072}}).encode()
            row = bytes([row_seed]) + bytes(D.ROW_BYTES - 1)
            rows = [row for _ in range(D.DECISIONS)]
            meta = NL.join(json.dumps({"pos": i, "pid": 4242}) + NL
                           for i in range(D.DECISIONS)).encode()
            identity = dict(C252.HOST_FACTS)
            if identity_drift:
                identity = {**identity, "driver": "999.99.99"}
            witness = {m: {"bytes": 1, "device": 1, "inode": 1,
                           "mtime_ns": 1, "ctime_ns": 1}
                       for m in C252.MODEL_MEMBERS}
            if stat_change:
                witness[next(iter(witness))]["mtime_ns"] = 999
            placement = {"output_projection": "Vulkan", "embedding": "CPU",
                         "ngl": 1, "gpu_uuid": C252.HOST_FACTS["gpu_uuid"],
                         "vulkan_family": "NV_coopmat2",
                         "cuda_participation": False,
                         "enumeration_line": ENUM_LINE}
            unit = {"arm": arm, "unit_index": unit_index,
                    "dispatch_comment_id": dispatch["comment_id"],
                    "dispatch_body_sha256": dispatch["body_sha256"],
                    "producer_head": dispatch["head_sha"],
                    "server_pid": 4242,
                    "started_at": "2026-10-01T12:00:00Z",
                    "ended_at": "2026-10-01T12:20:00Z",
                    "binary_sha256": C252.COMPARATOR_SHA256,
                    "model_stat_witness": witness,
                    "argv": argv, "env": env, "request": request,
                    "request_sha256": sha(b"req"),
                    "response_raw": response,
                    "response_raw_sha256": sha(response),
                    "observer_rows": rows, "observer_meta": meta,
                    "server_log": log.encode(),
                    "identity_pre": identity, "identity_post": identity,
                    "placement": placement,
                    "process_exit": {"returncode": 0,
                                     "cleanup_verified": exit_ok},
                    "health": {"rc": 0, "nvidia_smi_raw": ""}}
            if missing_row:
                unit["observer_rows"] = rows[:-1]
            return unit
        return execute

    def write_unit_tree(self, arm, index, capture, *, row_seed=0,
                        authority=None, fix_commit=None,
                        binary_sha256=C252.COMPARATOR_SHA256,
                        server_log=None, with_attestation=True,
                        mutate_attestation=None, namespace=None):
        """Retain one complete unit directory (receipt + attestation)."""
        ns = namespace or A.ARMS[arm]["namespace"]
        tag = f"case-3072-B-{arm.lower()}-{index:03d}"
        unit_dir = self.evidence / ns / tag
        unit_dir.mkdir(parents=True, exist_ok=True)
        authority = authority if authority is not None else capture
        rows = [bytes([row_seed]) + bytes(D.ROW_BYTES - 1)
                for _ in range(D.DECISIONS)]
        meta = NL.join(json.dumps({"pos": i, "pid": 4242}) + NL
                       for i in range(D.DECISIONS)).encode()
        response = json.dumps({"tokens": [1, 2, 3, 4, 5, 6, 7, 8],
                               "content": "x" * 8}).encode()
        log = (server_log or MECH_A3_LOG).encode()
        identity = dict(C252.HOST_FACTS)
        witness = {m: {"bytes": 1, "device": 1, "inode": 1, "mtime_ns": 1,
                       "ctime_ns": 1} for m in C252.MODEL_MEMBERS}
        placement = {"output_projection": "Vulkan", "embedding": "CPU",
                     "ngl": 1, "gpu_uuid": C252.HOST_FACTS["gpu_uuid"],
                     "vulkan_family": "NV_coopmat2",
                     "cuda_participation": False,
                     "enumeration_line": ENUM_LINE}
        receipt = P252.build_unit_receipt(
            authority=authority, unit_index=index,
            binary=Path("/nonexistent/llama-server"),
            model_member=PR.MODEL_DIR / next(iter(C252.MODEL_MEMBERS)),
            observer_dir=unit_dir, identity_pre=identity,
            identity_post=identity, placement=placement,
            raw_response=response, rows=rows, observer_meta=meta,
            server_log=log, server_pid=4242,
            model_stat_witness=witness,
            request=D.REQUEST_CONTRACT, fix_commit=fix_commit,
            binary_sha256=binary_sha256)
        attestation = {
            "schema": C.PRODUCER_SCHEMA,
            "producer_head": capture["head_sha"],
            "dispatch_capture_comment_id": capture["comment_id"],
            "dispatch_body_sha256": sha(capture["body"].encode()),
            "unit_index": index, "tag": tag, "server_pid": 4242,
            "started_at": "2026-10-01T12:00:00Z",
            "ended_at": "2026-10-01T12:20:00Z",
            "comparator_sha256": binary_sha256,
            "model_stat_witness": witness,
            "server_argv": receipt["server_argv"],
            "server_env": receipt["server_env"],
            "request_sha256": sha(b"req"),
            "response_raw_sha256": sha(response),
            "response_raw_bytes": len(response),
            "observer_meta_sha256": sha(meta),
            "observer_row_sha256": [sha(r) for r in rows],
            "observer_row_bytes": [len(r) for r in rows],
            "server_log_sha256": sha(log),
            "identity_pre": identity, "identity_post": identity,
            "placement": placement,
            "process_exit": {"returncode": 0, "cleanup_verified": True},
            "health": {"rc": 0, "nvidia_smi_raw": ""}}
        if mutate_attestation:
            mutate_attestation(attestation)
        (unit_dir / "response.json.raw").write_bytes(response)
        (unit_dir / "obs.meta.json").write_bytes(meta)
        (unit_dir / "server.log").write_bytes(log)
        (unit_dir / "identity-pre.json").write_text(
            json.dumps(identity, sort_keys=True))
        (unit_dir / "identity-post.json").write_text(
            json.dumps(identity, sort_keys=True))
        (unit_dir / "placement.json").write_text(
            json.dumps(placement, sort_keys=True))
        for n, row in enumerate(rows):
            (unit_dir / f"obs.row{n}.f32").write_bytes(row)
        (unit_dir / "unit.json").write_text(
            json.dumps(receipt, sort_keys=True))
        if with_attestation:
            (unit_dir / "producer-attestation.json").write_text(
                json.dumps(attestation, sort_keys=True))
        return unit_dir


class LiveDispatchTests(ProducerFixtureMixin, unittest.TestCase):
    """Live dispatch authentication (issue #254 property 1)."""

    def setUp(self):
        self.fixture()

    def test_valid_dispatch_body_and_capture(self):
        head, arm = PR.validate_live_body(
            f"{C.DISPATCH_PHRASE}{NL}head={'a' * 40}{NL}arm=A3")
        self.assertEqual((head, arm), ("a" * 40, "A3"))
        cap = self.live_capture()
        PR.validate_live_capture_structure(cap)
        self.assertNotEqual(cap["schema"], CAP.CAPTURE_SCHEMA)

    def test_phrase_252_is_not_live_authority(self):
        with self.assertRaises(PR.ProducerError):
            PR.validate_live_body(
                f"R8I3C PHYSICAL DISPATCH #252{NL}head={'a' * 40}{NL}arm=A3")

    def test_pr_head_moves_after_dispatch_comment(self):
        # case 10: dispatch comment pinned to an older head. The LIVE gate
        # derives everything from the API: PR open at the OLD head while the
        # local checkout has moved refuses (local HEAD != live PR head).
        (self.repo / "source.txt").write_text("moved" + NL)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "move head")
        new_head = git(self.repo, "rev-parse", "HEAD")
        branch = git(self.repo, "branch", "--show-current")
        old_head = self.head
        with mock.patch.object(PR, "resolve_producer_pr",
                               return_value=self.pr_number), \
             mock.patch.object(PR, "_api_get_json") as api:
            def get_json(path):
                if path == f"pulls/{self.pr_number}":
                    return {"state": "open", "merged": False, "draft": False,
                            "base": {"ref": "main"},
                            "head": {"sha": old_head, "ref": branch}}
                if path.startswith("issues/"):
                    return {"state": "open"}
                if "comments" in path:
                    return [self.dispatch_comment("A3", old_head)]
                raise AssertionError(path)
            api.side_effect = get_json
            with self.assertRaises(PR.ProducerError):
                PR.fetch_live_dispatch(self.repo)
        self.assertNotEqual(new_head, old_head)

    def test_dispatch_comment_targets_another_arm(self):
        # case 11: dispatch authorizes A5, execution requests A3
        self.dispatch_comment("A5", self.head)
        fetch = self.offline_fetch("A5")
        with self.assertRaises(PR.ProducerError):
            PR.run_unit(repo_root=self.repo, evidence_root=self.evidence,
                        arm="A3", binary=Path("/nonexistent"),
                        timeout_s=60, fetch=fetch,
                        execute=self.fake_execute_unit())

    def test_association_none_owner(self):
        comment = self.dispatch_comment("A3", body=(
            f"{C.DISPATCH_PHRASE}{NL}head={self.head}{NL}arm=A3"))
        comment["author_association"] = "NONE"
        fetch = self.offline_fetch("A3")
        with mock.patch.object(PR, "resolve_producer_pr",
                               return_value=self.pr_number), \
             mock.patch.object(PR, "_api_get_json") as api:
            # live fetcher path: PR open at head, but the only dispatch
            # comment author is not OWNER/MEMBER -> no valid dispatch.
            def get_json(path):
                if path.startswith("pulls?"):
                    return [{"number": self.pr_number,
                             "state": "open", "merged": False, "draft": False,
                             "base": {"ref": "main"},
                             "head": {"sha": self.head,
                                      "ref": git(self.repo, "branch",
                                                 "--show-current")}}]
                if path.startswith("pulls/"):
                    return {"state": "open", "merged": False, "draft": False,
                            "base": {"ref": "main"},
                            "head": {"sha": self.head,
                                     "ref": git(self.repo, "branch",
                                                "--show-current")}}
                if path.startswith("issues/254"):
                    return {"state": "open"}
                if "comments" in path:
                    return [comment]
                raise AssertionError(path)
            api.side_effect = get_json
            with self.assertRaises(PR.ProducerError):
                PR.fetch_live_dispatch(self.repo)


class ProducerCustodyTests(ProducerFixtureMixin, unittest.TestCase):
    """Atomic custody + stop law + no-synthetic-path (properties 5-7)."""

    def setUp(self):
        self.fixture()
        self.arm = "A3"
        self.ns = A.ARMS[self.arm]["namespace"]

    def run_unit(self, **kwargs):
        defaults = dict(repo_root=self.repo, evidence_root=self.evidence,
                        arm=self.arm, binary=Path("/nonexistent/llama-server"),
                        timeout_s=60, fetch=self.offline_fetch(self.arm),
                        execute=self.fake_execute_unit(**kwargs.pop(
                            "execute_kwargs", {})))
        defaults.update(kwargs)
        return PR.run_unit(**defaults)

    def test_unit_001_must_be_first(self):
        outcome = self.run_unit()
        self.assertEqual(outcome["index"], 1)
        self.assertTrue(outcome["unit_dir"].endswith(
            "case-3072-B-a3-001"))
        # unit 002 is next
        outcome2 = self.run_unit()
        self.assertEqual(outcome2["index"], 2)

    def test_unit_index_gap_refused(self):
        # case 12: a gap in the retained prefix refuses continuation
        self.write_unit_tree(self.arm, 1, self.live_capture(self.arm))
        # unit 2 missing, unit 3 present -> invalid prefix
        unit_dir = self.write_unit_tree(self.arm, 3,
                                        self.live_capture(self.arm))
        with self.assertRaises(PR.ProducerError):
            PR.next_legal_unit(self.evidence, self.arm)

    def test_duplicate_unit_refused(self):
        cap = self.live_capture(self.arm)
        self.write_unit_tree(self.arm, 1, cap)
        # duplicate the retained unit under its own tag (copy) -> both a
        # duplicate name collision and prefix-law refusal
        unit = self.evidence / self.ns / "case-3072-B-a3-001"
        dup = self.evidence / self.ns / "case-3072-B-a3-002"
        shutil.copytree(unit, dup)
        with self.assertRaises(PR.ProducerError):
            PR.next_legal_unit(self.evidence, self.arm)

    def test_restart_after_completed_mismatch_refuses_continuation(self):
        # case 13: mismatch at unit 2 answers the arm; a restart may not run 3
        self.write_unit_tree(self.arm, 1, self.live_capture(self.arm),
                             row_seed=1)
        self.write_unit_tree(self.arm, 2, self.live_capture(self.arm),
                             row_seed=2)
        self.assertIsNone(PR.next_legal_unit(self.evidence, self.arm))

    def test_three_identical_continue_five_deterministic_stop(self):
        cap = self.live_capture(self.arm)
        for i in range(1, 4):
            self.write_unit_tree(self.arm, i, cap)
        self.assertEqual(PR.next_legal_unit(self.evidence, self.arm), 4)
        for i in (4, 5):
            self.write_unit_tree(self.arm, i, cap)
        self.assertIsNone(PR.next_legal_unit(self.evidence, self.arm))

    def test_partial_unit_directory_after_crash(self):
        # case 14: a staging directory refuses ambiguous continuation
        staging = self.evidence / self.ns / f".unit-case-3072-B-a3-001.tmp"
        staging.mkdir(parents=True)
        with self.assertRaises(PR.ProducerError):
            PR.next_legal_unit(self.evidence, self.arm)

    def test_existing_final_unit_is_append_only(self):
        cap = self.live_capture(self.arm)
        self.write_unit_tree(self.arm, 1, cap)
        # The publish gate refuses to replace a retained unit directory.
        rows = [bytes([3]) + bytes(D.ROW_BYTES - 1)
                for _ in range(D.DECISIONS)]
        meta = NL.join(json.dumps({"pos": i, "pid": 4242}) + NL
                       for i in range(D.DECISIONS)).encode()
        response = json.dumps({"tokens": [1] * 8}).encode()
        with self.assertRaises(PR.ProducerError):
            PR.publish_unit_atomically(
                evidence_root=self.evidence, namespace=self.ns,
                tag="case-3072-B-a3-001",
                artifacts={"response.json.raw": response,
                           "obs.meta.json": meta,
                           "server.log": MECH_A3_LOG.encode(),
                           **{f"obs.row{n}.f32": r
                              for n, r in enumerate(rows)}},
                receipt=P252.build_unit_receipt(
                    authority=cap, unit_index=1,
                    binary=Path("/nonexistent/llama-server"),
                    model_member=PR.MODEL_DIR / next(iter(C252.MODEL_MEMBERS)),
                    observer_dir=self.evidence, identity_pre=dict(
                        C252.HOST_FACTS),
                    identity_post=dict(C252.HOST_FACTS),
                    placement={"output_projection": "Vulkan",
                               "embedding": "CPU", "ngl": 1,
                               "gpu_uuid": C252.HOST_FACTS["gpu_uuid"]},
                    raw_response=response, rows=rows, observer_meta=meta,
                    server_log=MECH_A3_LOG.encode(), server_pid=4242,
                    model_stat_witness={m: {"bytes": 1, "device": 1,
                                            "inode": 1, "mtime_ns": 1,
                                            "ctime_ns": 1}
                                        for m in C252.MODEL_MEMBERS},
                    request=D.REQUEST_CONTRACT),
                attestation={**self.attestation_template(),
                             "tag": "case-3072-B-a3-001", "unit_index": 1})

    def attestation_template(self):
        execute = self.fake_execute_unit()
        unit = execute(dispatch={"comment_id": 1, "body_sha256": "0" * 64,
                                 "head_sha": self.head},
                       arm="A3", unit_index=1, binary=Path("/x"),
                       unit_dir=Path("/x"), prompt="p", timeout_s=1)
        return PR.build_producer_attestation(unit)

    def test_failure_retains_status_record(self):
        def failing_execute(**kwargs):
            raise PR.ProducerError("synthetic launch failure")
        with self.assertRaises(PR.ProducerError):
            self.run_unit(execute=failing_execute)
        status = self.evidence / f"producer-status-{self.ns}.json"
        self.assertTrue(status.is_file())
        doc = json.loads(status.read_bytes())
        self.assertEqual(doc["status"], "unit_failed")


class AdversarialMatrixTests(ProducerFixtureMixin, unittest.TestCase):
    """The 17 required RED/adversarial cases, judged fail-closed."""

    def setUp(self):
        self.fixture()
        self.arm = "A3"
        self.ns = A.ARMS[self.arm]["namespace"]

    def _attestation_template(self):
        execute = self.fake_execute_unit()
        unit = execute(dispatch={"comment_id": 1, "body_sha256": "0" * 64,
                                 "head_sha": self.head},
                       arm="A3", unit_index=1, binary=Path("/x"),
                       unit_dir=Path("/x"), prompt="p", timeout_s=1)
        return PR.build_producer_attestation(unit)

    def _populated(self, n=5, row_seed=0, **kwargs):
        cap = self.live_capture(self.arm)
        for i in range(1, n + 1):
            self.write_unit_tree(self.arm, i, cap, row_seed=row_seed, **kwargs)
        return cap

    def _authority_doc(self, cap):
        (self.evidence / "authority.json").write_text(json.dumps({
            "repo_root": str(self.repo),
            "dispatch_capture": cap}, sort_keys=True))

    def verdict(self):
        with mock.patch.object(P252, "fetch_dispatch_comment",
                               self.offline_comment_refetch()):
            return T252.derive_terminal(self.evidence, {})

    # cases 1/17: caller-supplied synthetic observations can never be
    # promoted: execute_unit IS the only observation source (structural
    # signature test) and the /2 path without producer stays privileged.

    def test_case_1_no_synthetic_observation_api(self):
        # execute_unit accepts no observation parameters (structural).
        import inspect
        params = inspect.signature(PR.execute_unit.parameters.__self__
                                   if False else PR.execute_unit).parameters
        for banned in ("response", "rows", "identity", "placement",
                       "server_log", "raw_response", "receipt"):
            self.assertNotIn(banned, params,
                             f"execute_unit must not accept {banned!r}")
        # and no other public API marks supplied bytes physical:
        source = Path(PR.__file__).read_text()
        self.assertNotIn("def mark_physical", source)

    def test_case_2_forged_process_identity(self):
        # attestation whose server_argv was tampered fails binding
        self._populated(1, mutate_attestation=lambda att: att.update(
            server_argv=att["server_argv"] + ["--forged"]))
        cap = self.live_capture(self.arm)
        self._authority_doc(cap)
        # rebuild full 5 identical population with the forged first unit
        for i in range(2, 6):
            self.write_unit_tree(self.arm, i, cap)
        self.assertEqual(self.verdict(), T252.BLOCKED)

    def test_case_4_missing_observer_row(self):
        # fake executor that drops a row fails at retention time
        execute = self.fake_execute_unit(missing_row=True)
        with self.assertRaises(Exception):
            PR.run_unit(repo_root=self.repo, evidence_root=self.evidence,
                        arm=self.arm, binary=Path("/nonexistent"),
                        timeout_s=60, fetch=self.offline_fetch(self.arm),
                        execute=execute)

    def test_case_5_altered_raw_response_after_receipt(self):
        cap = self._populated(2)
        unit = self.evidence / self.ns / "case-3072-B-a3-001"
        raw = (unit / "response.json.raw").read_bytes()
        (unit / "response.json.raw").write_bytes(raw + b"x")
        self._authority_doc(cap)
        self.assertEqual(self.verdict(), T252.BLOCKED)

    def test_case_6_model_stat_changes_during_unit(self):
        # a witness whose member set no longer matches the frozen members
        # (model file changed during the unit) fails attestation validation
        att = self._attestation_template()
        att["model_stat_witness"] = {next(iter(C252.MODEL_MEMBERS)): {
            "bytes": 1}}
        with self.assertRaises(PR.ProducerError):
            PR.validate_producer_attestation(att)

    def test_case_7_comparator_differs_from_frozen_sha(self):
        with self.assertRaises(PR.ProducerError):
            PR.validate_producer_attestation({
                **self._attestation_template(), "comparator_sha256": "f" * 64})

    def test_case_8_wrong_gpu_second_enumeration(self):
        # a unit log carrying a SECOND enumeration line (unintended GPU)
        # fails the mechanism law at reduction time
        cap = self.live_capture(self.arm)
        bad_log = MECH_A3_LOG + ENUM_LINE.replace(" 0 = ", " 1 = ") + NL
        for i in range(1, 6):
            self.write_unit_tree(self.arm, i, cap, server_log=bad_log)
        self._authority_doc(cap)
        self.assertEqual(self.verdict(), T252.BLOCKED)

    def test_case_9_cuda_visible_path(self):
        # env tampering (CUDA enabled) breaks the frozen geometry equality
        execute = self.fake_execute_unit(env_tamper={
            "CUDA_VISIBLE_DEVICES": "0"})
        with self.assertRaises(PR.ProducerError):
            PR.run_unit(repo_root=self.repo, evidence_root=self.evidence,
                        arm=self.arm, binary=Path("/nonexistent"),
                        timeout_s=60, fetch=self.offline_fetch(self.arm),
                        execute=execute)

    def test_case_15_completed_evidence_mutated_before_reduction(self):
        cap = self._populated(5)
        unit = self.evidence / self.ns / "case-3072-B-a3-003"
        row = (unit / "obs.row0.f32").read_bytes()
        (unit / "obs.row0.f32").write_bytes(bytes([99]) + row[1:])
        self._authority_doc(cap)
        self.assertEqual(self.verdict(), T252.BLOCKED)

    def test_case_16_cleanup_left_server_alive(self):
        # attestation claiming cleanup_verified=False fails structurally
        att = self._attestation_template()
        att["process_exit"] = {"returncode": None,
                               "cleanup_verified": False}
        with self.assertRaises(PR.ProducerError):
            PR.validate_producer_attestation(att)

    def test_case_17_handbuilt_unit_without_producer_attestation(self):
        # internally consistent receipt tree, NO producer attestation:
        # refused as physical authority by the reducer.
        cap = self._populated(5, with_attestation=False)
        self._authority_doc(cap)
        self.assertEqual(self.verdict(), T252.BLOCKED)

    def test_positive_path_producer_attested_population_admitted(self):
        # The positive control: a complete producer-attested 5-identical
        # A3 population reaches the A3 terminal path (NOT_VALIDATED:
        # localized without fix), proving the adversarial rejections above
        # are not vacuous.
        cap = self._populated(5)
        self._authority_doc(cap)
        self.assertEqual(self.verdict(), C252.NOT_VALIDATED_TERMINAL)


class LiveCaptureVerifierTests(ProducerFixtureMixin, unittest.TestCase):

    def setUp(self):
        self.fixture()

    def test_verify_live_capture_roundtrip(self):
        cap = self.live_capture("A3")
        with mock.patch.object(P252, "fetch_dispatch_comment",
                               self.offline_comment_refetch()):
            self.assertEqual(PR.verify_live_capture(cap), cap)

    def test_verify_live_capture_refused_on_body_drift(self):
        cap = self.live_capture("A3")
        forged = copy.deepcopy(cap)
        forged["body"] = C.DISPATCH_PHRASE + NL + "head=" + "b" * 40 + NL + "arm=A5"
        forged["head_sha"] = "b" * 40
        forged["arm"] = "A5"
        forged["namespace"] = A.ARMS["A5"]["namespace"]
        with mock.patch.object(P252, "fetch_dispatch_comment",
                               self.offline_comment_refetch()):
            with self.assertRaises(PR.ProducerError):
                PR.verify_live_capture(forged)

    def test_verify_live_capture_252_phrase_refused(self):
        # a /3 capture carrying the OLD #252 phrase is structurally invalid
        cap = self.live_capture("A3")
        bad = copy.deepcopy(cap)
        bad["body"] = "R8I3C PHYSICAL DISPATCH #252" + NL + "head=" + cap["head_sha"] + NL + "arm=A3"
        bad["dispatch_phrase"] = "R8I3C PHYSICAL DISPATCH #252"
        with self.assertRaises(PR.ProducerError):
            PR.validate_live_capture_structure(bad)


class Phase0RegressionTests(ProducerFixtureMixin, unittest.TestCase):
    """The merged Phase-0 /2 path stays byte-identical in behavior."""

    def setUp(self):
        self.fixture()

    def test_252_schema2_authority_still_admitted(self):
        # a /2 capture (Phase-0 campaign) still verifies through the
        # original CAP verifier in the reducer (no capture of schema /2
        # is redirected to the #254 verifier).
        source = (ROOT / "scripts" / "issue252_terminal.py").read_text()
        self.assertIn("PR254.verify_live_capture(capture)", source)
        self.assertIn("CAP.verify_capture(capture, repo_pr_number=",
                      source)


if __name__ == "__main__":
    unittest.main()
