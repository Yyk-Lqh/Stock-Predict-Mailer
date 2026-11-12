"""Trace user-supplied reference pixels into runtime SVG contours (development only).

Requires Pillow, NumPy and SciPy. Inputs are local, decoded source frames; no
network or generated artwork is used. Runtime rendering needs no image library.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / ".tmp/character-reference-review"
OUTPUT = ROOT / "src/stock_predict_mailer/control/web/modules/pony-reference.js"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def pack_coordinates(points):
    """Losslessly encode hundredth-unit coordinates as three six-bit digits."""
    result = []
    for point in points:
        value = round(point * 100) + 32768
        if not 0 <= value < 65536:
            raise ValueError(f"Coordinate outside packed range: {point}")
        result.extend(ALPHABET[(value >> shift) & 63] for shift in (12, 6, 0))
    return "".join(result)


def regions(mask, minimum=8):
    labels, count = ndimage.label(mask)
    items = []
    for label in range(1, count + 1):
        item = labels == label
        if int(item.sum()) >= minimum:
            items.append(item)
    return sorted(items, key=lambda item: int(item.sum()), reverse=True)


def boundary(mask):
    """Pixel-edge contours, clockwise exterior and counterclockwise holes."""
    edges = {}
    height, width = mask.shape
    for y, x in zip(*np.where(mask), strict=True):
        x, y = int(x), int(y)
        for exposed, start, end in (
            (y == 0 or not mask[y - 1, x], (x, y), (x + 1, y)),
            (x == width - 1 or not mask[y, x + 1], (x + 1, y), (x + 1, y + 1)),
            (y == height - 1 or not mask[y + 1, x], (x + 1, y + 1), (x, y + 1)),
            (x == 0 or not mask[y, x - 1], (x, y + 1), (x, y)),
        ):
            if exposed:
                edges.setdefault(start, []).append(end)
    loops = []
    while edges:
        start = next(iter(edges))
        current, points = start, []
        while current in edges:
            points.append(current)
            choices = edges[current]
            following = choices.pop()
            if not choices:
                del edges[current]
            current = following
            if current == start:
                break
        if len(points) > 5:
            loops.append(np.asarray(points, dtype=float))
    return sorted(loops, key=lambda p: abs(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1))), reverse=True)


def resample(points, count, origin, scale, anchor=None, softness=1.25):
    points = ndimage.gaussian_filter1d(points, softness, axis=0, mode="wrap")
    points = (points - np.asarray(origin)) * scale
    if anchor is not None:
        at = int(np.argmin(np.sum((points - np.asarray(anchor)) ** 2, axis=1)))
        points = np.roll(points, -at, axis=0)
    closed = np.concatenate([points, points[:1]])
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cumulative = np.concatenate([[0], np.cumsum(lengths)])
    values = np.arange(count) * cumulative[-1] / count
    result = np.column_stack([np.interp(values, cumulative, closed[:, dim]) for dim in [0, 1]])
    return np.round(result, 2).ravel().tolist()


def contour(mask, count, origin, scale, anchor=None, softness=1.25):
    loops = boundary(mask)
    return resample(loops[0], count, origin, scale, anchor, softness) if loops else []


def shapes(mask, origin, scale, limit=None):
    parts = regions(mask)
    if limit is not None:
        parts = parts[:limit]
    parts.sort(key=lambda region: float(np.where(region)[1].mean()))
    return [contour(region, max(12, min(36, int(region.sum() ** .5) * 3)), origin, scale) for region in parts]


def ellipses(mask, origin, scale):
    """Fit the source's smooth eye/pupil ellipses without pixel-stair corners."""
    parts = regions(mask)[:2]
    parts.sort(key=lambda region: float(np.where(region)[1].mean()))
    result = []
    for region in parts:
        y, x = np.where(region)
        points = np.column_stack([x + .5, y + .5])
        center = points.mean(axis=0)
        eigenvalues, eigenvectors = np.linalg.eigh(np.cov(points, rowvar=False, bias=True))
        axes = 2 * np.sqrt(eigenvalues)
        theta = np.arange(36) * np.pi * 2 / 36
        ring = np.column_stack([np.cos(theta), np.sin(theta)]) * axes
        ring = ring @ eigenvectors.T + center
        result.append(np.round((ring - origin) * scale, 2).ravel().tolist())
    return result


def split_character(path):
    image = np.array(Image.open(path).convert("RGB"))
    dark = image.max(axis=2) < 45
    parts = regions(dark, minimum=100)
    head, body = sorted(parts[:2], key=lambda part: np.where(part)[0].min())
    return image, dark, head, body


def trace_character(path, origin=None, scale=130 / 230):
    image, dark, head, body = split_character(path)
    # An arm behind the scarf can be disconnected from the main body mask.
    # Keep those visible anatomy pieces instead of discarding all but two blobs.
    body_islands = regions(dark & ~ndimage.binary_fill_holes(head) & ~body, minimum=100)
    if origin is None:
        origin = (np.where(head)[1].max() + 1 - 93 / 230 * 360, 574)
    eye_mask = ndimage.binary_fill_holes(head) & ~head
    red = (image[:, :, 0] > 90) & (image[:, :, 0] > image[:, :, 1].astype(float) * 1.8) & (image[:, :, 0] > image[:, :, 2].astype(float) * 1.8)
    scarf = regions(red)[0]
    red_channel = image[:, :, 0].astype(float)
    fringe_hull = ndimage.binary_closing(scarf, structure=np.ones((1, 5)))
    fringe_gaps = (ndimage.maximum_filter1d(red_channel, size=5, axis=1) - red_channel > 40) & (red_channel < 165) & fringe_hull
    fringe_gaps[:int(np.where(scarf)[0].max() - 7.4 / scale), :] = False
    fringe = [contour(part, 16, origin, scale, softness=.35) for part in regions(fringe_gaps, minimum=3)]
    return {
        "origin": [round(float(value), 4) for value in origin],
        "pixelScale": scale,
        "head": contour(ndimage.binary_fill_holes(head), 120, origin, scale, (48, -75)),
        "body": contour(body, 160, origin, scale, (0, -65)),
        "bodyIslands": [contour(part, 60, origin, scale) for part in body_islands],
        "bodyHoles": shapes(ndimage.binary_fill_holes(body) & ~body, origin, scale),
        "eyes": ellipses(eye_mask, origin, scale),
        "pupils": ellipses(dark & eye_mask, origin, scale),
        "scarf": contour(scarf, 280, origin, scale, (-20, -65), softness=.4),
        "fringe": fringe,
    }


def office_head(image, box, origin, scale):
    x0, y0, x1, y1 = box
    # The sleeping head touches a monitor whose screen is RGB ~43–47.
    # Separate the source's black ink from that background before tracing.
    dark = image[y0:y1, x0:x1].max(axis=2) < 25
    head = regions(dark, 50)[0]
    offset = (origin[0] - x0, origin[1] - y0)
    holes = ndimage.binary_fill_holes(head) & ~head
    collar_top = 124 if y0 < 100 else 465
    cloth = image[collar_top:collar_top + 68, x0:x1].astype(float)
    saturated = (cloth.max(axis=2) - cloth.min(axis=2) > 55) & (cloth.max(axis=2) > 90)
    collar = regions(saturated, 30)[0]
    return {
        "head": contour(ndimage.binary_fill_holes(head), 100, offset, scale, (25, -72)),
        "lids": shapes(holes, offset, scale, limit=2),
        "collar": contour(collar, 100, (origin[0] - x0, origin[1] - collar_top), scale, (0, -65)),
    }


def align_loop(frames, keys):
    """Match contour vertex phase before interpolation; preserve traced shape."""
    for key in keys:
        previous = None
        for frame in frames:
            points = np.asarray(frame[key]).reshape(-1, 2)
            if previous is not None:
                shift = min(range(len(points)), key=lambda i: float(np.sum((np.roll(points, i, axis=0) - previous) ** 2)))
                points = np.roll(points, shift, axis=0)
                frame[key] = points.ravel().tolist()
            previous = points


def main():
    still = trace_character(ROOT / "docs/superpowers/specs/assets/2026-11-12-character-reference/reference-still.png", (120, 284))
    walk = [dict(frame=frame, **trace_character(FRAMES / f"video-b/frame-{frame + 1:04d}.png", scale=130 / 360)) for frame in range(12, 30)]
    align_loop(walk, ["head", "body", "scarf"])
    # Video A chair/neck anchors, each normalized to the same runtime neck.
    # Both profile muzzles must fit, including the side opposite the first pose.
    specifications = [
        ("prediction", (132, 48, 268, 140), (204, 232)),
        ("main", (608, 48, 746, 140), (669, 232)),
        ("risk", (1048, 48, 1193, 140), (1132, 232)),
        ("mail", (108, 410, 258, 524), (194, 589)),
        ("advice", (608, 394, 752, 480), (669, 574)),
        ("charts", (1045, 394, 1195, 480), (1132, 574)),
    ]
    heads = {name: [] for name, _, _ in specifications}
    # Keep native frames through head turns. Unrelated contour vertex indices
    # are not anatomical correspondences and cannot safely be morphed.
    for frame in range(168):
        image = np.array(Image.open(FRAMES / f"video-a/frame-{frame + 1:04d}.png").convert("RGB"))
        for name, box, origin in specifications:
            heads[name].append(dict(frame=frame, **office_head(image, box, origin, .72)))
    end_pose = trace_character(FRAMES / "video-b/frame-0031.png", scale=130 / 360)
    stride = (end_pose["origin"][0] - walk[0]["origin"][0]) * 130 / 360
    data = {"height": 130, "sourceFPS": 30, "walkStart": 12, "walkEnd": 30, "walkPeriod": .6, "strideDistance": round(stride, 4),
            "still": still, "walk": walk, "seatedFPS": 30, "seated": heads}
    for frames in heads.values():
        for pose in frames:
            for key in ("head", "collar"):
                pose[key] = pack_coordinates(pose[key])
            pose["lids"] = [pack_coordinates(points) for points in pose["lids"]]
    output = "/* Source-derived SVG contours. Generated by scripts/trace_character_reference.py. */\n"
    output += "globalThis.PonyReference = (() => {\nconst data=" + json.dumps(data, separators=(",", ":")) + ";\n"
    output += f'const alphabet="{ALPHABET}";\n'
    output += """const decode=text=>{
  const points=[];
  for(let i=0;i<text.length;i+=3)points.push(((alphabet.indexOf(text[i])<<12|alphabet.indexOf(text[i+1])<<6|alphabet.indexOf(text[i+2]))-32768)/100);
  return points;
};
for(const frames of Object.values(data.seated))for(const pose of frames){
  pose.head=decode(pose.head);pose.collar=decode(pose.collar);pose.lids=pose.lids.map(decode);
}
return Object.freeze(data);
})();
"""
    OUTPUT.write_text(output, encoding="utf-8", newline="\n")
    print(f"Traced still, {len(walk)} walk phases, {sum(map(len, heads.values()))} seated head samples: {len(output):,} bytes")


if __name__ == "__main__":
    main()
