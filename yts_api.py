import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from http.client import HTTPSConnection
from urllib.parse import quote

CACHE = os.path.expanduser("~/.cache/youtube_music_search")
THUMBS = os.path.join(CACHE, "thumbs")
CONFIG_FILE = os.path.join(CACHE, "api_config.json")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
LIMIT = 50
LIMIT_ALL = 50
CAT_MAP = {"album": "Albums", "playlist": "Playlists", "podcast": "Episodes",
           "video": "Videos", "artist": "Artists", "song": "Songs",
           "top_result": "Top result"}


def decompress_br(raw: bytes) -> bytes:
    p = subprocess.Popen(["brotli", "-d", "-c"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    out, _ = p.communicate(raw)
    return out


def decode_js_str(raw_data: str) -> str:
    """Decode a JS string literal with hex/unicode escapes to UTF-8."""
    raw_data = raw_data.replace("\\/", "/")
    escaped = raw_data.encode("utf-8")
    decoded = escaped.decode("unicode_escape")
    try:
        decoded = decoded.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return decoded


def get_initial_data(html: str) -> dict | None:
    m = re.search(r'<script[^>]*>.*?YTMUSIC_INITIAL_DATA.*?</script>',
                  html, re.DOTALL)
    if not m:
        return None
    script = m.group(0)
    idx = script.find("initialData.push({path: '/search")
    if idx < 0:
        idx = script.find("initialData.push({path: '\\/search")
    if idx < 0:
        return None
    dstart = script.find("data: '", idx)
    if dstart < 0:
        dstart = script.find('data: "', idx)
    if dstart < 0:
        return None
    qchar = script[dstart + 6]
    qpos = dstart + 7
    end = qpos
    while end < len(script):
        if script[end] == "\\":
            end += 2
        elif script[end] == qchar:
            break
        else:
            end += 1
    raw_data = script[qpos:end]
    return json.loads(decode_js_str(raw_data))


def get_api_key(html: str) -> str:
    m = re.search(r'INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    return m.group(1) if m else ""


def get_client_ver(html: str) -> str:
    m = re.search(r'INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html)
    return m.group(1) if m else "1.20260531.05.00"


def get_songs_params(data: dict) -> str | None:
    try:
        header = (data["contents"]["tabbedSearchResultsRenderer"]
                  ["tabs"][0]["tabRenderer"]["content"]
                  ["sectionListRenderer"]["header"])
        chips = header["chipCloudRenderer"].get("chips", [])
        for chip in chips:
            ccr = chip.get("chipCloudChipRenderer", {})
            text = ""
            try:
                text = ccr["text"]["runs"][0]["text"]
            except (KeyError, IndexError):
                pass
            if text == "Songs":
                return (ccr["navigationEndpoint"]["searchEndpoint"]
                        .get("params"))
    except (KeyError, IndexError, TypeError):
        pass
    return None


def parse_card_shelf(csr: dict) -> dict | None:
    nav = csr.get("onTap", {})
    vid = nav.get("watchEndpoint", {}).get("videoId", "")
    playlist_id = ""
    browse_id = ""
    if not vid:
        playlist_id = nav.get("watchPlaylistEndpoint", {}).get("playlistId", "")
    if not vid and not playlist_id:
        browse_id = nav.get("browseEndpoint", {}).get("browseId", "")
        
    if not vid and not playlist_id and not browse_id:
        buttons = csr.get("buttons", [])
        for btn in buttons:
            cmd = btn.get("buttonRenderer", {}).get("command", {})
            vid = cmd.get("watchEndpoint", {}).get("videoId", "")
            if not vid:
                playlist_id = cmd.get("watchPlaylistEndpoint", {}).get("playlistId", "")
            if not vid and not playlist_id:
                browse_id = cmd.get("browseEndpoint", {}).get("browseId", "")
            if vid or playlist_id or browse_id:
                break
                
    if not vid and not playlist_id and not browse_id:
        return None
        
    item_id = vid if vid else (playlist_id if playlist_id else browse_id)
    
    title = ""
    t_runs = csr.get("title", {}).get("runs", [])
    if t_runs:
        title = "".join(x.get("text", "") for x in t_runs).replace("\t", " ")
        
    sub_runs = csr.get("subtitle", {}).get("runs", [])
    rtype, artist, album, plays, duration, year = parse_metadata_runs(sub_runs)
    if not rtype:
        if vid:
            rtype = "song"
        elif playlist_id:
            rtype = "playlist"
        elif browse_id:
            rtype = "artist"
            
    thumb = ""
    try:
        thumb = (csr["thumbnail"]["musicThumbnailRenderer"]
                 ["thumbnail"]["thumbnails"][-1]["url"])
        if "googleusercontent.com" in thumb:
            base = thumb.split("=")[0]
            thumb = f"{base}=w600-h600-p-l90-rj"
    except (KeyError, IndexError, TypeError):
        pass
    if not thumb and vid:
        thumb = f"https://i.ytimg.com/vi/{vid}/sddefault.jpg"

    return {
        "id": item_id,
        "playlist_id": playlist_id,
        "rtype": rtype,
        "title": title,
        "artist": artist,
        "album": album,
        "plays": plays,
        "duration": duration,
        "year": year,
        "thumb": thumb,
        "section": "Top result"
    }


def parse_sections(data: dict) -> list[dict]:
    items = []
    try:
        sections = (data["contents"]["tabbedSearchResultsRenderer"]
                    ["tabs"][0]["tabRenderer"]["content"]
                    ["sectionListRenderer"]["contents"])
    except (KeyError, IndexError, TypeError):
        return items
    for sec in sections:
        # musicCardShelfRenderer (Top Result Card)
        csr = sec.get("musicCardShelfRenderer")
        if csr:
            main_item = parse_card_shelf(csr)
            if main_item:
                items.append(main_item)
            for content in csr.get("contents", []):
                r = content.get("musicResponsiveListItemRenderer")
                if r:
                    item = parse_item(r)
                    if item:
                        item["section"] = "Top result"
                        items.append(item)
        # API: musicShelfRenderer -> contents -> musicResponsiveListItemRenderer
        msr = sec.get("musicShelfRenderer", {})
        cat = ""
        if msr:
            try:
                cat = msr["title"]["runs"][0]["text"]
            except (KeyError, IndexError):
                pass
        for content in msr.get("contents", []):
            r = content.get("musicResponsiveListItemRenderer")
            if r:
                item = parse_item(r)
                if item:
                    item["section"] = cat
                    items.append(item)
        # itemSectionRenderer -> contents -> musicResponsiveListItemRenderer
        isr = sec.get("itemSectionRenderer", {})
        for content in isr.get("contents", []):
            r = content.get("musicResponsiveListItemRenderer")
            if r:
                item = parse_item(r)
                if item:
                    if not item["section"]:
                        item["section"] = CAT_MAP.get(item["rtype"], "")
                    items.append(item)
    return items


def get_continuation_token(data: dict) -> str | None:
    """Extract continuation token from the search response."""
    try:
        sections = (data["contents"]["tabbedSearchResultsRenderer"]
                    ["tabs"][0]["tabRenderer"]["content"]
                    ["sectionListRenderer"]["contents"])
        for sec in sections:
            msr = sec.get("musicShelfRenderer")
            if msr:
                for cont in msr.get("continuations", []):
                    tok = (cont.get("nextContinuationData", {})
                           .get("continuation"))
                    if tok:
                        return tok
            isr = sec.get("itemSectionRenderer", {})
            for content in isr.get("contents", []):
                cir = content.get("continuationItemRenderer")
                if cir:
                    tok = (cir.get("continuationEndpoint", {})
                           .get("continuationCommand", {})
                           .get("token"))
                    if tok:
                        return tok
    except (KeyError, IndexError, TypeError):
        pass
    return None


def is_separator(text: str) -> bool:
    t = text.strip()
    return not t or t in ("•", "·", "·", ",", "-", "|")


def is_duration(text: str) -> bool:
    return bool(re.match(r'^\d+:\d+(:\d+)?$', text.strip()))


def is_year(text: str) -> bool:
    return bool(re.match(r'^\d{4}$', text.strip()))


def is_plays(text: str) -> bool:
    t = text.lower()
    return "plays" in t or "views" in t or "listeners" in t or "subscribers" in t or "audience" in t or "monthly" in t


def parse_metadata_runs(runs: list) -> tuple:
    # Group runs by separators
    sections = []
    current_section = []
    for r in runs:
        txt = r.get("text", "")
        if is_separator(txt):
            if current_section:
                sections.append("".join(current_section).strip())
                current_section = []
        else:
            current_section.append(txt)
    if current_section:
        sections.append("".join(current_section).strip())

    sections = [s for s in sections if s]

    rtype = ""
    type_prefixes = {
        "song": "song", "video": "video", "album": "album", "ep": "album",
        "single": "album", "playlist": "playlist", "podcast": "podcast",
        "episode": "podcast", "artist": "artist"
    }
    if sections:
        first_lower = sections[0].lower()
        if first_lower in type_prefixes:
            rtype = type_prefixes[first_lower]
            sections.pop(0)

    artist, album, plays, duration, year = "", "", "", "", ""
    remaining = []
    for s in sections:
        if is_duration(s):
            duration = s
        elif is_plays(s):
            plays = s
        elif is_year(s):
            year = s
        else:
            remaining.append(s)

    if remaining:
        artist = remaining[0]
        if len(remaining) > 1:
            album = remaining[1]

    return rtype, artist, album, plays, duration, year


def parse_item(r: dict) -> dict | None:
    vid = ""
    playlist_id = ""
    browse_id = ""

    nav = r.get("navigationEndpoint", {})
    vid = nav.get("watchEndpoint", {}).get("videoId", "")
    if not vid:
        playlist_id = nav.get("watchPlaylistEndpoint", {}).get("playlistId", "")
    if not vid and not playlist_id:
        browse_id = nav.get("browseEndpoint", {}).get("browseId", "")

    if not vid and not playlist_id and not browse_id:
        try:
            pne = (r["overlay"]["musicItemThumbnailOverlayRenderer"]
                    ["content"]["musicPlayButtonRenderer"]
                    ["playNavigationEndpoint"])
            if not vid:
                vid = pne.get("watchEndpoint", {}).get("videoId", "")
            if not vid:
                playlist_id = pne.get("watchPlaylistEndpoint", {}).get("playlistId", "")
        except (KeyError, IndexError, TypeError):
            pass

    if not vid and not playlist_id and not browse_id:
        return None

    item_id = vid if vid else (playlist_id if playlist_id else browse_id)

    flex = r.get("flexColumns", [])

    title = ""
    if flex:
        runs = (flex[0].get("musicResponsiveListItemFlexColumnRenderer", {})
                .get("text", {}).get("runs", []))
        title = "".join(x.get("text", "") for x in runs).replace("\t", " ")

    # Collect metadata runs from columns 1 and 2, separated by a dummy delimiter
    metadata_runs = []
    for col_idx in (1, 2):
        if len(flex) > col_idx:
            runs = (flex[col_idx].get("musicResponsiveListItemFlexColumnRenderer", {})
                    .get("text", {}).get("runs", []))
            if metadata_runs and runs:
                metadata_runs.append({"text": " • "})
            metadata_runs.extend(runs)

    rtype, artist, album, plays, duration, year = parse_metadata_runs(metadata_runs)

    if not rtype:
        if vid:
            rtype = "song"
        elif playlist_id:
            rtype = "playlist"
        elif browse_id:
            rtype = "artist"

    # Check fixedColumns for duration as fallback/primary
    fixed = r.get("fixedColumns", [])
    if fixed:
        try:
            runs = (fixed[0].get("musicResponsiveListItemFixedColumnRenderer", {})
                    .get("text", {}).get("runs", []))
            dur_text = "".join(x.get("text", "") for x in runs).strip()
            if dur_text:
                duration = dur_text
        except (KeyError, IndexError, TypeError):
            pass

    thumb = ""
    try:
        thumb = (r["thumbnail"]["musicThumbnailRenderer"]
                 ["thumbnail"]["thumbnails"][-1]["url"])
        if "googleusercontent.com" in thumb:
            base = thumb.split("=")[0]
            thumb = f"{base}=w600-h600-p-l90-rj"
    except (KeyError, IndexError, TypeError):
        pass
    if not thumb and vid:
        thumb = f"https://i.ytimg.com/vi/{vid}/sddefault.jpg"

    return {
        "id": item_id,
        "playlist_id": playlist_id,
        "rtype": rtype,
        "title": title,
        "artist": artist,
        "album": album,
        "plays": plays,
        "duration": duration,
        "year": year,
        "thumb": thumb,
        "section": ""
    }


def load_config() -> dict | None:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_config(api_key: str, client_ver: str, params: str):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"api_key": api_key, "client_ver": client_ver,
                    "params": params}, f)


def _fetch_html(url_path: str) -> str | None:
    try:
        conn = HTTPSConnection("music.youtube.com")
        conn.request("GET", url_path,
                     headers={"User-Agent": UA,
                              "Accept": "text/html,application/xhtml+xml",
                              "Accept-Language": "en-US,en;q=0.5"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        encoding = resp.getheader("Content-Encoding")
        if encoding == "br":
            raw = decompress_br(raw)
        elif encoding in ("gzip", "deflate"):
            import gzip
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Network error: {e}", file=sys.stderr)
        return None


def get_category_params(data: dict) -> dict:
    cat_params = {}
    try:
        header = (data["contents"]["tabbedSearchResultsRenderer"]
                  ["tabs"][0]["tabRenderer"]["content"]
                  ["sectionListRenderer"]["header"])
        chips = header["chipCloudRenderer"].get("chips", [])
        for chip in chips:
            ccr = chip.get("chipCloudChipRenderer", {})
            text = ""
            try:
                text = ccr["text"]["runs"][0]["text"]
            except (KeyError, IndexError):
                pass
            p = ccr["navigationEndpoint"]["searchEndpoint"].get("params")
            if text and p:
                cat_params[text] = p
    except (KeyError, IndexError, TypeError):
        pass
    return cat_params


def query_endpoint(query: str, api_key: str, client_ver: str, params: str | None, ctx: dict, seen: set, limit: int):
    conn = HTTPSConnection("music.youtube.com")
    try:
        body = json.dumps({"context": ctx, "query": query, "params": params})
        conn.request("POST", f"/youtubei/v1/search?key={api_key}&prettyPrint=false",
                     body=body,
                     headers={"Content-Type": "application/json",
                              "User-Agent": UA,
                              "Accept-Encoding": "br"})
        resp = conn.getresponse()
        raw = resp.read()
        if resp.getheader("Content-Encoding") == "br":
            raw = decompress_br(raw)
        resp_data = json.loads(raw.decode("utf-8"))

        for item in parse_sections(resp_data):
            if item and item["id"] and item["id"] not in seen:
                seen.add(item["id"])
                yield item
                if len(seen) >= limit:
                    return

        token = get_continuation_token(resp_data)
        while token and len(seen) < limit:
            cbody = json.dumps({"context": ctx, "continuation": token})
            conn.request("POST",
                         f"/youtubei/v1/search?key={api_key}&prettyPrint=false",
                         body=cbody,
                         headers={"Content-Type": "application/json",
                                  "User-Agent": UA,
                                  "Accept-Encoding": "br"})
            cresp = conn.getcall() if hasattr(conn, "getcall") else conn.getresponse()
            craw = cresp.read()
            if cresp.getheader("Content-Encoding") == "br":
                craw = decompress_br(craw)
            cdata = json.loads(craw.decode("utf-8"))

            added = 0
            msc = cdata.get("continuationContents", {}).get("musicShelfContinuation", {})
            if msc:
                for content in msc.get("contents", []):
                    r = content.get("musicResponsiveListItemRenderer")
                    if r:
                        item = parse_item(r)
                        if item and item["id"] and item["id"] not in seen:
                            seen.add(item["id"])
                            added += 1
                            yield item
                            if len(seen) >= limit:
                                return
                token = None
                for cont in msc.get("continuations", []):
                    token = (cont.get("nextContinuationData", {})
                             .get("continuation"))
                    if token:
                        break
            else:
                for action in (cdata.get("onResponseReceivedActions")
                               or cdata.get("onResponseReceivedCommands")
                               or []):
                    acia = (action.get("appendContinuationItemsAction", {})
                            .get("continuationItems", []))
                    for citem in acia:
                        cr = citem.get("continuationItemRenderer", {})
                        if cr:
                            try:
                                token = (cr["continuationEndpoint"]
                                         ["continuationCommand"]["token"])
                            except (KeyError, IndexError):
                                token = None
                            continue
                        r = citem.get("musicResponsiveListItemRenderer")
                        if not r:
                            isr = citem.get("itemSectionRenderer", {})
                            for sub in isr.get("contents", []):
                                r = sub.get("musicResponsiveListItemRenderer")
                                if r:
                                    break
                        if r:
                            item = parse_item(r)
                            if item and item["id"] and item["id"] not in seen:
                                seen.add(item["id"])
                                added += 1
                                yield item
                                if len(seen) >= limit:
                                    return
                if added == 0:
                    break
    except Exception as e:
        print(f"API Endpoint query error: {e}", file=sys.stderr)
    finally:
        conn.close()


def fetch_category_worker(query: str, api_key: str, client_ver: str, params: str, ctx: dict, out_queue: queue.Queue, cat_name: str):
    conn = HTTPSConnection("music.youtube.com")
    try:
        body = json.dumps({"context": ctx, "query": query, "params": params})
        conn.request("POST", f"/youtubei/v1/search?key={api_key}&prettyPrint=false",
                     body=body,
                     headers={"Content-Type": "application/json",
                              "User-Agent": UA,
                              "Accept-Encoding": "br"})
        resp = conn.getresponse()
        raw = resp.read()
        if resp.getheader("Content-Encoding") == "br":
            raw = decompress_br(raw)
        resp_data = json.loads(raw.decode("utf-8"))

        items = []
        for item in parse_sections(resp_data):
            if item and item["id"]:
                items.append(item)
        out_queue.put((cat_name, items, None))
    except Exception as e:
        out_queue.put((cat_name, [], e))
    finally:
        conn.close()


def search(query: str, refresh: bool = False, filter_songs: bool = True, limit: int = LIMIT):
    config = None if refresh else load_config()

    if config:
        api_key = config["api_key"]
        client_ver = config["client_ver"]
        cached_params = config.get("params")
        if isinstance(cached_params, dict):
            cat_params = cached_params
        else:
            cat_params = {"Songs": cached_params or ""}
    else:
        html = _fetch_html(f"/search?q={quote(query)}")
        if not html:
            return
        data = get_initial_data(html)
        if not data:
            return
        api_key = get_api_key(html)
        client_ver = get_client_ver(html)
        cat_params = get_category_params(data)
        if not api_key:
            return
        save_config(api_key, client_ver, cat_params)

    ctx = {
        "client": {
            "hl": "en", "gl": "US",
            "clientName": "WEB_REMIX",
            "clientVersion": client_ver,
        }
    }

    seen = set()

    if filter_songs:
        p = cat_params.get("Songs")
        yield from query_endpoint(query, api_key, client_ver, p, ctx, seen, limit)
    else:
        # Mixed (all) mode
        yield from query_endpoint(query, api_key, client_ver, None, ctx, seen, limit)

        if len(seen) < limit:
            categories = ["Songs", "Videos", "Albums", "Community playlists", "Podcasts"]
            active_cats = [cat for cat in categories if cat_params.get(cat)]
            if active_cats:
                result_queue = queue.Queue()
                for cat in active_cats:
                    p = cat_params[cat]
                    t = threading.Thread(
                        target=fetch_category_worker,
                        args=(query, api_key, client_ver, p, ctx, result_queue, cat),
                        daemon=True
                    )
                    t.start()

                finished = 0
                while finished < len(active_cats) and len(seen) < limit:
                    try:
                        cat_name, items, err = result_queue.get(timeout=3.0)
                        finished += 1
                        for item in items:
                            if item["id"] not in seen:
                                seen.add(item["id"])
                                yield item
                                if len(seen) >= limit:
                                    break
                    except queue.Empty:
                        break

        if len(seen) < limit:
            p = cat_params.get("Songs")
            if p:
                yield from query_endpoint(query, api_key, client_ver, p, ctx, seen, limit)


def find_keys_recursive(obj, target_key):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target_key:
                results.append(v)
            else:
                results.extend(find_keys_recursive(v, target_key))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_keys_recursive(item, target_key))
    return results


def find_all_list_items(obj) -> list[dict]:
    results = []
    if isinstance(obj, dict):
        if "musicResponsiveListItemRenderer" in obj:
            results.append(obj["musicResponsiveListItemRenderer"])
        for v in obj.values():
            results.extend(find_all_list_items(v))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_all_list_items(item))
    return results


def fetch_artist_songs(browse_id: str, api_key: str, client_ver: str, ctx: dict) -> list[dict]:
    conn = HTTPSConnection("music.youtube.com")
    songs = []
    try:
        body = json.dumps({"context": ctx, "browseId": browse_id})
        conn.request("POST", f"/youtubei/v1/browse?key={api_key}",
                     body=body,
                     headers={"Content-Type": "application/json",
                              "User-Agent": UA,
                              "Accept-Encoding": "br"})
        resp = conn.getresponse()
        raw = resp.read()
        if resp.getheader("Content-Encoding") == "br":
            raw = decompress_br(raw)
        data = json.loads(raw.decode("utf-8"))

        # Find "Top songs" shelf
        playlist_id = ""
        shelf_songs = []

        scbrr = data.get("contents", {}).get("singleColumnBrowseResultsRenderer", {})
        tabs = scbrr.get("tabs", [])
        sections = []
        if tabs:
            content = tabs[0].get("tabRenderer", {}).get("content", {})
            sections = content.get("sectionListRenderer", {}).get("contents", [])

        for sec in sections:
            sec_type = list(sec.keys())[0]
            if sec_type == "musicShelfRenderer":
                renderer = sec["musicShelfRenderer"]
                title_runs = renderer.get("title", {}).get("runs", [])
                title = "".join(r.get("text", "") for r in title_runs).strip()
                if "songs" in title.lower():
                    # Check for bottomEndpoint
                    be = renderer.get("bottomEndpoint", {})
                    playlist_id = be.get("browseEndpoint", {}).get("browseId", "")
                    if not playlist_id:
                        playlist_id = be.get("watchPlaylistEndpoint", {}).get("playlistId", "")
                    
                    for itm in renderer.get("contents", []):
                        r = itm.get("musicResponsiveListItemRenderer")
                        if r:
                            parsed = parse_item(r)
                            if parsed:
                                shelf_songs.append(parsed)

        if playlist_id:
            playlist_songs = fetch_playlist_songs(playlist_id, api_key, client_ver, ctx)
            if playlist_songs:
                return playlist_songs

        if shelf_songs:
            return shelf_songs

        # Fallback recursive search
        fallback_items = find_all_list_items(data)
        for r in fallback_items:
            parsed = parse_item(r)
            if parsed and parsed.get("rtype") in ("song", "video"):
                songs.append(parsed)
        if songs:
            return songs
    except Exception as e:
        print(f"Error fetching artist songs: {e}", file=sys.stderr)
    finally:
        conn.close()
    return songs


def fetch_playlist_songs(playlist_id: str, api_key: str, client_ver: str, ctx: dict) -> list[dict]:
    conn = HTTPSConnection("music.youtube.com")
    songs = []
    try:
        body = json.dumps({"context": ctx, "browseId": playlist_id})
        conn.request("POST", f"/youtubei/v1/browse?key={api_key}",
                     body=body,
                     headers={"Content-Type": "application/json",
                              "User-Agent": UA,
                              "Accept-Encoding": "br"})
        resp = conn.getresponse()
        raw = resp.read()
        if resp.getheader("Content-Encoding") == "br":
            raw = decompress_br(raw)
        data = json.loads(raw.decode("utf-8"))

        shelves = find_keys_recursive(data, "musicPlaylistShelfRenderer")
        if shelves:
            shelf = shelves[0]
            for itm in shelf.get("contents", []):
                r = itm.get("musicResponsiveListItemRenderer")
                if r:
                    parsed = parse_item(r)
                    if parsed:
                        songs.append(parsed)
    except Exception as e:
        print(f"Error fetching playlist songs: {e}", file=sys.stderr)
    finally:
        conn.close()
    return songs
