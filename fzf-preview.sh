#!/usr/bin/env bash

# fzf-preview.sh - Advanced file preview script for fzf
# Integrates with bat, eza, glow, mediainfo, pdfinfo, sqlite3, kitty, chafa, readelf, and ldd.

file="$1"
w="${FZF_PREVIEW_COLUMNS:-80}"
h="${FZF_PREVIEW_LINES:-40}"

# 1. Input validation
[[ -z "$file" || ! -e "$file" ]] && { echo "no file"; exit 0; }

# 2. Directory Check (fast path - avoids running file utility on directories)
if [[ -d "$file" ]]; then
  if command -v eza &>/dev/null; then
    echo -e "\e[1;34m=== Tree Structure ===\e[0m"
    eza --tree --level=3 --color=always --icons=always --group-directories-first --git-ignore "$file" | head -n "$((h / 2))"
    echo ""
    echo -e "\e[1;34m=== Detailed Directory List ===\e[0m"
    eza -la --color=always --icons=always --git --group-directories-first "$file" | head -n "$((h / 2))"
  elif command -v exa &>/dev/null; then
    exa -la --color=always --icons --git --group-directories-first "$file" | head -n "$h"
  elif command -v tree &>/dev/null; then
    tree -C -L 3 "$file" | head -n "$h"
  else
    ls -la --color=always "$file" | head -n "$h"
  fi
  exit 0
fi

# --- Helper functions for formatting size ---
get_human_size() {
  local size="$1"
  if (( size > 1048576 )); then
    echo "$((size / 1048576))MB"
  else
    echo "$((size / 1024))KB"
  fi
}

# --- Helper Preview Functions ---

preview_image() {
  local file="$1"
  local w="$2"
  local h="$3"
  local img_h=$h
  
  if [[ "$TERM" == xterm-kitty ]] && command -v kitty &>/dev/null; then
    kitty icat --clear --transfer-mode=stream --unicode-placeholder --stdin=no --place="${w}x${img_h}@0x0" -- "$file" 2>/dev/null || \
    kitty icat --clear --transfer-mode=memory --unicode-placeholder --stdin=no --place="${w}x${img_h}@0x0" -- "$file" 2>/dev/null
    echo -e '\e[m'
  else
    chafa --clear --symbols all --color-space rgb --fill resize --size "${w}x${img_h}" "$file" 2>/dev/null
  fi
}

preview_media() {
  local file="$1"
  local w="$2"
  local h="$3"
  local mime
  mime=$(file --brief --mime-type "$file")

  # For video files: extract a thumbnail frame and display as image
  if [[ "$mime" == video/* ]] && command -v ffmpeg &>/dev/null; then
    local tmp_frame="/tmp/fzf-video-$$.jpg"
    # Seek to 10% into the video for a more interesting frame
    local duration
    duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$file" 2>/dev/null)
    local seek=0
    if [[ -n "$duration" && "$duration" != "N/A" ]]; then
      seek=$(awk "BEGIN { printf \"%.2f\", $duration * 0.1 }")
    fi
    if ffmpeg -ss "$seek" -i "$file" -vframes 1 -q:v 2 -f image2 "$tmp_frame" -y 2>/dev/null; then
      preview_image "$tmp_frame" "$w" "$h"
      rm -f "$tmp_frame"
      return
    fi
    rm -f "$tmp_frame"
  fi

  # Fallback for audio or if ffmpeg fails: show metadata
  if command -v mediainfo &>/dev/null; then
    mediainfo "$file" | head -n "$h"
  elif command -v ffprobe &>/dev/null; then
    ffprobe -hide_banner "$file" 2>&1 | head -n "$h"
  else
    exiftool "$file" 2>/dev/null | head -n "$h"
  fi
}

preview_pdf() {
  local file="$1"
  local w="$2"
  local h="$3"
  local tmp_png="/tmp/fzf-pdf-$$"
  
  if command -v pdftoppm &>/dev/null; then
    if pdftoppm -png -f 1 -l 1 -singlefile "$file" "$tmp_png" 2>/dev/null; then
      local png_file="${tmp_png}.png"
      preview_image "$png_file" "$w" "$h"
      rm -f "$png_file"
      return
    fi
  fi
  
  # Fallback if pdftoppm is missing or fails
  if command -v pdfinfo &>/dev/null; then
    echo -e "\e[1;35m=== PDF Information ===\e[0m"
    pdfinfo "$file" 2>/dev/null | grep -E "^(Title|Author|Pages|File size|PDF version):" | sed 's/\s*:\s*/: /'
    echo ""
    echo -e "\e[1;34m=== Page Content (Sample) ===\e[0m"
    pdftotext -f 1 -l 5 "$file" - 2>/dev/null | head -n "$((h - 8))"
  else
    pdftotext "$file" - 2>/dev/null | head -n "$h"
  fi
}

preview_epub() {
  local file="$1"
  local h="$2"
  echo -e "\e[1;35m=== EPUB Document Preview ===\e[0m"
  if command -v pandoc &>/dev/null; then
    pandoc "$file" -t plain 2>/dev/null | head -n "$h" | bat --color=always -l txt 2>/dev/null || \
    pandoc "$file" -t plain 2>/dev/null | head -n "$h"
  else
    unzip -p "$file" '*.xhtml' 2>/dev/null | head -200 | sed 's/<[^>]*>//g' | head -n "$h"
  fi
}

preview_docx() {
  local file="$1"
  local h="$2"
  echo -e "\e[1;35m=== Word Document (.docx) Text Preview ===\e[0m"
  unzip -p "$file" word/document.xml 2>/dev/null | sed -e 's/<[^>]*>//g' -e 's/<\/[^>]*>/\n/g' | head -n "$h"
}

preview_odt() {
  local file="$1"
  local h="$2"
  echo -e "\e[1;35m=== OpenDocument Text (.odt) Text Preview ===\e[0m"
  unzip -p "$file" content.xml 2>/dev/null | sed -e 's/<[^>]*>//g' -e 's/<\/[^>]*>/\n/g' | head -n "$h"
}

preview_sqlite() {
  local file="$1"
  local h="$2"
  echo -e "\e[1;35m=== SQLite Database: ${file##*/} ===\e[0m"
  echo -e "\e[1;34mTables:\e[0m"
  sqlite3 "$file" ".tables" 2>/dev/null | column -t | sed 's/^/  /'
  echo ""
  echo -e "\e[1;34mSchema Details:\e[0m"
  sqlite3 "$file" ".schema" 2>/dev/null | head -n "$((h - 7))" | bat --color=always -l sql 2>/dev/null || \
  sqlite3 "$file" ".schema" 2>/dev/null | head -n "$((h - 7))"
}

preview_archive() {
  local file="$1"
  local h="$2"
  local mime="$3"
  
  if [[ "$file" == *.tar.gz || "$file" == *.tgz || "$file" == *.tar.bz2 || "$file" == *.tbz2 || "$file" == *.tar.xz || "$file" == *.txz || "$file" == *.tar.zst || "$file" == *.tzst ]]; then
    echo -e "\e[1;35m=== Tarball Archive Contents ===\e[0m"
    bsdtar -tvf "$file" 2>/dev/null | head -n "$h"
  elif [[ "$mime" == *gzip* || "$file" == *.gz ]]; then
    echo -e "\e[1;35m=== Decompressed GZIP Preview ===\e[0m"
    zcat "$file" 2>/dev/null | head -n "$h" | bat --color=always 2>/dev/null || zcat "$file" 2>/dev/null | head -n "$h"
  elif [[ "$mime" == *x-bzip2* || "$file" == *.bz2 ]]; then
    echo -e "\e[1;35m=== Decompressed BZIP2 Preview ===\e[0m"
    bzcat "$file" 2>/dev/null | head -n "$h" | bat --color=always 2>/dev/null || bzcat "$file" 2>/dev/null | head -n "$h"
  elif [[ "$mime" == *x-xz* || "$file" == *.xz ]]; then
    echo -e "\e[1;35m=== Decompressed XZ Preview ===\e[0m"
    xzcat "$file" 2>/dev/null | head -n "$h" | bat --color=always 2>/dev/null || xzcat "$file" 2>/dev/null | head -n "$h"
  elif [[ "$mime" == *x-zstd* || "$file" == *.zst ]]; then
    echo -e "\e[1;35m=== Decompressed ZSTD Preview ===\e[0m"
    zstdcat "$file" 2>/dev/null | head -n "$h" | bat --color=always 2>/dev/null || zstdcat "$file" 2>/dev/null | head -n "$h"
  else
    echo -e "\e[1;35m=== Archive Contents ===\e[0m"
    7z l "$file" 2>/dev/null | head -n "$h" || \
    bsdtar -tvf "$file" 2>/dev/null | head -n "$h" || \
    unzip -l "$file" 2>/dev/null | head -n "$h"
  fi
}

preview_binary() {
  local file="$1"
  local h="$2"
  echo -e "\e[1;35m=== ELF Binary Info ===\e[0m"
  file -b "$file"
  echo ""
  if command -v ldd &>/dev/null && file "$file" | grep -q "dynamically linked"; then
    echo -e "\e[1;34mDynamic Library Dependencies:\e[0m"
    ldd "$file" 2>/dev/null | sed 's/^/  /' | head -n 15
    echo ""
  fi
  if command -v readelf &>/dev/null; then
    echo -e "\e[1;34mELF Header Summary:\e[0m"
    readelf -h "$file" 2>/dev/null | head -n "$((h - 15))"
  fi
}

preview_markdown() {
  local file="$1"
  local w="$2"
  local h="$3"
  if command -v glow &>/dev/null; then
    glow -s dark -w "$w" "$file" 2>/dev/null | head -n "$h"
  else
    bat --color=always "$file" 2>/dev/null || head -n "$h" "$file"
  fi
}

preview_json() {
  local file="$1"
  local h="$2"
  local size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
  
  if (( size > 2000000 )); then
    local hs=$(get_human_size "$size")
    echo -e "\e[1;33m[Large File Guard] JSON file is too large ($hs) - showing raw first 1000 lines\e[0m"
    echo ""
    head -n 1000 "$file" | bat --color=always -l json 2>/dev/null || head -n 1000 "$file"
    return
  fi

  jq . "$file" 2>/dev/null | bat --color=always -l json 2>/dev/null || \
  jq . "$file" 2>/dev/null | head -n "$h" || \
  bat --color=always "$file" 2>/dev/null || \
  head -n "$h" "$file"
}

# --- Extension-based matching (Fast path) ---
ext="${file##*/}" # Handle hidden files correctly
ext="${ext##*.}"
ext="${ext,,}"

case "$ext" in
  md|markdown)
    preview_markdown "$file" "$w" "$h"
    exit 0
    ;;
  json|ipynb)
    preview_json "$file" "$h"
    exit 0
    ;;
  png|jpg|jpeg|gif|webp|bmp|ico|tiff|svg)
    preview_image "$file" "$w" "$h"
    exit 0
    ;;
  pdf)
    preview_pdf "$file" "$w" "$h"
    exit 0
    ;;
  epub)
    preview_epub "$file" "$h"
    exit 0
    ;;
  docx)
    preview_docx "$file" "$h"
    exit 0
    ;;
  odt)
    preview_odt "$file" "$h"
    exit 0
    ;;
  db|sqlite|sqlite3)
    preview_sqlite "$file" "$h"
    exit 0
    ;;
  mp3|mp4|mkv|avi|mov|flac|wav|ogg|webm)
    preview_media "$file" "$w" "$h"
    exit 0
    ;;
  zip|tar|gz|bz2|xz|zst|7z|tgz|tbz2|txz|tzst)
    preview_archive "$file" "$h" ""
    exit 0
    ;;
esac

# --- Fallback to MIME type detection ---
mime=$(file --brief --mime-type "$file")

case "$mime" in
  image/*)
    preview_image "$file" "$w" "$h"
    ;;
  video/*|audio/*)
    preview_media "$file" "$w" "$h"
    ;;
  application/pdf)
    preview_pdf "$file" "$w" "$h"
    ;;
  application/epub+zip)
    preview_epub "$file" "$h"
    ;;
  *wordprocessingml.document)
    preview_docx "$file" "$h"
    ;;
  *opendocument.text)
    preview_odt "$file" "$h"
    ;;
  *sqlite3)
    preview_sqlite "$file" "$h"
    ;;
  application/zip|application/gzip|application/x-7z-compressed|application/x-tar|application/x-bzip2|application/x-xz|application/x-zstd)
    preview_archive "$file" "$h" "$mime"
    ;;
  *x-executable|*x-sharedlib|*x-pie-executable)
    preview_binary "$file" "$h"
    ;;
  text/markdown)
    preview_markdown "$file" "$w" "$h"
    ;;
  *json*)
    preview_json "$file" "$h"
    ;;
  text/*|application/xml|*/javascript|*/typescript|*/yaml|*/toml|*/x-subrip|*/x-perl|*/x-python|*/x-ruby|*/x-sh|*/x-c|*/x-c++|*/x-java|*/x-php)
    size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
    if (( size > 2000000 )); then
      hs=$(get_human_size "$size")
      echo -e "\e[1;33m[Large File Guard] File is too large ($hs) - showing first 1000 lines\e[0m"
      echo ""
      bat --color=always --line-range :1000 "$file" 2>/dev/null || head -n 1000 "$file"
    else
      bat --color=always "$file" 2>/dev/null || head -n "$h" "$file"
    fi
    ;;
  application/octet-stream)
    size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
    if (( size > 2000000 )); then
      hs=$(get_human_size "$size")
      echo -e "\e[1;33m[Large File Guard] Binary file is too large ($hs) - showing hex dump of first 1000 lines\e[0m"
      echo ""
      xxd "$file" 2>/dev/null | head -n 1000 || od -A x -t x1z "$file" | head -n 1000
    elif file "$file" | grep -qi "text"; then
      bat --color=always "$file" 2>/dev/null || head -n "$h" "$file"
    else
      echo -e "\e[1;33m[Hex Dump]\e[0m"
      xxd "$file" 2>/dev/null | head -n "$h" || od -A x -t x1z "$file" | head -n "$h"
    fi
    ;;
  *)
    size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
    if (( size > 2000000 )); then
      hs=$(get_human_size "$size")
      echo -e "\e[1;33m[Large File Guard] File is too large ($hs) - showing first 1000 lines\e[0m"
      echo ""
      if file "$file" | grep -qi "text"; then
        bat --color=always --line-range :1000 "$file" 2>/dev/null || head -n 1000 "$file"
      else
        xxd "$file" 2>/dev/null | head -n 1000 || od -A x -t x1z "$file" | head -n 1000
      fi
    elif bat --color=always "$file" 2>/dev/null; then
      :
    elif file "$file" | grep -qi "text"; then
      head -n "$h" "$file"
    else
      echo -e "\e[1;33m[Hex Dump]\e[0m"
      xxd "$file" 2>/dev/null | head -n "$h" || od -A x -t x1z "$file" | head -n "$h"
    fi
    ;;
esac
