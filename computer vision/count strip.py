#!/usr/bin/env python3
"""
count_strip.py - count free vs occupied parking spots along ONE strip, from a
recorded pass of the bot (video file saved from the stream).

How it works
  1. Run the 2-class YOLO detector + BoT-SORT tracker over the strip's time window.
  2. Count every track ONCE, at the moment it crosses a vertical line in the frame
     (default: the center, where the camera sees the spot most head-on).
  3. Decide each object's class by a confidence-weighted vote over all frames of its
     track (not a single frame).
  4. Validate the pass:
       - total events must equal the strip's known spot count
       - bot drives at steady speed, so crossings must be evenly spaced in time;
         a ~2x gap means a missed spot, a ~0x gap means a double count
       - first/last crossing must sit near the logged start/stop times
       - every event's class vote must be confident
  5. Any failed check -> the pass is FLAGGED for human review (exit code 2).

Outputs (in --out): report.json, events.csv, observations.csv, events/*.jpg
(one annotated frame per counted object, for the reviewer).

Typical use
  python count_strip.py --video strip_A.mp4 --weights best.pt \
      --start 12.0 --stop 171.0 --expected-total 30 --direction left

Tune thresholds without re-running the model:
  python count_strip.py --from-observations runs/count/strip_A/observations.csv \
      --start 12.0 --stop 171.0 --expected-total 30 --edge-offset 0.4

Exit codes: 0 = pass looks clean, 2 = flagged for review, 1 = bad usage/error.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # only needed when reading video; the counting logic itself does not need it
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


# --------------------------------------------------------------------------- #
# Core logic (pure Python, no model needed)
# --------------------------------------------------------------------------- #
@dataclass
class TrackState:
    track_id: int
    votes: dict = field(default_factory=dict)  # class id -> summed confidence
    n_votes: int = 0
    conf_sum: float = 0.0
    prev_x: float | None = None
    prev_t: float | None = None
    cross_t: float | None = None
    cross_frame: int | None = None
    snapshot: bytes | None = None


class LineCounter:
    """Registers the first time each track crosses a vertical line."""

    def __init__(self, line_x: float = 0.5, direction: str = "left", vote_band: float = 0.35):
        assert direction in ("left", "right", "any")
        self.line_x = line_x
        self.direction = direction  # direction objects move across the IMAGE
        self.vote_band = vote_band
        self.tracks: dict[int, TrackState] = {}
        self.opposite_crossings = 0  # crossings in the direction we are NOT counting

    def _crossing(self, prev_x: float, x: float) -> str | None:
        L = self.line_x
        if prev_x > L >= x:
            return "left"
        if prev_x < L <= x:
            return "right"
        return None

    def update(self, t: float, frame_idx: int, dets) -> list[int]:
        """dets: iterable of (track_id, class_id, conf, x_center_normalized).
        Returns the track ids that crossed the line in this frame."""
        crossed_now = []
        for tid, cls, conf, x in dets:
            tr = self.tracks.setdefault(tid, TrackState(tid))
            if abs(x - self.line_x) <= self.vote_band:  # only the central part of the frame votes
                tr.votes[cls] = tr.votes.get(cls, 0.0) + conf
                tr.n_votes += 1
                tr.conf_sum += conf
            if tr.prev_x is not None:
                d = self._crossing(tr.prev_x, x)
                if d is not None:
                    if self.direction in ("any", d):
                        if tr.cross_t is None:  # one count per track, ever
                            frac = (self.line_x - tr.prev_x) / (x - tr.prev_x)
                            tr.cross_t = tr.prev_t + frac * (t - tr.prev_t)
                            tr.cross_frame = frame_idx
                            crossed_now.append(tid)
                    else:
                        self.opposite_crossings += 1
            tr.prev_x, tr.prev_t = x, t
        return crossed_now


def decide_class(tr: TrackState, min_share: float, min_conf: float, min_votes: int):
    """Confidence-weighted vote. Returns (class_id | None, share, mean_conf, reasons)."""
    if not tr.votes:
        return None, 0.0, 0.0, ["no usable detections near the line"]
    total = sum(tr.votes.values())
    cls, w = max(tr.votes.items(), key=lambda kv: kv[1])
    share = w / total
    mean_conf = tr.conf_sum / tr.n_votes
    reasons = []
    if share < min_share:
        reasons.append(f"class vote split ({share:.0%} for winner)")
    if mean_conf < min_conf:
        reasons.append(f"low mean confidence ({mean_conf:.2f})")
    if tr.n_votes < min_votes:
        reasons.append(f"seen in only {tr.n_votes} frames near the line")
    return cls, share, mean_conf, reasons


def _issue(kind: str, severity: str, t, detail: str) -> dict:
    return {"type": kind, "severity": severity, "t": None if t is None else round(t, 2), "detail": detail}


def analyze_timing(times, n_expected, t_start, t_stop, tol, edge_offset, pace_tol):
    """Checks that crossings are evenly spaced and sit where the start/stop log says."""
    issues = []
    n = len(times)
    pace = (t_stop - t_start) / n_expected  # seconds per spot implied by the bot's log
    delta = pace
    if n >= 2:
        d = statistics.median([b - a for a, b in zip(times, times[1:])])
        if d > 0:
            delta = d  # observed typical spacing (robust to a few bad events)

    if abs(delta - pace) > pace_tol * pace:
        issues.append(_issue(
            "pace_mismatch", "note", None,
            f"typical spacing {delta:.2f}s vs {pace:.2f}s implied by start/stop log and expected total "
            f"(speed not steady, log misaligned, or acceleration at the ends)"))

    for i, (a, b) in enumerate(zip(times, times[1:]), start=1):
        r = (b - a) / delta
        k = int(r + 0.5)
        mid = (a + b) / 2
        if k == 0:
            issues.append(_issue("possible_duplicate", "flag", mid,
                                 f"objects #{i} and #{i + 1} only {b - a:.2f}s apart ({r:.2f}x normal spacing)"))
        elif k >= 2:
            issues.append(_issue("possible_missed", "flag", mid,
                                 f"{b - a:.2f}s gap ({r:.1f}x normal) between #{i} and #{i + 1}: "
                                 f"about {k - 1} object(s) missed"))
        elif abs(r - 1) > tol:
            issues.append(_issue("irregular_spacing", "note", mid,
                                 f"spacing between #{i} and #{i + 1} is {r:.2f}x normal (off-center car or speed change)"))

    lead = tail = None
    if n:
        lead, tail = times[0] - t_start, t_stop - times[-1]
        for label, val in (("start", lead), ("end", tail)):
            if abs(val - edge_offset * delta) > tol * delta:
                issues.append(_issue(
                    f"edge_{label}", "flag", times[0] if label == "start" else times[-1],
                    f"first/last crossing is {val:.2f}s from the {label} of the strip "
                    f"(expected about {edge_offset * delta:.2f}s): an object at the {label} may be "
                    f"missed/extra, or the logged {label} time is misaligned"))
    stats = {"pace_from_log_s": round(pace, 3), "median_gap_s": round(delta, 3),
             "lead_s": None if lead is None else round(lead, 3),
             "tail_s": None if tail is None else round(tail, 3)}
    return issues, stats


def build_report(counter: LineCounter, a) -> dict:
    pace = (a.stop - a.start) / a.expected_total
    lo, hi = a.start - a.edge_margin * pace, a.stop + a.edge_margin * pace

    crossed = [tr for tr in counter.tracks.values() if tr.cross_t is not None]
    inside = sorted((tr for tr in crossed if lo <= tr.cross_t <= hi), key=lambda tr: tr.cross_t)
    outside = len(crossed) - len(inside)

    events, issues = [], []
    n_occ = n_free = n_unknown = 0
    for i, tr in enumerate(inside, start=1):
        cls, share, mean_conf, reasons = decide_class(tr, a.min_vote_share, a.min_conf, a.min_votes)
        if cls == a.occupied_id:
            n_occ += 1
            label = "occupied_spot"
        elif cls == a.empty_id:
            n_free += 1
            label = "empty_spot"
        else:
            n_unknown += 1
            label = "unknown"
        if reasons:
            issues.append(_issue("uncertain_class", "flag", tr.cross_t, f"object #{i} ({label}): " + "; ".join(reasons)))
        events.append({"index": i, "track_id": tr.track_id, "t": round(tr.cross_t, 3), "frame": tr.cross_frame,
                       "class": label, "vote_share": round(share, 3), "mean_conf": round(mean_conf, 3),
                       "frames_voting": tr.n_votes, "uncertain": bool(reasons)})

    n = len(inside)
    if n != a.expected_total:
        issues.append(_issue("count_mismatch", "flag", None,
                             f"counted {n} objects but the strip has {a.expected_total}"))
        if n == 0 and counter.opposite_crossings:
            issues.append(_issue("direction_hint", "note", None,
                                 f"0 crossings counted but {counter.opposite_crossings} in the opposite "
                                 f"direction: try --direction {'right' if a.direction == 'left' else 'left'}"))
    if outside:
        issues.append(_issue("outside_window", "note", None,
                             f"{outside} crossing(s) happened outside the strip's start/stop window and were ignored"))

    timing_issues, stats = analyze_timing([e["t"] for e in events], a.expected_total, a.start, a.stop,
                                          a.tol, a.edge_offset, a.pace_tol)
    issues += timing_issues
    flagged = any(x["severity"] == "flag" for x in issues)
    return {"window": {"start": a.start, "stop": a.stop}, "expected_total": a.expected_total,
            "counts": {"events": n, "occupied": n_occ, "free": n_free, "unknown": n_unknown},
            "timing": stats, "flagged": flagged, "issues": issues, "events": events}


# --------------------------------------------------------------------------- #
# Video / model side
# --------------------------------------------------------------------------- #
def parse_time(s: str) -> float:
    """'90', '1:30' or '1:02:03' -> seconds."""
    secs = 0.0
    for part in str(s).split(":"):
        secs = secs * 60 + float(part)
    return secs


def _frame_time(cap, idx, fps, last_t):
    ms = cap.get(cv2.CAP_PROP_POS_MSEC)
    t = ms / 1000.0 if ms and ms > 0 else idx / fps
    if last_t is not None and t <= last_t:  # timestamps not increasing -> fall back
        t = last_t + 1.0 / fps
    return t


def run_video(a, counter: LineCounter) -> list[list]:
    if cv2 is None:
        sys.exit("opencv is required to read video: pip install opencv-python")
    from ultralytics import YOLO

    model = YOLO(a.weights)
    names = {int(k): v for k, v in model.names.items()}
    if names.get(a.empty_id) != "empty_spot" or names.get(a.occupied_id) != "occupied_spot":
        print(f"WARNING: model class names are {names}; check --empty-id / --occupied-id", file=sys.stderr)

    cap = cv2.VideoCapture(str(a.video))
    if not cap.isOpened():
        sys.exit(f"cannot open video: {a.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    pace = (a.stop - a.start) / a.expected_total
    pad = a.edge_margin * pace + 2.0  # a little extra before/after so the tracker can warm up
    t_lo, t_hi = a.start - pad, a.stop + pad

    kwargs = dict(persist=True, tracker=a.tracker, conf=a.conf, imgsz=a.imgsz, verbose=False,
                  classes=[a.empty_id, a.occupied_id])
    if a.device:
        kwargs["device"] = a.device

    rows, idx, last_t, n_proc = [], -1, None, 0
    while True:
        if not cap.grab():
            break
        idx += 1
        t = _frame_time(cap, idx, fps, last_t)
        last_t = t
        if t < t_lo:
            continue
        if t > t_hi:
            break
        ok, frame = cap.retrieve()
        if not ok:
            continue

        res = model.track(frame, **kwargs)[0]
        n_proc += 1
        if n_proc % 200 == 0:
            n_evt = sum(1 for x in counter.tracks.values() if x.cross_t is not None)
            print(f"  t={t:7.1f}s  frames processed={n_proc}  crossings so far={n_evt}", flush=True)
        boxes = res.boxes
        if boxes is None or boxes.id is None:
            continue
        ids = boxes.id.int().cpu().tolist()
        cls = boxes.cls.int().cpu().tolist()
        conf = boxes.conf.cpu().tolist()
        xywhn = boxes.xywhn.cpu().tolist()

        dets = [(i, c, p, b[0]) for i, c, p, b in zip(ids, cls, conf, xywhn)]
        rows += [[round(t, 4), idx, i, c, round(p, 4), *[round(v, 5) for v in b]]
                 for i, c, p, b in zip(ids, cls, conf, xywhn)]

        crossed = counter.update(t, idx, dets)
        if crossed and not a.no_snapshots:
            img = res.plot()
            h, w = img.shape[:2]
            x = int(a.line_x * w)
            cv2.line(img, (x, 0), (x, h), (0, 255, 255), 2)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                for tid in crossed:
                    counter.tracks[tid].snapshot = buf.tobytes()
    cap.release()
    return rows


def replay_observations(path: str, counter: LineCounter):
    """Feed a saved observations.csv through the counter (no model, no video)."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        cur_frame, cur_t, batch = None, None, []
        for r in reader:
            fr = int(r["frame"])
            if fr != cur_frame and batch:
                counter.update(cur_t, cur_frame, batch)
                batch = []
            cur_frame, cur_t = fr, float(r["t"])
            batch.append((int(r["track_id"]), int(r["cls"]), float(r["conf"]), float(r["x"])))
        if batch:
            counter.update(cur_t, cur_frame, batch)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def save_outputs(out: Path, a, counter: LineCounter, report: dict, obs_rows: list[list]):
    out.mkdir(parents=True, exist_ok=True)
    report = {"video": str(a.video) if a.video else None, "weights": a.weights,
              "settings": {k: v for k, v in vars(a).items() if k not in ("video", "weights")}, **report}
    (out / "report.json").write_text(json.dumps(report, indent=2))

    with open(out / "events.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report["events"][0].keys()) if report["events"] else ["index"])
        w.writeheader()
        w.writerows(report["events"])

    if obs_rows:
        with open(out / "observations.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "frame", "track_id", "cls", "conf", "x", "y", "w", "h"])
            w.writerows(obs_rows)

    if not a.no_snapshots and not a.from_observations:
        ev_dir = out / "events"
        ev_dir.mkdir(exist_ok=True)
        for old in ev_dir.glob("*.jpg"):
            old.unlink()
        by_track = {tr.track_id: tr for tr in counter.tracks.values()}
        for e in report["events"]:
            tr = by_track[e["track_id"]]
            if tr.snapshot:
                name = f"spot_{e['index']:02d}_{e['class']}_t{e['t']:.1f}s_id{e['track_id']}.jpg"
                (ev_dir / name).write_bytes(tr.snapshot)
    return report


def print_summary(report: dict, out: Path):
    c, t = report["counts"], report["timing"]
    print()
    print(f"Strip window: {report['window']['start']:.1f}s -> {report['window']['stop']:.1f}s")
    print(f"Counted {c['events']} objects (expected {report['expected_total']}):  "
          f"occupied={c['occupied']}  free={c['free']}  unknown={c['unknown']}")
    print(f"Spacing: median {t['median_gap_s']}s (log implies {t['pace_from_log_s']}s)   "
          f"lead={t['lead_s']}s  tail={t['tail_s']}s   <- use lead/tail to calibrate --edge-offset")
    if report["issues"]:
        print("\nIssues:")
        for x in report["issues"]:
            when = f" @ {x['t']}s" if x["t"] is not None else ""
            print(f"  [{x['severity']:4}] {x['type']}{when}: {x['detail']}")
    print()
    print("STATUS:", "FLAGGED FOR HUMAN REVIEW" if report["flagged"] else "OK - all checks passed")
    print(f"Details: {out}/report.json")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_argument_group("input")
    src.add_argument("--video", help="recorded pass (saved stream)")
    src.add_argument("--weights", help="trained detector, e.g. runs/detect/strip_counter/weights/best.pt")
    src.add_argument("--from-observations", help="re-run counting on a saved observations.csv (no model/video)")

    strip = p.add_argument_group("strip")
    strip.add_argument("--start", type=parse_time, required=True, help="strip start in video time (sec or [H:]MM:SS)")
    strip.add_argument("--stop", type=parse_time, required=True, help="strip stop in video time")
    strip.add_argument("--expected-total", type=int, required=True, help="number of spots on the strip")
    strip.add_argument("--line-x", type=float, default=0.5, help="counting line, 0=left edge 1=right edge")
    strip.add_argument("--direction", choices=["left", "right", "any"], default="left",
                       help="direction objects move across the image (left = right-to-left)")
    strip.add_argument("--empty-id", type=int, default=0)
    strip.add_argument("--occupied-id", type=int, default=1)

    det = p.add_argument_group("detector / tracker")
    det.add_argument("--conf", type=float, default=0.1, help="low on purpose: weak frames keep tracks alive")
    det.add_argument("--imgsz", type=int, default=960)
    det.add_argument("--device", default=None)
    det.add_argument("--tracker", default="botsort.yaml")

    chk = p.add_argument_group("checks")
    chk.add_argument("--tol", type=float, default=0.35, help="spacing tolerance, fraction of normal spacing")
    chk.add_argument("--edge-offset", type=float, default=0.5,
                     help="expected first/last crossing distance from start/stop, in spacings")
    chk.add_argument("--edge-margin", type=float, default=0.75,
                     help="crossings this many spacings outside start/stop are still considered")
    chk.add_argument("--pace-tol", type=float, default=0.15)
    chk.add_argument("--vote-band", type=float, default=0.35, help="only frames this close to the line vote on class")
    chk.add_argument("--min-vote-share", type=float, default=0.7)
    chk.add_argument("--min-conf", type=float, default=0.45)
    chk.add_argument("--min-votes", type=int, default=5)

    p.add_argument("--out", default=None, help="output folder (default runs/count/<video name>)")
    p.add_argument("--no-snapshots", action="store_true")
    a = p.parse_args()

    if a.from_observations is None and not (a.video and a.weights):
        p.error("give --video and --weights, or --from-observations")
    if a.stop <= a.start:
        p.error("--stop must be after --start")
    if a.expected_total < 1:
        p.error("--expected-total must be >= 1")
    return a


def main():
    a = parse_args()
    stem = Path(a.video).stem if a.video else Path(a.from_observations).parent.name
    out = Path(a.out) if a.out else Path("runs/count") / stem

    counter = LineCounter(a.line_x, a.direction, a.vote_band)
    if a.from_observations:
        replay_observations(a.from_observations, counter)
        obs_rows = []
    else:
        print(f"Processing {a.video} ({a.start:.1f}s -> {a.stop:.1f}s) ...")
        obs_rows = run_video(a, counter)

    report = build_report(counter, a)
    report = save_outputs(out, a, counter, report, obs_rows)
    print_summary(report, out)
    sys.exit(2 if report["flagged"] else 0)


if __name__ == "__main__":
    main()