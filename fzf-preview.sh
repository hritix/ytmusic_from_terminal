#!/usr/bin/env bash

ENABLE_IMAGE_PREVIEW=true

imgprv() {
    img_file="$1"
	final_dims="${FZF_PREVIEW_COLUMNS}x${FZF_PREVIEW_LINES}"
	if [[ $TERM = xterm-kitty || $TERM = xterm-ghostty ]];then
		err_file=`mktemp`
		kitten icat --clear --transfer-mode=stream --unicode-placeholder --stdin=no --place="${final_dims}@0x0" -- "$img_file" 2>$err_file
		#can't use the exit codes as unlike chafa they are not reliable in kitten icat, so just catching the errors 
		[[ -s $err_file ]] && command rm $err_file && curl -sL "$img_url" > $img_file && imgprv "$img_file" "$dim" || command rm $err_file
	else
		chafa -s "$final_dims" -- "$img_file" 2>/dev/null
		if [ $? -ne 0 ];then
			curl -sL "$img_url" > $img_file && imgprv "$img_file" "$dim"
		fi
	fi
}

url=`printf "$1" | cut -d ":" -f5`
img_url="https://img.youtube.com/vi/$url/maxresdefault.jpg"

mkdir -p $HOME/.cache/thumbnails/big
img_file=$HOME/.cache/thumbnails/big/"$url".jpg
crop_script=`dirname "$0"`/image_crop.py
[[ -s $img_file ]] || (curl -sL "$img_url" > $img_file && $crop_script $img_file)
imgprv "$img_file" "$dim"
