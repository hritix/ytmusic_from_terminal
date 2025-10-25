#!/usr/bin/env bash

ENABLE_IMAGE_PREVIEW=true

imgprv() {
    img_file="$1"
    preview_dims="$2"
    final_dims="$preview_dims"
	kitten icat --clear --transfer-mode=stream --unicode-placeholder --stdin=no --place="${final_dims}@0x0" -- "$img_file" 2>/dev/null
}

dim="${FZF_PREVIEW_COLUMNS}x${FZF_PREVIEW_LINES}"

url=`printf "$1" | cut -d ":" -f5`
img_url="https://img.youtube.com/vi/$url/maxresdefault.jpg"

mkdir -p $HOME/.cache/thumbnails/big
img_file=$HOME/.cache/thumbnails/big/"$url".jpg

[[ -s $img_file ]] || curl -sL "$img_url" > $img_file
imgprv "$img_file" "$dim"
