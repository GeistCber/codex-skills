"""Render an existing native CAD PDF to PNG without changing its contents."""

import argparse
import math
from pathlib import Path

import fitz
from PIL import Image, ImageChops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("png", type=Path)
    parser.add_argument("--page", type=int, default=1, help="Page number, starting at 1.")
    parser.add_argument("--scale", type=float, default=4)
    parser.add_argument("--padding", type=int, default=30)
    parser.add_argument("--no-crop", action="store_true")
    args = parser.parse_args()
    if args.pdf.resolve() == args.png.resolve():
        parser.error("Input and output paths must differ.")
    if args.png.suffix.lower() != ".png":
        parser.error("Output must have a .png extension.")
    if not math.isfinite(args.scale) or args.scale <= 0 or args.padding < 0:
        parser.error("Scale must be positive and finite; padding must be nonnegative.")

    with fitz.open(args.pdf) as document:
        if not 1 <= args.page <= len(document):
            parser.error(f"Page must be between 1 and {len(document)}.")
        pixels = document[args.page - 1].get_pixmap(
            matrix=fitz.Matrix(args.scale, args.scale), alpha=False,
            colorspace=fitz.csRGB,
        )
        image = Image.frombytes("RGB", (pixels.width, pixels.height), pixels.samples)

    if not args.no_crop:
        white = Image.new("RGB", image.size, "white")
        bounds = ImageChops.difference(image, white).getbbox()
        if bounds:
            pad = args.padding
            image = image.crop((
                max(0, bounds[0] - pad), max(0, bounds[1] - pad),
                min(image.width, bounds[2] + pad), min(image.height, bounds[3] + pad),
            ))
    args.png.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.png, format="PNG")
    print(f"{args.png} | page {args.page} | {image.width}x{image.height}")


if __name__ == "__main__":
    main()
