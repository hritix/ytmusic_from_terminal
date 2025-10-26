#!/home/rtx/prjs/projects/github_back/ytmusic_from_terminal/.venv/bin/python


import sys
from ytmusicapi import YTMusic as ym
from pathlib import Path

# https://ytmusicapi.readthedocs.io/en/stable/reference/search.html#ytmusicapi.YTMusic.search
from subprocess import run

base_url = "https://music.youtube.com/watch?v="
mpv_path = (
    "ampv"  # usinng the alternate mpv installation as the official arch package broken
)


fzf_preview_file = (
    "/".join(str(Path(sys.argv[0]).resolve()).split("/")[:-1]) + "/fzf-preview.sh"
)


def search():
    if len(sys.argv) > 1:
        a = ym().search(" ".join(sys.argv[1:]), "songs", limit=40)
        sys.argv = sys.argv[:1]
        return a
    else:
        search_query = input("Enter song name: ")
        if search_query in ["quit", "q", "exit", ""]:
            sys.exit()
        else:
            return ym().search(search_query, "songs", limit=40)


def get_views(a):
    weight = {"K": 1000, "M": 1000000, "B": 1000000000}
    multiplier = weight.get(a[-1], 1)
    if multiplier > 1:
        return float(a[:-1]) * multiplier
    else:
        return float(a)


def max_views_song():
    max_views = 0
    max_views_id = 0
    for i in range(len(search_results)):
        views = get_views(search_results[i].get("views"))
        if views > max_views:
            max_views = views
            max_views_id = i

    song = search_results[max_views_id]
    print("Title:", song.get("title"))
    print("Type:", song.get("resultType"))
    vid_id = song.get("videoId")
    song_url = f"{base_url}{vid_id}" if vid_id else None
    print("URL:", song_url)
    run([mpv_path, "--script=/etc/mpv/scripts/mpris.so", "--no-video", song_url])


def all_songs_choice():
    newlist = []
    for song in search_results:
        newlist.append(
            f"{song.get('title')}::{song.get('artists')[0].get('name')}::{song.get('videoId')}::{song.get('views')}"
        )
    choices = "\n".join(newlist)
    songs = run(
        [
            "fzf",
            "--multi",
            "--height",
            "60%",
            "--reverse",
            "--preview",
            fzf_preview_file + " {}",
            "--preview-window=default:right:40%",
        ],
        input=choices,
        text=True,
        capture_output=True,
    )
    if len(songs.stdout) == 0:
        print("No Songs Selected.")
        return 1
    songs = songs.stdout[:-1]
    for song in songs.split("\n"):
        print(song)
        song = song.split("::")
        print("Title:", song[0])
        print("Artist:", song[1])
        vid_id = song[2]
        song_url = f"{base_url}{vid_id}" if vid_id else None
        print("URL:", song_url)
        run([mpv_path, "--script=/etc/mpv/scripts/mpris.so", "--no-video", song_url])


if __name__ == "__main__":
    while True:
        search_results = search()
        all_songs_choice()
