import csv
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from eyespysc import __version__
from eyespysc import sperm_count as sc

BACKGROUND = 139
SIZE = (700, 900)  # height, width


def blank(seed=0):
    return np.full(SIZE, BACKGROUND, dtype=np.float32), np.random.default_rng(seed)


def draw_sperm(img, head_xy, angle_deg, tail_len=260, head_value=75, tail_value=118):
    """Head ellipse + thick midpiece + faint 2px tail, pointing along angle_deg."""
    direction = np.array([np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))])
    head = np.array(head_xy, dtype=np.float64)
    cv2.ellipse(img, tuple(int(v) for v in head), (11, 7), angle_deg, 0, 360, head_value, -1)
    neck = head + direction * 10
    mid_end = neck + direction * 30
    cv2.line(img, tuple(int(v) for v in neck), tuple(int(v) for v in mid_end), 100, 4)
    tail_end = mid_end + direction * tail_len
    cv2.line(img, tuple(int(v) for v in mid_end), tuple(int(v) for v in tail_end), tail_value, 2)
    return tuple(int(v) for v in tail_end)


def finish(img, rng):
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    img = img + rng.normal(0, 2.5, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def heads_near(result, xy, tol=20):
    return [
        h
        for inst in result["instances"]
        for h in inst.heads_xy
        if np.hypot(h[0] - xy[0], h[1] - xy[1]) <= tol
    ]


class SyntheticCountingTests(unittest.TestCase):
    def test_single_sperm(self):
        img, rng = blank()
        draw_sperm(img, (150, 200), 20)
        result = sc.analyze_image(finish(img, rng))
        self.assertEqual(result["sperm_count"], 1)
        self.assertEqual([i.kind for i in result["instances"]], ["single"])
        self.assertTrue(heads_near(result, (150, 200)))

    def test_two_separate_sperm(self):
        img, rng = blank(1)
        draw_sperm(img, (120, 120), 10)
        draw_sperm(img, (150, 450), -15)
        result = sc.analyze_image(finish(img, rng))
        self.assertEqual(result["sperm_count"], 2)
        self.assertEqual(sorted(i.kind for i in result["instances"]), ["single", "single"])

    def test_crossing_tails_become_one_overlap_cluster_counting_both_heads(self):
        img, rng = blank(2)
        draw_sperm(img, (150, 150), 35, tail_len=330)
        draw_sperm(img, (150, 520), -35, tail_len=330)
        result = sc.analyze_image(finish(img, rng))
        self.assertEqual(result["sperm_count"], 2)
        self.assertEqual(len(result["instances"]), 1)
        cluster = result["instances"][0]
        self.assertEqual(cluster.kind, "overlap_cluster")
        self.assertEqual(cluster.head_count, 2)
        self.assertTrue(heads_near(result, (150, 150)))
        self.assertTrue(heads_near(result, (150, 520)))

    def test_debris_and_round_cells_are_not_counted(self):
        img, rng = blank(3)
        for x, y in [(200, 200), (400, 300), (650, 500)]:
            cv2.circle(img, (x, y), 12, 90, -1)
        cv2.circle(img, (500, 150), 30, 110, 2)  # round cell outline
        cv2.circle(img, (500, 150), 22, 125, -1)
        result = sc.analyze_image(finish(img, rng))
        self.assertEqual(result["sperm_count"], 0)
        self.assertEqual(result["instances"], [])

    def test_debris_on_middle_of_tail_is_not_a_second_head(self):
        img, rng = blank(4)
        draw_sperm(img, (120, 300), 0, tail_len=400)
        cv2.circle(img, (320, 300), 10, 85, -1)
        result = sc.analyze_image(finish(img, rng))
        self.assertEqual(result["sperm_count"], 1)
        self.assertTrue(heads_near(result, (120, 300)))

    def test_headless_tail_is_reported_but_not_counted(self):
        img, rng = blank(5)
        cv2.line(img, (100, 400), (500, 250), 118, 2)
        result = sc.analyze_image(finish(img, rng))
        self.assertEqual(result["sperm_count"], 0)
        self.assertEqual([i.kind for i in result["instances"]], ["headless_tail"])

    def test_pure_noise_produces_nothing(self):
        img, rng = blank(6)
        result = sc.analyze_image(finish(img, rng))
        self.assertEqual(result["instances"], [])

    def test_deterministic(self):
        img, rng = blank(7)
        draw_sperm(img, (150, 200), 20)
        gray = finish(img, rng)
        first, second = sc.analyze_image(gray), sc.analyze_image(gray)
        self.assertTrue(np.array_equal(first["instance_map"], second["instance_map"]))
        self.assertEqual(first["instances"], second["instances"])


class HelperTests(unittest.TestCase):
    def test_crossing_number_ignores_staircase_but_finds_junction(self):
        stair = np.zeros((9, 9), np.uint8)
        for i in range(8):
            stair[i, i] = 1
            stair[i, i + 1] = 1
        self.assertLess(sc.crossing_number(stair)[stair > 0].max(), 3)

        cross = np.zeros((9, 9), np.uint8)
        cross[4, :] = 1
        cross[:, 4] = 1
        self.assertGreaterEqual(sc.crossing_number(cross)[4, 4], 3)

    def test_local_straightness_line_vs_circle(self):
        line = np.zeros((10, 200), np.uint8)
        line[5, 5:195] = 1
        circle = np.zeros((120, 120), np.uint8)
        cv2.circle(circle, (60, 60), 12, 1, 1)
        circle[60, 72] = 0  # open the loop so it has two ends
        line_value = sc.local_straightness(sc.longest_skeleton_path(line), 30)
        circle_value = sc.local_straightness(sc.longest_skeleton_path(circle), 30)
        self.assertGreater(line_value, 0.98)
        self.assertLess(circle_value, 0.8)

    def test_longest_path_is_ordered_and_measures_diagonals(self):
        diag = np.zeros((50, 50), np.uint8)
        for i in range(40):
            diag[i, i] = 1
        path = sc.longest_skeleton_path(diag)
        self.assertEqual(len(path), 40)
        self.assertAlmostEqual(sc.path_length(path), 39 * np.sqrt(2), places=3)
        self.assertTrue(np.all(np.abs(np.diff(path, axis=0)).max(axis=1) == 1))

    def test_contrib_thinning_is_never_used(self):
        # Validated counts use Zhang-Suen; an OpenCV-contrib install must not
        # switch the pipeline to cv2.ximgproc.thinning.
        def contrib_thinning(*_args):
            raise AssertionError("cv2.ximgproc.thinning was called")

        img, rng = blank(12)
        draw_sperm(img, (150, 200), 20)
        gray = finish(img, rng)
        with mock.patch.object(
            cv2, "ximgproc", types.SimpleNamespace(thinning=contrib_thinning), create=True
        ):
            self.assertEqual(sc.analyze_image(gray)["sperm_count"], 1)


class MagnificationTests(unittest.TestCase):
    def test_scale_follows_magnification_ratio(self):
        self.assertEqual(sc.scale_factor(2048, 1536), 1.0)
        self.assertEqual(sc.scale_factor(2048, 1536, 40), 2.0)
        self.assertEqual(sc.scale_factor(900, 700, 10), 0.5)

    def test_filename_token(self):
        self.assertEqual(sc.magnification_from_name("caput_40x_0019_TRANS.png"), 40.0)
        self.assertEqual(sc.magnification_from_name("40x_cauda.tif"), 40.0)
        self.assertIsNone(sc.magnification_from_name("caput_0019_TRANS.png"))
        self.assertIsNone(sc.magnification_from_name("box40xyz_0001.png"))

    def test_presets(self):
        self.assertFalse(sc.settings_for_magnification(20).relief_contrast)
        self.assertTrue(sc.settings_for_magnification(40).relief_contrast)
        with self.assertRaises(ValueError):
            sc.settings_for_magnification(0)

    def test_sperm_drawn_twice_as_large_is_found_at_double_magnification(self):
        img = np.full((1400, 1800), BACKGROUND, dtype=np.float32)
        rng = np.random.default_rng(11)
        direction = np.array([np.cos(np.radians(20)), np.sin(np.radians(20))])
        head = np.array([300.0, 400.0])
        cv2.ellipse(img, (300, 400), (22, 14), 20, 0, 360, 75, -1)
        neck, mid_end = head + direction * 20, head + direction * 80
        cv2.line(img, tuple(int(v) for v in neck), tuple(int(v) for v in mid_end), 100, 8)
        tail_end = mid_end + direction * 520
        cv2.line(img, tuple(int(v) for v in mid_end), tuple(int(v) for v in tail_end), 118, 4)
        img = cv2.GaussianBlur(img, (0, 0), 1.6) + rng.normal(0, 2.5, img.shape)
        gray = np.clip(img, 0, 255).astype(np.uint8)
        settings = sc.Settings(magnification=40)  # scaling only, no relief preset
        result = sc.analyze_image(gray, settings)
        self.assertEqual(result["sperm_count"], 1)
        self.assertTrue(heads_near(result, (300, 400), tol=40))


class OutputTests(unittest.TestCase):
    def test_write_outputs_and_rgb_input(self):
        img, rng = blank(8)
        draw_sperm(img, (150, 200), 20)
        gray = finish(img, rng)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "rgb_input.png"
            cv2.imwrite(str(src), cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
            loaded = sc.load_gray(src)
            self.assertEqual(loaded.shape, gray.shape)

            result = sc.analyze_image(loaded)
            out_dir = Path(tmp) / "out"
            summary = sc.write_outputs(src, loaded, result, out_dir)
            for name in (
                "overlay.png",
                "sperm_mask.png",
                "candidate_pixels.png",
                "instance_labels.png",
                "instances.json",
            ):
                self.assertTrue((out_dir / name).exists(), name)
            self.assertEqual(len(list((out_dir / "crops").glob("*.png"))), len(result["instances"]))
            data = json.loads((out_dir / "instances.json").read_text())
            self.assertEqual(data["summary"]["sperm_count"], summary["sperm_count"])
            self.assertEqual(len(data["instances"]), len(result["instances"]))
            labels = cv2.imread(str(out_dir / "instance_labels.png"), cv2.IMREAD_UNCHANGED)
            self.assertEqual(labels.dtype, np.uint16)
            self.assertTrue(np.array_equal(labels, result["instance_map"]))

    def test_minimal_outputs_only_overlay_and_candidates(self):
        img, rng = blank(9)
        draw_sperm(img, (150, 200), 20)
        gray = finish(img, rng)
        result = sc.analyze_image(gray)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            summary = sc.write_outputs(Path("x.png"), gray, result, out_dir, minimal=True)
            self.assertEqual(
                sorted(p.name for p in out_dir.iterdir()),
                ["candidate_pixels.png", "original.png", "overlay.png"],
            )
            original = cv2.imread(str(out_dir / "original.png"), cv2.IMREAD_UNCHANGED)
            self.assertTrue(np.array_equal(original, gray))
            self.assertEqual(summary["sperm_count"], 1)

    def test_16bit_input_is_scaled_not_clipped(self):
        img, rng = blank(10)
        draw_sperm(img, (150, 200), 20)
        gray = finish(img, rng)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "deep.png"
            cv2.imwrite(str(src), gray.astype(np.uint16) * 256)
            loaded = sc.load_gray(src)
            self.assertEqual(loaded.dtype, np.uint8)
            self.assertTrue(np.array_equal(loaded, gray))
            self.assertEqual(sc.analyze_image(loaded)["sperm_count"], 1)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "eyespysc", *args], capture_output=True, text=True, check=False
        )

    def test_version(self):
        done = self.run_cli("--version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), f"eyespysc {__version__}")

    def test_batch_writes_summary_and_mirrors_subfolders(self):
        img, rng = blank(13)
        draw_sperm(img, (150, 200), 20)
        gray = finish(img, rng)
        with tempfile.TemporaryDirectory() as tmp:
            inputs = Path(tmp) / "in"
            (inputs / "session").mkdir(parents=True)
            cv2.imwrite(str(inputs / "session" / "one_sperm.png"), gray)
            out = Path(tmp) / "out"
            done = self.run_cli("--input", str(inputs), "--output-root", str(out))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("one_sperm.png: 1 sperm", done.stdout)
            with (out / "summary.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["sperm_count"] for row in rows], ["1"])
            self.assertTrue((out / "session" / "one_sperm" / "overlay.png").exists())

            again = self.run_cli("--input", str(inputs), "--output-root", str(out))
            self.assertNotEqual(again.returncode, 0)
            self.assertIn("--overwrite", again.stderr)

    def write_one_sperm(self, path, seed=13):
        img, rng = blank(seed)
        draw_sperm(img, (150, 200), 20)
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), finish(img, rng))

    def test_json_progress_reports_each_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs = Path(tmp) / "in"
            self.write_one_sperm(inputs / "a.png")
            self.write_one_sperm(inputs / "b.png", seed=14)
            out = Path(tmp) / "out"
            done = self.run_cli(
                "--input", str(inputs), "--output-root", str(out), "--minimal", "--json-progress"
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            events = [json.loads(line) for line in done.stdout.splitlines()]
            self.assertEqual([e["event"] for e in events], ["start", "image", "image", "done"])
            self.assertEqual(events[0]["total"], 2)
            first = events[1]
            self.assertEqual((first["index"], first["name"]), (1, "a.png"))
            self.assertEqual(first["summary"]["sperm_count"], 1)
            self.assertTrue(Path(first["overlay"]).is_file())
            self.assertTrue(Path(first["original"]).is_file())
            self.assertEqual(Path(events[-1]["summary_csv"]), (out / "summary.csv").resolve())

    def test_preview_only_writes_previews_and_no_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in" / "big.png"
            src.parent.mkdir()
            cv2.imwrite(str(src), np.full((1800, 2400), 120, np.uint8))
            out = Path(tmp) / "previews"
            done = self.run_cli(
                "--input", str(src), "--output-root", str(out), "--preview-only", "--json-progress"
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            events = [json.loads(line) for line in done.stdout.splitlines()]
            self.assertEqual([e["event"] for e in events], ["start", "image", "done"])
            image = events[1]
            self.assertEqual((image["width"], image["height"]), (2400, 1800))
            preview = cv2.imread(image["preview"], cv2.IMREAD_UNCHANGED)
            self.assertEqual(preview.shape, (1200, sc.PREVIEW_LONG_SIDE))
            self.assertFalse((out / "summary.csv").exists())
            self.assertEqual([p.name for p in (out / "big").iterdir()], ["preview.png"])

    def test_several_inputs_and_output_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "one" / "x.png"
            second = Path(tmp) / "two" / "y.png"
            self.write_one_sperm(first)
            self.write_one_sperm(second, seed=14)
            out = Path(tmp) / "out"
            done = self.run_cli(
                "--input", str(first), "--input", str(second), "--output-root", str(out)
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            with (out / "summary.csv").open(newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)
            self.assertTrue((out / "x" / "overlay.png").exists())
            self.assertTrue((out / "y" / "overlay.png").exists())

            clash = Path(tmp) / "three" / "x.png"
            self.write_one_sperm(clash)
            done = self.run_cli(
                "--input", str(first), "--input", str(clash), "--output-root", str(Path(tmp) / "o2")
            )
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("would both write to", done.stderr)


if __name__ == "__main__":
    unittest.main()
