# YouTube Music Search + mpv

## Overview
CLI tool that searches YouTube Music, presents results in fzf with thumbnail previews, and plays selected items via mpv.

## File Structure
- [yts-music.py](file:///home/rtx/prjs/vibes/youtube_music_search/yts-music.py) — Main entry point, CLI argument parser, and outer search loop.
- [yts_api.py](file:///home/rtx/prjs/vibes/youtube_music_search/yts_api.py) — Core API queries (search, page browsing, playlist fetching) and metadata parsing logic.
- [yts_player.py](file:///home/rtx/prjs/vibes/youtube_music_search/yts_player.py) — Foreground sub-menu implementation, mpv playback launching, and thumbnail caching.
- [fzf-preview.sh](file:///home/rtx/prjs/vibes/youtube_music_search/fzf-preview.sh) — Advanced file preview script for fzf thumbnails and media details.

## Data Flow
1. `search()` in `yts_api.py` returns parsed dictionary results from the search endpoints.
2. `format_line()` in `yts_player.py` formats these dictionaries into tab-separated lines: `{fp}\t{url}\t{thumb}\t{display}\t{id}\t{rtype}`
   - `rtype` is always lowercase: `"song"`, `"video"`, `"album"`, `"playlist"`, `"podcast"`, `"artist"`, etc.
3. Lines are fed to fzf's stdin.
4. fzf uses `--with-nth 4` to display only the formatted title and metadata (field 4).
5. `{+2}` expands to the item URL (field 2), and `{+6}` expands to the item rtype (field 6).

## CLI Features

### Autoplay Mode
- **`-a` or `--auto`**: Performs a search for the query, finds the top result, and plays it immediately in the foreground using `mpv` (without opening `fzf`). If the top result is an artist channel, it fetches their tracks and plays the first one.

### Key Bindings (Outer FZF)
- **Enter**: Launches python in the foreground:
  - If the selected item is a song, video, or playlist, it starts playback immediately. If `mpv` is already running, it replaces the current track/queue and starts playing. For single songs or videos, **Enter** automatically appends the official YouTube Music Radio/Recommendations playlist (e.g. `&list=RDAMVM{videoId}`) to play recommended tracks indefinitely.
  - If the selected item is an **artist**, python stays in the foreground, fetches their page and tracks, and launches a nested `fzf` sub-menu.
- **ctrl-q**: Queues the selected track(s) to the playing background `mpv` player queue using UNIX domain sockets IPC without interrupting active music. Shows a desktop notification containing the album art.
- **alt-v**: Force video mode. Plays the selected item(s) in background with the video window enabled regardless of its type.
- **alt-s**: Re-search. Exits fzf and loops back to the search prompt.
- **Esc**: Exit fzf. Loops back to the search prompt.
- **Ctrl-C**: Kill script entirely.

### Interactive Artist Sub-menu
When an artist/channel is selected, the tool queries `/youtubei/v1/browse`. It extracts the artist's "Top songs" playlist ID (typically starting with `VLOLAK5uy_...`) and fetches up to 100+ tracks. These tracks are displayed in a nested `fzf` menu in the terminal.
- **Enter (in sub-menu)**: Plays the selected track(s) immediately (clearing the old queue) and keeps the sub-menu open so you can queue more tracks.
- **ctrl-q (in sub-menu)**: Queues the selected track(s) to the playing player queue in the background.
- **Esc / alt-s (in sub-menu)**: Closes the sub-menu and returns to the parent search results.

### Video Auto-Detection
- Items with `rtype = "video"` play with the video window visible (`mpv {URL}`).
- All other items play audio-only with the video window hidden (`mpv --no-video {URL}`).

### `--all` Mode
- Shows all result categories: Songs, Albums, Playlists, Videos, Podcasts, Top result, and Artists.
- Categories are displayed in dim text at the end of each line (e.g. ` · Artists`).

## Test Commands
```bash
# Test with --all to see video and artist items
python3 yts-music.py --all "radiohead"

# Test songs-only mode
python3 yts-music.py "thom yorke"

# Test with initial query
python3 yts-music.py "beatles"

# Test autoplay mode (plays cardigan by Taylor Swift in foreground)
python3 yts-music.py -a "taylor swift cardigan"

# Syntax check all modules
python3 -c "import py_compile; py_compile.compile('yts_api.py', doraise=True); py_compile.compile('yts_player.py', doraise=True); py_compile.compile('yts-music.py', doraise=True)"
```
