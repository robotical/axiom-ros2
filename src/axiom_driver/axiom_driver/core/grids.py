"""Grid measurements for standard single-channel ROS images."""

import math
import struct


def float32_image_data(width, height, pixels):
    """Pack row-major pixels as little-endian floats; missing pixels are NaN."""
    if width <= 0 or height <= 0 or len(pixels) != width * height:
        raise ValueError('Image dimensions do not match its pixels')
    # Do not turn missing measurements into zero or emit infinities on the wire.
    pixels = [float(p) for p in pixels]
    pixels = [p if math.isfinite(p) and abs(p) <= 3.4028234663852886e38 else math.nan
              for p in pixels]
    return struct.pack('<' + 'f' * len(pixels), *pixels)


def zone_grid(values, distance):
    """Extract a descriptor-defined 4x4/8x8 range grid, masking invalid zones."""
    options = distance['meta'].get('vo', {})
    side = values[options['gridAttr']]['value']
    if isinstance(side, bool) or side not in (4, 8):
        raise ValueError('Range grid must be 4x4 or 8x8')
    side = int(side)
    count = side * side
    pixels = distance['si_value']
    statuses = values[options['statusAttr']]['value']
    accepted = options['validStatus']
    if (not isinstance(pixels, list) or not isinstance(statuses, list)
            or len(pixels) not in (count, 64) or len(statuses) != len(pixels)):
        raise ValueError('Range grid dimensions do not match its distances/statuses')
    if not isinstance(accepted, list) or not accepted:
        raise ValueError('Range grid has no valid status codes')
    flags = distance['valid']
    if isinstance(flags, list) and len(flags) != len(pixels):
        raise ValueError('Range grid validity length mismatch')
    # The fixed firmware payload reserves 64 entries even in 4x4 mode. Preserve
    # its zone order and omit padding, without applying display transformations.
    result = []
    for index, pixel in enumerate(pixels[:count]):
        valid = flags[index] if isinstance(flags, list) else flags
        result.append(float(pixel) if valid and statuses[index] in accepted
                      and math.isfinite(pixel) and pixel > 0 else math.nan)
    return side, result
