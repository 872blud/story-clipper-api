# story clipper api

this is a small python script for chopping long minecraft / roblox style story videos into shorter clips.

it downloads a youtube video, grabs the captions, picks moments that look like actual tiktok clips, then cuts both highlight clips and full story parts with ffmpeg.

the goal is not to make a giant editing app. it is just the boring pipeline i kept needing: download, read captions, find the good parts, cut the files, put everything in a folder.

## what it does

- downloads the video and english captions with `yt-dlp`
- parses `.vtt` captions into timestamped transcript lines
- scores the transcript to pick the strongest clip moments
- snaps clip starts and ends to nearby caption boundaries
- cuts highlight clips between 20 and 60 seconds
- splits the full story into however many parts you ask for
- saves the transcript, metadata, highlights, and story parts in one run folder

## requirements

- python 3.11+
- `ffmpeg`
- `yt-dlp`
- chrome cookies available for `yt-dlp --cookies-from-browser chrome`
## running it

there are no python package dependencies right now. run it like this:


```bash
python3.11 story_clipper_api.py "YOUTUBE_URL" 6
```

the number at the end is how many story parts you want. it will always use at least 3.

outputs go here:

```text
~/story_clipper_v2/runs/
```

## status

this is a working utility script, not a polished app. it assumes you have `yt-dlp`, `ffmpeg`, and browser cookies set up already.
