#!/home/rtx/prjs/projects/github_back/ytmusic_from_terminal/.venv/bin/python

import sys
from PIL import Image

if len(sys.argv) != 1:
    # we are assuming that the path provided exists and is imagefile, kinda reasonable
    image = Image.open(sys.argv[1])
    crop_box = (
        (image.width - image.height) / 2,
        0,
        image.height + (image.width - image.height) / 2,
        image.height,
    )
    image.crop(crop_box).save(sys.argv[1])
else:
    print("Provide The Path Of Image To Be Removed.")
