"""Run with: python -m unittest discover tests"""
import csv
import io
import unittest

from scorer.score import SubmissionError, load_reference, parse_predictions, score_bytes
from tools.fetch import find_url, is_allowed
from tools.submission import collect, md, parse_issue_form

FORM = """### Model name

my-model @someone

### Team or organization

Lab | X

### Training

Fine-tuned or trained for Tibetan

### Open weights

Yes

### Model or code link

javascript:alert(1)

### Paper or report link

_No response_

### Predictions CSV

[preds.csv](https://github.com/user-attachments/files/12345/preds.csv)

### Notes

_No response_

### Rules

- [X] These predictions were produced by the model named above, without using the benchmark's ground-truth transcriptions.
"""


def to_csv(rows, header=("id", "transcription")) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def gt_rows():
    with open("scorer/data/ground_truth.csv", encoding="utf-8", newline="") as fh:
        return [(r["id"], r["transcription"]) for r in csv.DictReader(fh)]


class ScorerTest(unittest.TestCase):
    def test_ground_truth_scores_zero(self):
        result = score_bytes(to_csv(gt_rows()))
        self.assertEqual(result["mean_cer"], 0.0)
        self.assertEqual(result["coverage"], len(load_reference()[0]))

    def test_missing_pages_count_as_one(self):
        rows = gt_rows()
        result = score_bytes(to_csv(rows[10:]))
        self.assertAlmostEqual(result["mean_cer"], round(10 / len(rows), 4))
        self.assertTrue(any("missing" in w for w in result["warnings"]))

    def test_zero_padding_repaired(self):
        preds, warnings = parse_predictions(to_csv([(str(int(i)), t) for i, t in gt_rows()]))
        self.assertIn("0002", preds)
        self.assertTrue(warnings)

    def test_rejects_bad_files(self):
        rows = gt_rows()
        bad = [
            to_csv(rows, header=("page", "text")),
            to_csv(rows + [rows[0]]),
            to_csv([("9999", "x")]),
            "id,transcription\n0002,caf\xe9\n".encode("latin-1"),
            b"id,transcription\n",
        ]
        for raw in bad:
            with self.assertRaises(SubmissionError):
                parse_predictions(raw)


class IssueFormTest(unittest.TestCase):
    def test_parse_and_sanitize(self):
        fields = parse_issue_form(FORM)
        self.assertEqual(fields["paper_url"], "")
        meta, url = collect({"ISSUE_BODY": FORM, "ISSUE_AUTHOR": "alice"})
        self.assertEqual(url, "https://github.com/user-attachments/files/12345/preds.csv")
        self.assertEqual(meta["training"], "fine-tuned")
        self.assertIs(meta["open_weights"], True)
        self.assertEqual(meta["model_url"], "")  # non-http link dropped
        self.assertNotIn("@", md(meta["model"]))
        self.assertIn("\\|", md(meta["team"]))

    def test_unchecked_rules_rejected(self):
        with self.assertRaises(SubmissionError):
            collect({"ISSUE_BODY": FORM.replace("[X]", "[ ]")})

    def test_url_allowlist(self):
        self.assertTrue(is_allowed("https://huggingface.co/datasets/a/b/resolve/main/p.csv"))
        self.assertTrue(is_allowed("https://gist.githubusercontent.com/u/0abc/raw/p.csv"))
        self.assertFalse(is_allowed("https://evil.example/p.csv"))
        self.assertFalse(is_allowed("https://github.com/user-attachments/files/1/p.csv?x=http://a"))
        with self.assertRaises(SubmissionError):
            find_url("see http://example.com/p.csv")


if __name__ == "__main__":
    unittest.main()
