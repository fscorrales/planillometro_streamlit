"""Genera un archivo .ico a partir de una imagen con marco squircle centrado.

Recorta automáticamente el marco con esquinas redondeadas (squircle) de la
imagen de origen y lo exporta en múltiples resoluciones para Windows.

Uso:
    python generate_icon.py
    python generate_icon.py --source planillometro.jpg --output app_icon.ico
    python generate_icon.py --crop-box 903,249,1914,1293 --no-mask
"""

from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median

import numpy as np
from PIL import Image, ImageDraw

# --- CONFIGURACIÓN ---
SOURCE = "planillometro.jpg"
OUTPUT = "app_icon.ico"
ICON_SIZES: list[tuple[int, int]] = [
    (16, 16),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]
SPIKE_THRESHOLD = 12.0  # Diferencia mínima de brillo que identifica el borde
SPIKE_WINDOW = 6  # Distancia (px) a cada lado del pico evaluado
SCAN_OFFSETS: tuple[int, ...] = (-50, -25, 0, 25, 50)  # Líneas de escaneo
CORNER_RADIUS_RATIO = 0.20  # Radio del squircle como fracción del lado


def _find_spikes(profile: np.ndarray) -> list[int]:
    """Devuelve los índices con un pico fino de brillo sobre su entorno.

    Un borde delgado (la línea del marco) destaca por encima del valor
    medio de sus vecinos a `SPIKE_WINDOW` píxeles; las zonas extensas y
    brillantes (el ícono neón) no superan este filtro.
    """
    window = SPIKE_WINDOW
    scores = profile[window:-window] - 0.5 * (
        profile[: -2 * window] + profile[2 * window :]
    )
    return [int(index) + window for index in np.flatnonzero(scores > SPIKE_THRESHOLD)]


def detect_squircle_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Detecta el marco squircle centrado de la imagen.

    Escanea varias filas y columnas cerca del centro y toma el pico más
    externo de cada lado; el ícono interior queda descartado por estar
    dentro de esos bordes. Devuelve una caja estilo PIL (izq, arr, der,
    abajo) con der/abajo exclusivos.

    Eleva ValueError si ningún borde puede detectarse.
    """
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    height, width = gray.shape
    center_y = height // 2
    center_x = width // 2

    left_edges: list[int] = []
    right_edges: list[int] = []
    top_edges: list[int] = []
    bottom_edges: list[int] = []

    for offset in SCAN_OFFSETS:
        row_index = center_y + offset
        if 0 <= row_index < height:
            spikes = _find_spikes(gray[row_index])
            left = [index for index in spikes if index < center_x]
            right = [index for index in spikes if index > center_x]
            if left and right:
                left_edges.append(min(left))
                right_edges.append(max(right))

        column_index = center_x + offset
        if 0 <= column_index < width:
            spikes = _find_spikes(gray[:, column_index])
            top = [index for index in spikes if index < center_y]
            bottom = [index for index in spikes if index > center_y]
            if top and bottom:
                top_edges.append(min(top))
                bottom_edges.append(max(bottom))

    if not (left_edges and right_edges and top_edges and bottom_edges):
        raise ValueError(
            "No se pudo detectar el marco squircle en la imagen; "
            "indica el recorte manualmente con --crop-box L,T,R,B."
        )

    left = int(round(median(left_edges)))
    right = int(round(median(right_edges)))
    top = int(round(median(top_edges)))
    bottom = int(round(median(bottom_edges)))
    return left, top, right + 1, bottom + 1


def square_crop_box(
    box: tuple[int, int, int, int],
    image_size: tuple[int, int],
    padding: int,
) -> tuple[int, int, int, int]:
    """Normaliza la caja a un cuadrado perfecto centrada en el marco.

    Los .ico requieren frames cuadrados; se toma el mayor de los dos
    lados para no recortar ninguna parte del squircle y se desplaza
    hacia dentro si el padding lo excede de los límites de la imagen.
    """
    left, top, right, bottom = box
    image_width, image_height = image_size

    if right <= left or bottom <= top:
        raise ValueError(f"Recorte inválido: {box}.")
    if left < 0 or top < 0 or right > image_width or bottom > image_height:
        raise ValueError(
            f"El recorte {box} excede los límites de la imagen {image_size}."
        )

    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    side = max(right - left, bottom - top) + 2 * padding
    if side > image_width or side > image_height:
        raise ValueError(
            f"El recorte cuadrado de {side}px excede el tamaño de la imagen "
            f"{image_size}; reduce --padding."
        )

    crop_left = min(max(center_x - side // 2, 0), image_width - side)
    crop_top = min(max(center_y - side // 2, 0), image_height - side)
    return crop_left, crop_top, crop_left + side, crop_top + side


def apply_rounded_mask(
    image: Image.Image,
    inner_box: tuple[int, int, int, int],
) -> Image.Image:
    """Aplica transparencia a las esquinas fuera del marco squircle.

    `inner_box` es la posición relativa del marco dentro del recorte,
    para alinear la máscara con el contorno real y no con los márgenes.
    """
    left, top, right, bottom = inner_box
    radius = int(min(right - left, bottom - top) * CORNER_RADIUS_RATIO)
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=radius, fill=255)
    rgba = image.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def parse_crop_box(raw: str) -> tuple[int, int, int, int]:
    """Convierte una cadena 'L,T,R,B' en una tupla de enteros para argparse."""
    try:
        parts = [int(part.strip()) for part in raw.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Valor no entero en --crop-box: {raw!r}. Usa 'L,T,R,B'."
        ) from error

    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"--crop-box requiere 4 valores 'L,T,R,B'; recibido: {raw!r}."
        )

    left, top, right, bottom = parts
    if right <= left or bottom <= top:
        raise argparse.ArgumentTypeError(
            f"--crop-box inválido: der/abajo debe ser mayor que izq/arr; "
            f"recibido: {raw!r}."
        )
    return left, top, right, bottom


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convierte una imagen en un .ico recortando el marco squircle "
            "centrado de la aplicación."
        ),
    )
    parser.add_argument(
        "--source",
        default=SOURCE,
        help=f"Imagen de origen (por defecto: {SOURCE})",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT,
        help=f"Archivo .ico de salida (por defecto: {OUTPUT})",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=0,
        help="Píxeles adicionales alrededor del marco detectado (por defecto: 0)",
    )
    parser.add_argument(
        "--crop-box",
        dest="crop_box",
        type=parse_crop_box,
        default=None,
        metavar="L,T,R,B",
        help="Anula la detección automática con un recorte manual estilo PIL",
    )
    mask_group = parser.add_mutually_exclusive_group()
    mask_group.add_argument(
        "--mask-corners",
        dest="mask_corners",
        action="store_true",
        default=True,
        help="Transparencia en las esquinas redondeadas (por defecto)",
    )
    mask_group.add_argument(
        "--no-mask",
        dest="mask_corners",
        action="store_false",
        help="Conserva las esquinas opacas sin canal alfa",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    source = Path(args.source)
    output = Path(args.output)

    if not source.is_file():
        raise FileNotFoundError(f"No se encontró la imagen de origen: {source}")

    with Image.open(source) as image:
        image.load()
        box = args.crop_box if args.crop_box is not None else detect_squircle_box(image)
        final_box = square_crop_box(box, image.size, args.padding)
        source_size = image.size
        cropped = image.crop(final_box)

    relative_box = (
        box[0] - final_box[0],
        box[1] - final_box[1],
        box[2] - final_box[0],
        box[3] - final_box[1],
    )
    if args.mask_corners:
        cropped = apply_rounded_mask(cropped, relative_box)

    cropped.save(output, sizes=ICON_SIZES)

    print(f"Imagen de origen: {source} ({source_size[0]}x{source_size[1]})")
    print(f"Marco squircle detectado: {box}")
    print(f"Recorte final: {final_box} ({cropped.width}x{cropped.height})")
    print(f"Esquinas transparentes: {'sí' if args.mask_corners else 'no'}")
    print(f"¡Ícono '{output}' generado con éxito con {len(ICON_SIZES)} resoluciones!")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(f"Error: {error}") from error
