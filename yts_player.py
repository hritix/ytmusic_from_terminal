import os
import sys
import time
import subprocess
import threading
import socket
import json
import re
from urllib import request
import yts_api

PREVIEW_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fzf-preview.sh")

FZF_ARGS = [
    "-m", "--ansi",
    "--delimiter", "\t", "--with-nth", "4",
    "--preview", PREVIEW_SH + " {1}",
    "--preview-window", "right:35%:border-sharp",
    "--color=fg:#cecece,bg:#0e1415,hl:#f4bf75",
    "--color=fg+:#ffffff,bg+:#1f2526,hl+:#f4bf75",
    "--color=info:#b4d273,prompt:#7392b2,pointer:#7392b2",
    "--color=marker:#b4d273,spinner:#7392b2,header:#b4d273",
    "--color=border:#7392b2,label:#cecece,query:#ffffff",
    "--layout=reverse", "--border=none",
    "--prompt=> ", "--pointer=┃ ", "--marker=+",
    "--info=default", "--padding=0,1",
    "--bind", "ctrl-/:toggle-preview",
]


def dl_thumb(url: str, fp: str):
    if not url or os.path.exists(fp):
        return
    try:
        req = request.Request(url, headers={"User-Agent": yts_api.UA})
        with request.urlopen(req, timeout=5) as r:
            with open(fp, "wb") as f:
                f.write(r.read())
    except Exception:
        pass


def format_line(item: dict) -> str:
    vid = item["id"]
    playlist_id = item["playlist_id"] or (vid if item["rtype"] == "playlist" or vid.startswith("VL") else "")
    if playlist_id:
        if playlist_id.startswith("VL"):
            playlist_id = playlist_id[2:]
        url = f"https://music.youtube.com/playlist?list={playlist_id}"
    elif item["rtype"] == "artist":
        url = f"https://music.youtube.com/channel/{vid}"
    else:
        url = f"https://www.youtube.com/watch?v={vid}"
    fp = os.path.join(yts_api.THUMBS, f"{vid}.jpg")
    parts = []
    for field in ("artist", "album", "duration", "year", "plays"):
        val = item.get(field)
        if val:
            parts.append(val)
    label = item.get("section") or yts_api.CAT_MAP.get(item["rtype"], "")
    if label:
        parts.append(label)
    meta = " · ".join(parts)
    display = item["title"]
    if meta:
        display += f" \x1b[2m{meta}\x1b[0m"
    thumb = item.get("thumb", "")
    return f"{fp}\t{url}\t{thumb}\t{display}\t{item['id']}\t{item['rtype']}"


def get_socket_path() -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, "yts-music.sock")
    return f"/tmp/yts-music-{os.getuid()}.sock"


def is_mpv_running() -> bool:
    sock_path = get_socket_path()
    if not os.path.exists(sock_path):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.1)
        s.connect(sock_path)
        s.close()
        return True
    except Exception:
        try:
            os.remove(sock_path)
        except OSError:
            pass
        return False


def send_mpv_command(cmd: list) -> bool:
    sock_path = get_socket_path()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(sock_path)
        payload = json.dumps({"command": cmd}) + "\n"
        s.sendall(payload.encode())
        s.close()
        return True
    except Exception:
        return False
def send_mpv_query(cmd: list) -> any:
    sock_path = get_socket_path()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(sock_path)
        payload = json.dumps({"command": cmd}) + "\n"
        s.sendall(payload.encode())
        
        resp_data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp_data += chunk
            while b"\n" in resp_data:
                line, resp_data = resp_data.split(b"\n", 1)
                if line:
                    try:
                        msg = json.loads(line.decode(errors="replace"))
                        if isinstance(msg, dict) and "error" in msg:
                            s.close()
                            return msg.get("data")
                    except Exception:
                        pass
        s.close()
    except Exception:
        pass
    return None


def move_queued_track_after_resolve(queued_url: str):
    sock_path = get_socket_path()
    for _ in range(60):
        time.sleep(0.5)
        if not is_mpv_running():
            break
        playlist = send_mpv_query(["get_property", "playlist"])
        if not playlist:
            continue
            
        if len(playlist) > 2:
            found_idx = -1
            for idx, item in enumerate(playlist):
                filename = item.get("filename", "")
                if queued_url in filename or (queued_url and filename and queued_url.split("v=")[-1] in filename):
                    found_idx = idx
                    break
                    
            if found_idx == -1:
                break
                
            current_idx = None
            for idx, item in enumerate(playlist):
                if item.get("current"):
                    current_idx = idx
                    break
            if current_idx is None:
                current_idx = 0
                
            target_idx = len(playlist)
            for idx in range(current_idx + 1, len(playlist)):
                item = playlist[idx]
                path = item.get("playlist-path") or item.get("filename") or ""
                if "list=RD" in path or "list=UL" in path:
                    target_idx = idx
                    break
            
            if found_idx > target_idx:
                send_mpv_command(["playlist-move", found_idx, target_idx])
            break


def show_notification(status: str, title_str: str, thumb_path: str):
    parts = [p.strip() for p in title_str.split(" · ")]
    title = parts[0] if parts else "Unknown Track"
    artist = parts[1] if len(parts) > 1 else ""
    msg = title
    if artist:
        msg += f"\n{artist}"
    cmd = ["notify-send", "-t", "3000"]
    if thumb_path and os.path.exists(thumb_path):
        cmd.extend(["-i", thumb_path])
    cmd.extend([status, msg])
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def play_handler(play_urls: list[str], rtypes: list[str], force_video: bool = False, queue: bool = False, titles: list[str] = None, thumbs: list[str] = None):
    # Check if there are any artists in rtypes
    artist_url = ""
    if rtypes:
        for url, rt in zip(play_urls, rtypes):
            if rt.strip().lower() == "artist":
                artist_url = url
                break

    if artist_url:
        cfg = yts_api.load_config()
        if cfg:
            api_key = cfg["api_key"]
            client_ver = cfg["client_ver"]
            browse_id = artist_url.split("/")[-1].strip()
            show_artist_menu(browse_id, api_key, client_ver)
        else:
            print("Error: API config not loaded. Perform a search first to initialize config.", file=sys.stderr)
            time.sleep(2)
        return

    sock_path = get_socket_path()
    mpv_active = is_mpv_running()

    # Append recommendations list (RDAMVM) only for single play (non-queue) song/video items
    processed_urls = []
    for url, rt in zip(play_urls, rtypes or []):
        if not queue and len(play_urls) == 1 and rt in ("song", "video") and "list=" not in url:
            m = re.search(r"[?&]v=([^&]+)", url)
            if m:
                vid = m.group(1)
                url = f"{url}&list=RDAMVM{vid}"
        processed_urls.append(url)

    if queue:
        if mpv_active:
            pl = send_mpv_query(["get_property", "playlist-count"]) or 0
            cur = send_mpv_query(["get_property", "playlist-pos"]) or 0
            for i, url in enumerate(processed_urls):
                send_mpv_command(["loadfile", url, "append"])
                new_idx = pl + i
                target = cur + 1 + i
                if new_idx > target:
                    send_mpv_command(["playlist-move", new_idx, target])
            if titles and thumbs:
                show_notification("Queued", titles[0], thumbs[0])
            sys.exit(0)
        else:
            has_video = force_video or (rtypes and any(rt.strip().lower() == "video" for rt in rtypes))
            cmd = ["mpv", f"--input-ipc-server={sock_path}"]
            if not has_video:
                cmd.append("--no-video")
            subprocess.Popen(["setsid", "-f", *cmd, *processed_urls], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if titles and thumbs:
                show_notification("Playing", titles[0], thumbs[0])
            sys.exit(0)
    else:
        if mpv_active:
            send_mpv_command(["loadfile", processed_urls[0], "replace"])
            for url in processed_urls[1:]:
                send_mpv_command(["loadfile", url, "append"])
            if titles and thumbs:
                show_notification("Playing", titles[0], thumbs[0])
            sys.exit(0)
        else:
            has_video = force_video or (rtypes and any(rt.strip().lower() == "video" for rt in rtypes))
            cmd = ["mpv", f"--input-ipc-server={sock_path}"]
            if not has_video:
                cmd.append("--no-video")
            subprocess.Popen(["setsid", "-f", *cmd, *processed_urls], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if titles and thumbs:
                show_notification("Playing", titles[0], thumbs[0])
            sys.exit(0)


def show_artist_menu(browse_id: str, api_key: str, client_ver: str):
    ctx = {
        "client": {
            "hl": "en", "gl": "US",
            "clientName": "WEB_REMIX",
            "clientVersion": client_ver,
        }
    }

    python_bin = sys.executable
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yts-music.py")

    nested_fzf_args = [
        *FZF_ARGS,
        "--bind", f"enter:execute-silent(setsid -f {python_bin} {script_path} --play {{+2}} --rtypes {{+6}} --titles {{+4}} --thumbs {{+1}} >/dev/null 2>&1)",
        "--bind", f"ctrl-q:execute-silent(setsid -f {python_bin} {script_path} --play {{+2}} --rtypes {{+6}} --titles {{+4}} --thumbs {{+1}} --queue >/dev/null 2>&1)",
        "--bind", f"alt-v:execute-silent(setsid -f {python_bin} {script_path} --play {{+2}} --force-video >/dev/null 2>&1)",
        "--bind", "alt-s:abort",
    ]

    fzf = subprocess.Popen(["fzf", *nested_fzf_args],
                           stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,
                           stderr=sys.stderr)

    def feed():
        try:
            songs = yts_api.fetch_artist_songs(browse_id, api_key, client_ver, ctx)
            if not songs:
                return

            count = 0
            for s in songs:
                count += 1
                line = format_line(s)
                parts = line.split("\t")
                fp = parts[0]
                thumb_url = parts[2]
                if count == 1:
                    dl_thumb(thumb_url, fp)
                elif not os.path.exists(fp):
                    threading.Thread(target=dl_thumb, args=(thumb_url, fp), daemon=True).start()
                try:
                    fzf.stdin.write((line + "\n").encode())
                    fzf.stdin.flush()
                except BrokenPipeError:
                    break
        except Exception:
            pass
        finally:
            try:
                fzf.stdin.close()
            except OSError:
                pass

    t = threading.Thread(target=feed, daemon=True)
    t.start()

    try:
        fzf.wait()
    except KeyboardInterrupt:
        fzf.terminate()


def play_foreground(item: dict, force_video: bool = False):
    vid = item["id"]
    playlist_id = item["playlist_id"] or (vid if item["rtype"] == "playlist" or vid.startswith("VL") else "")
    if playlist_id:
        if playlist_id.startswith("VL"):
            playlist_id = playlist_id[2:]
        url = f"https://music.youtube.com/playlist?list={playlist_id}"
    elif item["rtype"] == "artist":
        url = f"https://music.youtube.com/channel/{vid}"
    else:
        url = f"https://www.youtube.com/watch?v={vid}"

    if item["rtype"] == "artist":
        print(f"Top result is artist: {item['title']}. Fetching tracks...", flush=True)
        cfg = yts_api.load_config()
        if cfg:
            api_key = cfg["api_key"]
            client_ver = cfg["client_ver"]
            ctx = {
                "client": {
                    "hl": "en", "gl": "US",
                    "clientName": "WEB_REMIX",
                    "clientVersion": client_ver,
                }
            }
            songs = yts_api.fetch_artist_songs(vid, api_key, client_ver, ctx)
            if songs:
                top_song = songs[0]
                print(f"Playing top track for {item['title']}: {top_song['title']} · {top_song['artist']}", flush=True)
                play_foreground(top_song, force_video)
                return
        print("No tracks found for artist.", file=sys.stderr)
        return

    meta_parts = []
    for f in ("artist", "album", "duration"):
        v = item.get(f)
        if v:
            meta_parts.append(v)
    meta = f" · {', '.join(meta_parts)}" if meta_parts else ""
    print(f"Playing: {item['title']}{meta}", flush=True)

    has_video = force_video or item["rtype"] == "video"
    cmd = ["mpv"]
    if not has_video:
        cmd.append("--no-video")
    subprocess.run([*cmd, url])
