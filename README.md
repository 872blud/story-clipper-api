# Story Clipper API

Download a YouTube story video, parse English captions, ask OpenAI to choose short-form highlights, and cut both highlight clips and full story parts with ffmpeg.

## Requirements

- Python 3.11+
- `ffmpeg`
- `yt-dlp`
- Chrome cookies available for `yt-dlp --cookies-from-browser chrome`
- `OPENAI_API_KEY` set in your environment

Install Python dependencies:

```bash
python3.11 -m pip install -r requirements.txt
```

Run:

```bash
python3.11 story_clipper_api.py "YOUTUBE_URL" 6
```

Outputs are written under `~/story_clipper_v2/runs/`.
