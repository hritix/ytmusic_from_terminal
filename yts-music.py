#!/usr/bin/env python3
import argparse
import os
import sys
import threading
import time
import subprocess
import yts_api
import yts_player

def main():
    parser = argparse.ArgumentParser(description="YouTube Music search + mpv")
    parser.add_argument("query", nargs="*", help="search query")
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch API config instead of using cache")
    parser.add_argument("-c", "--center", action="store_true",
                        help="center prompt in terminal")
    parser.add_argument("--all", action="store_true",
                        help="show all result types (not just songs)")
    parser.add_argument("--play", nargs="+", help="play URLs in mpv")
    parser.add_argument("--rtypes", nargs="+", help="corresponding rtypes for the URLs")
    parser.add_argument("--force-video", action="store_true", help="force video mode")
    parser.add_argument("-a", "--auto", action="store_true",
                        help="automatically play the top result without launching fzf")
    parser.add_argument("--titles", nargs="+", help="corresponding titles for the URLs")
    parser.add_argument("--thumbs", nargs="+", help="corresponding thumbnail file paths")
    parser.add_argument("--queue", action="store_true", help="queue songs instead of replacing")
    args = parser.parse_args()

    # Play mode handler (execute/execute-silent triggers this)
    if args.play:
        yts_player.play_handler(
            args.play,
            args.rtypes,
            force_video=args.force_video,
            queue=args.queue,
            titles=args.titles,
            thumbs=args.thumbs
        )
        return

    # Autoplay top result mode
    if args.auto:
        query = " ".join(args.query).strip() if args.query else ""
        if not query:
            print("Error: search query is required when using --auto.", file=sys.stderr)
            sys.exit(1)
        limit = yts_api.LIMIT_ALL if args.all else yts_api.LIMIT
        results = list(yts_api.search(query, refresh=args.refresh, filter_songs=not args.all, limit=limit))
        if not results:
            print("No results found.", file=sys.stderr)
            sys.exit(1)
        yts_player.play_foreground(results[0], force_video=args.force_video)
        return

    # Ensure thumbnail cache directory exists
    os.makedirs(yts_api.THUMBS, exist_ok=True)

    first = True
    while True:
        query = ""
        if first:
            query = " ".join(args.query) if args.query else ""
            first = False
        if not query:
            try:
                prompt = "\x1b[38;2;115;146;178m┃ YouTube Music \x1b[0m"
                if args.center:
                    import shutil
                    w, h = shutil.get_terminal_size()
                    x, y = w // 4, h // 2
                    print(f"\x1b[2J\x1b[{y};{x}H{prompt}", end="", flush=True)
                    query = input().strip()
                else:
                    query = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                return
        if not query:
            return

        python_bin = sys.executable
        script_path = os.path.abspath(sys.argv[0])

        # Enter uses execute (foreground) to allow sub-menus for artists,
        # and standard background playback (which exits immediately) for songs.
        # while right arrow and ctrl-o suspend fzf to load the artist sub-menu.
        fzf_args = [
            *yts_player.FZF_ARGS,
            "--bind", f"enter:execute({python_bin} {script_path} --play {{+2}} --rtypes {{+6}} --titles {{+4}} --thumbs {{+1}})",
            "--bind", f"ctrl-q:execute-silent({python_bin} {script_path} --play {{+2}} --rtypes {{+6}} --titles {{+4}} --thumbs {{+1}} --queue)",
            "--bind", f"alt-v:execute-silent(setsid -f {python_bin} {script_path} --play {{+2}} --force-video >/dev/null 2>&1)",
            "--bind", "alt-s:abort",
        ]

        fzf = subprocess.Popen(["fzf", *fzf_args],
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=sys.stderr)

        def feed():
            try:
                count = 0
                limit = yts_api.LIMIT_ALL if args.all else yts_api.LIMIT
                for item in yts_api.search(query, refresh=args.refresh, filter_songs=not args.all, limit=limit):
                    count += 1
                    line = yts_player.format_line(item)
                    parts = line.split("\t")
                    fp = parts[0]
                    thumb_url = parts[2]
                    if count == 1:
                        yts_player.dl_thumb(thumb_url, fp)
                    elif not os.path.exists(fp):
                        threading.Thread(target=yts_player.dl_thumb,
                                         args=(thumb_url, fp),
                                         daemon=True).start()
                    try:
                        fzf.stdin.write((line + "\n").encode())
                        fzf.stdin.flush()
                    except BrokenPipeError:
                        break
            finally:
                try:
                    fzf.stdin.close()
                except OSError:
                    pass

        t0 = time.time()
        t = threading.Thread(target=feed, daemon=True)
        t.start()
        try:
            out = fzf.stdout.read().decode()
            fzf.wait()
        except KeyboardInterrupt:
            fzf.terminate()
            print()
            return
        dt = time.time() - t0

        selected = [ln for ln in out.strip().split("\n") if ln]
        if selected:
            has_video = any(ln.split("\t")[5].strip() == "video" for ln in selected)
            play_urls = [ln.split("\t")[1].strip() for ln in selected]
            rtypes = [ln.split("\t")[5].strip() for ln in selected]
            titles = [ln.split("\t")[3].strip() for ln in selected]
            thumbs = [ln.split("\t")[0].strip() for ln in selected]
            yts_player.play_handler(
                play_urls,
                rtypes,
                force_video=has_video,
                queue=False,
                titles=titles,
                thumbs=thumbs
            )
            print(f"\x1b[2m{len(selected)} selected in {dt:.0f}s\x1b[0m", file=sys.stderr)

if __name__ == "__main__":
    main()
