Search and play music from music.youtube.com from the terminal using fzf and yt-dlp
## Requirements
* mpv
* yt-dlp


## Overview
- [yts-music.py](file:///home/rtx/prjs/vibes/youtube_music_search/yts-music.py) — Main entry point, CLI argument parser, and outer search loop.
- [yts_api.py](file:///home/rtx/prjs/vibes/youtube_music_search/yts_api.py) — Core API queries (search, page browsing, playlist fetching) and metadata parsing logic.
- [yts_player.py](file:///home/rtx/prjs/vibes/youtube_music_search/yts_player.py) — Foreground sub-menu implementation, mpv playback launching, and thumbnail caching.
- [fzf-preview.sh](file:///home/rtx/prjs/vibes/youtube_music_search/fzf-preview.sh) — Advanced file preview script for fzf thumbnails and media details.

## CLI Features

### Autoplay Mode
- **`-a` or `--auto`**: automatically plays the first result

### `--all` Mode
- Shows all result categories: Songs, Albums, Playlists, Videos, Podcasts, Top result, and Artists.
- Categories are displayed in dim text at the end of each line (e.g. ` · Artists`).

## Usage Examples

```bash
# get help
./yts-music.py -h
# Test with --all to see video and artist items
./yts-music.py --all "radiohead"

# Test autoplay mode (plays cardigan by Taylor Swift in foreground)
./yts-music.py -a "taylor swift cardigan"
