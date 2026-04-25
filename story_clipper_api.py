import json
import re
import subprocess
import sys
import time
from pathlib import Path

# ================ CONFIG ================

TARGET_HEIGHT = 1080
MIN_CLIP_SEC = 20
MAX_CLIP_SEC = 60


# ================ UTILS ================

def run_cmd(cmd, timeout=None, input_text=None):
    p = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        if err:
            print(err)
        raise SystemExit(p.returncode)
    return p.stdout


def safe_name(s):
    s = re.sub(r"[^a-zA-Z0-9_\-]+", "_", s)
    return s.strip("_").lower()[:80]


def ts_to_sec(raw):
    ts = raw.strip().split()[0]
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    return parts[0]


def ts_label(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ================ DOWNLOAD ================

def download_youtube(url, dl_dir):
    dl_dir = Path(dl_dir)
    dl_dir.mkdir(parents=True, exist_ok=True)

    outtmpl = str(dl_dir / "%(title).80s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--cookies-from-browser",
        "chrome",
        "-f",
        f"bestvideo[height={TARGET_HEIGHT}]+bestaudio/best[height={TARGET_HEIGHT}]",
        "--merge-output-format",
        "mp4",
        "--write-auto-subs",
        "--sub-lang",
        "en",
        "--convert-subs",
        "vtt",
        "-o",
        outtmpl,
        url,
    ]

    # show yt-dlp progress
    subprocess.call(cmd)

    mp4s = sorted(dl_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4s:
        raise SystemExit("no mp4 downloaded")

    vtts = sorted(
        list(dl_dir.glob("*.en.vtt")) + list(dl_dir.glob("*.vtt")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not vtts:
        raise SystemExit("no captions (.vtt) downloaded")

    return mp4s[0], vtts[0]


# ================ CAPTION PARSING ================

def parse_vtt(vtt_path):
    text = Path(vtt_path).read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    items = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if "-->" not in line:
            i += 1
            continue

        try:
            left, right = line.split("-->", 1)
            start_sec = ts_to_sec(left)
            end_sec = ts_to_sec(right)
        except Exception:
            i += 1
            continue

        i += 1
        cap_lines = []
        while i < n and lines[i].strip() != "":
            cap_lines.append(lines[i].strip())
            i += 1

        caption = " ".join(cap_lines)
        caption = re.sub(r"<[^>]+>", "", caption)
        caption = re.sub(r"\s+", " ", caption).strip()

        if caption:
            items.append({"start": start_sec, "end": end_sec, "text": caption})

        i += 1

    return items


def build_transcript_text(items, max_chars=50000):
    parts = []
    total = 0
    for it in items:
        label = ts_label(it["start"])
        line = f"[{label}] {it['text']}"
        length = len(line) + 1
        if total + length > max_chars:
            break
        parts.append(line)
        total += length
    return "\n".join(parts)


# ================ HIGHLIGHT PICKING ================

def score_caption(text):
    words = text.lower()
    score = 0

    strong_terms = [
        "no way", "wait", "what", "why", "how", "help", "stop", "run",
        "die", "dead", "kill", "killed", "fight", "betray", "betrayed",
        "secret", "found", "lost", "win", "won", "fail", "failed",
        "trap", "caught", "escape", "escaped", "hide", "hidden", "panic",
        "laugh", "shout", "scream", "clutch", "crazy", "insane",
    ]
    for term in strong_terms:
        if term in words:
            score += 3

    if "!" in text:
        score += 2
    if "?" in text:
        score += 1
    if len(text.split()) >= 12:
        score += 1

    return score


def choose_highlights(items, max_highlights=6):
    if not items:
        return []

    total_dur = items[-1]["end"]
    candidates = []

    for idx, item in enumerate(items):
        window_start = max(0.0, item["start"] - 3.0)
        window_end = min(total_dur, window_start + MAX_CLIP_SEC)
        if window_end - window_start < MIN_CLIP_SEC:
            window_start = max(0.0, window_end - MIN_CLIP_SEC)

        nearby = items[idx: idx + 12]
        score = score_caption(item["text"]) + sum(score_caption(n["text"]) for n in nearby[:4])
        if score <= 0:
            continue

        candidates.append(
            {
                "start": window_start,
                "end": window_end,
                "score": score,
                "reason": "high-energy caption window",
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)

    chosen = []
    for candidate in candidates:
        overlaps = any(
            candidate["start"] < existing["end"] and candidate["end"] > existing["start"]
            for existing in chosen
        )
        if overlaps:
            continue
        chosen.append(candidate)
        if len(chosen) >= max_highlights:
            break

    chosen.sort(key=lambda x: x["start"])
    return [{"start": h["start"], "end": h["end"], "reason": h["reason"]} for h in chosen]


# ================ CLIP BOUNDARIES ================

def snap_to_captions(items, start, end, window=3.0):
    best_start = start
    best_end = end

    for it in items:
        ds = abs(it["start"] - start)
        if ds <= window and ds < abs(best_start - start):
            best_start = it["start"]

        de = abs(it["end"] - end)
        if de <= window and de < abs(best_end - end):
            best_end = it["end"]

    if best_end <= best_start:
        best_end = start + (end - start)

    return best_start, best_end


def build_story_parts(items, num_parts):
    if not items or num_parts <= 1:
        return []
    total = items[-1]["end"]
    target = total / num_parts

    parts = []
    part_start = items[0]["start"]
    next_target = target

    for it in items:
        if it["end"] >= next_target and len(parts) < num_parts - 1:
            part_end = it["end"]
            parts.append((part_start, part_end))
            part_start = part_end
            next_target += target

    parts.append((part_start, total))
    return parts


# ================ FFMPEG CUT ================

def cut_clip(video_path, start, end, out_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        str(start),
        "-to",
        str(end),
        "-i",
        str(video_path),
        "-c",
        "copy",
        str(out_path),
    ]
    run_cmd(cmd)


# ================ MAIN ================

def ensure_unique_dir(base_dir, name):
    base_dir = Path(base_dir)
    candidate = base_dir / name
    idx = 1
    while candidate.exists():
        candidate = base_dir / f"{name}_{idx}"
        idx += 1
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def main():
    if len(sys.argv) < 3:
        print('usage: python3.11 story_clipper_api.py "YOUTUBE_URL" PARTS')
        return

    url = sys.argv[1]
    parts = max(3, int(sys.argv[2]))

    base = Path.home() / "story_clipper_v2"
    runs = base / "runs"
    runs.mkdir(parents=True, exist_ok=True)

    print("[1/6] downloading video and captions...")
    tmp_dir = runs / f"_tmp_dl_{int(time.time())}"
    video_tmp, vtt_tmp = download_youtube(url, tmp_dir)

    title_safe = safe_name(video_tmp.stem or "story_video")
    job_dir = ensure_unique_dir(runs, title_safe)

    video = job_dir / "video.mp4"
    vtt = job_dir / "captions.vtt"
    video_tmp.rename(video)
    vtt_tmp.rename(vtt)

    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    print("[2/6] parsing captions...")
    items = parse_vtt(vtt)
    if not items:
        raise SystemExit("empty captions after parsing; open captions.vtt and check format")
    print(f"    parsed {len(items)} caption segments")

    print("[3/6] building transcript...")
    transcript_txt = build_transcript_text(items)
    (job_dir / "transcript.txt").write_text(transcript_txt, encoding="utf-8")
    print(f"    transcript length: {len(transcript_txt)} characters")

    print("[4/6] choosing highlights...")
    highlights = choose_highlights(items, max_highlights=min(8, parts))
    if not highlights:
        print("    no highlights found, continuing with story parts only")
    else:
        print(f"    picked {len(highlights)} highlight segments")

    snapped_highlights = []
    for h in highlights:
        s, e = snap_to_captions(items, h["start"], h["end"])
        snapped_highlights.append({"start": s, "end": e, "reason": h["reason"]})
    highlights = snapped_highlights

    print("[5/6] building story parts...")
    story_parts = build_story_parts(items, parts)
    print(f"    story split into {len(story_parts)} parts")

    hi_dir = job_dir / "highlights"
    st_dir = job_dir / "story_parts"
    hi_dir.mkdir(exist_ok=True)
    st_dir.mkdir(exist_ok=True)

    if highlights:
        print("[6/6] cutting highlight clips...")
        total_h = len(highlights)
        for i, h in enumerate(highlights, 1):
            bar_len = 20
            filled = int(bar_len * i / total_h)
            bar = "#" * filled + "-" * (bar_len - filled)
            print(f"    highlights [{bar}] {i}/{total_h}", end="\r", flush=True)
            out_path = hi_dir / f"{title_safe}_highlight_{i:02d}.mp4"
            cut_clip(video, h["start"], h["end"], out_path)
        print()
    else:
        print("[6/6] skipping highlights, none to cut")

    print("    cutting story parts...")
    total_s = len(story_parts)
    for j, (s, e) in enumerate(story_parts, 1):
        bar_len = 20
        filled = int(bar_len * j / total_s)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"    story     [{bar}] {j}/{total_s}", end="\r", flush=True)
        out_path = st_dir / f"{title_safe}_story_{j:02d}.mp4"
        cut_clip(video, s, e, out_path)
    print()

    meta = {
        "url": url,
        "title": title_safe,
        "video": str(video.name),
        "captions": str(vtt.name),
        "highlights": highlights,
        "story_parts": [{"start": s, "end": e} for (s, e) in story_parts],
    }
    (job_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("\nall done.")
    print("output folder:", job_dir)
    print("  highlights:", hi_dir)
    print("  story parts:", st_dir)


if __name__ == "__main__":
    main()
