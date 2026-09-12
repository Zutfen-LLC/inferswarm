"""Byte-oriented V0-C frozen visible-response reduction tests."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v0c_correctness as correctness  # noqa: E402

PROMPT = b"The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:"
REFERENCE = (b'The sentence "The quick brown fox jumps over the lazy dog" is a well-known pangram, '
             b'and after this sentence, the next sentence could be anything, as there is no specific '
             b'rule or context provided for what comes next.')


class V0CCorrectnessTests(unittest.TestCase):
    def retained_stdout(self) -> bytes:
        artifact = ROOT / "docs/investigations/vulkan-v0-c/evidence/v0c-final-execution/accounting.json"
        return json.loads(artifact.read_text(encoding="utf-8"))["raw"]["stdout"].encode("utf-8")

    def test_retained_canonical_stdout_is_byte_exact(self):
        result = correctness.reduce(self.retained_stdout(), PROMPT, REFERENCE)
        self.assertTrue(result["byte_exact_visible_output"])
        self.assertEqual(result["visible_response_bytes"], REFERENCE)

    def test_changed_word_is_not_byte_exact(self):
        transcript = self.retained_stdout().replace(b"well-known", b"famous")
        self.assertFalse(correctness.reduce(transcript, PROMPT, REFERENCE)["byte_exact_visible_output"])

    def test_changed_punctuation_is_not_byte_exact(self):
        transcript = self.retained_stdout().replace(b"comes next.", b"comes next!")
        self.assertFalse(correctness.reduce(transcript, PROMPT, REFERENCE)["byte_exact_visible_output"])

    def test_missing_prompt_fails_closed(self):
        with self.assertRaisesRegex(correctness.CorrectnessError, "prompt"):
            correctness.extract_visible_response(b"noise\n", PROMPT)

    def test_duplicate_prompt_fails_closed(self):
        transcript = b"> " + PROMPT + b"\n" + REFERENCE + b"\n[ Prompt: x]\n> " + PROMPT + b"\n"
        with self.assertRaisesRegex(correctness.CorrectnessError, "prompt"):
            correctness.extract_visible_response(transcript, PROMPT)

    def test_missing_timing_terminator_fails_closed(self):
        with self.assertRaisesRegex(correctness.CorrectnessError, "timing"):
            correctness.extract_visible_response(b"> " + PROMPT + b"\n" + REFERENCE, PROMPT)

    def test_spinner_banner_noise_before_prompt_is_structurally_ignored(self):
        transcript = b"spinner\b-\b\\\nbanner\n> " + PROMPT + b"\n" + REFERENCE + b"\n\n[ Prompt: 1 t/s]\n"
        self.assertEqual(correctness.extract_visible_response(transcript, PROMPT), REFERENCE)


if __name__ == "__main__":
    unittest.main()
