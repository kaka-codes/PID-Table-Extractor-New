import json
import sys

import cv2
import easyocr


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: easyocr_worker.py <image_path>", file=sys.stderr)
        return 2

    image_path = sys.argv[1]
    image = cv2.imread(image_path)
    if image is None:
        print(f"Could not read image: {image_path}", file=sys.stderr)
        return 3

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    results = reader.readtext(
        image,
        detail=1,
        paragraph=False,
        batch_size=1,
    )

    items = []
    for result in results:
        try:
            box, text, confidence = result
        except Exception:
            continue

        if text is None:
            continue

        text = str(text).strip()
        if not text:
            continue

        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = 0.0

        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]

        items.append(
            {
                "text": text,
                "confidence": round(confidence_value, 4),
                "bbox": [
                    float(min(xs)),
                    float(min(ys)),
                    float(max(xs)),
                    float(max(ys)),
                ],
                "center": (
                    float(sum(xs) / len(xs)),
                    float(sum(ys) / len(ys)),
                ),
            }
        )

    sys.stdout.write(json.dumps(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
