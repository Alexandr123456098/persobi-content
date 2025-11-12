# -*- coding: utf-8 -*-
import os, sys
from dotenv import load_dotenv

sys.path.insert(0, "/opt/content_factory")  # чтобы импортировался пакет app
load_dotenv("/opt/content_factory/.env")

from app.adapters.wan_adapter import run_wan_i2v, WanError

def main():
    if len(sys.argv) < 3:
        print("USAGE: python3 wan_smoketest.py <image_path> <prompt>")
        sys.exit(2)
    img = sys.argv[1]
    prompt = " ".join(sys.argv[2:])
    try:
        url = run_wan_i2v(img, prompt)
        print("WAN OK:", url)
    except WanError as e:
        print("WAN FAIL:", repr(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
