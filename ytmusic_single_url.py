#!/home/rtx/prjs/python_venvs/web_scraping/bin/python


import sys
from ytmusicapi import YTMusic as ym

# https://ytmusicapi.readthedocs.io/en/stable/reference/search.html#ytmusicapi.YTMusic.search
from subprocess import run

base_url = "https://music.youtube.com/watch?v="

if len(sys.argv) > 1:
    search_results = ym().search(sys.argv[1], "songs")
else:
    search_results = ym().search(input("Enter song name: "), "songs")


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
    run(["mpv", "--no-video", song_url])


def all_songs_choice():
    newlist = []
    for song in search_results:
        newlist.append(
            f"{song.get('title')}:{song.get('artists')[0].get('name')}:{song.get('videoId')}:{song.get('views')}"
        )
    choices = "\n".join(newlist)
    song = run(["fzf", "--reverse"], input=choices, text=True, capture_output=True)
    song = song.stdout[:-1]
    song = song.split(":")
    print("Title:", song[0])
    print("Artist:", song[1])
    vid_id = song[2]
    song_url = f"{base_url}{vid_id}" if vid_id else None
    print("URL:", song_url)
    run(["mpv", "--no-video", song_url])


all_songs_choice()
