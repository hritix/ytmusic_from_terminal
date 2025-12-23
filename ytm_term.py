#!/home/rtx/prjs/github_hritix/ytmusic_from_terminal/.venv/bin/python

import sys
from ytmusicapi import YTMusic as ym
from pathlib import Path
from os import getenv

# https://ytmusicapi.readthedocs.io/en/stable/reference/search.html#ytmusicapi.YTMusic.search
from subprocess import run

HOME = getenv("HOME")
download_folder=rf"{HOME}/Music/"

base_url = "https://music.youtube.com/watch?v="
tools={"mpv":['mpv','--no-video'],"downloader":['yt-dlp', '-f', 'bestaudio[ext=m4a]','--embed-thumbnail', '--ppa','ThumbnailsConvertor+FFmpeg_o:-vf crop=ih:ih','-P',f'{download_folder}']}
tool=tools["mpv"]

fzf_preview_file = (
        "/".join(str(Path(sys.argv[0]).resolve()).split("/")[:-1]) + "/fzf-preview.sh"
        ) #this will make it so that it works when the preview script is in the same folder as the python file

def search(search_logs_file):
    global tool
    if len(sys.argv) > 1:
        search_query=" ".join(sys.argv[1:])
    else:
        search_query = input("Enter Song Name: ")

    if search_query in ["quit", "q", "exit", ""]:
        sys.exit()
    else:
        if search_query[0:2]=="d ":
            search_query=search_query[2:]
            tool=tools["downloader"]
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
    tool.append(song_url)
    run(tool)


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
                "--preview-window=default:left:40%",
                "--preview-border",
                "none"
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
        tool.append(song_url)
        run(tool)


def logs(song_info, search_logs_file, file_urls):
    pass


if __name__ == "__main__":
    Path(rf"{HOME}/.config/ytm_term").mkdir(parents=True, exist_ok=True)
    # I am defining these outside the logs function because, then we will not have to close and open this everytime log function is over.
    search_logs_file = open(rf"{HOME}/.config/ytm_term/searches.txt", "a+")
    file_urls = open(rf"{HOME}/.config/ytm_term/urls.txt", "a+")
    # don't forget to close the files
    while True:
        run("clear")
        search_results = search(search_logs_file)
        all_songs_choice()
    search_logs_file.close()
