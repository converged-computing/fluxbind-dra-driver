"""Conversions between hwloc bitmap strings and Linux cpulist strings."""

HWLOC_WORD_BITS = 32
HWLOC_WORD_HEX_DIGITS = HWLOC_WORD_BITS // 4


def parse_hwloc_mask(mask: str) -> list[int]:
    """
    Return the sorted OS CPU indices set in an hwloc bitmap string.

    Accepts hwloc's comma-separated 32-bit word format, where an empty word
    means zero (e.g. "0x80000000,,0x00000001" is CPUs 0 and 95), and the
    single-word taskset format (e.g. "0x1000000000001000000").
    """
    if mask is None or not mask.strip():
        raise ValueError("hwloc mask is empty")

    words = [w.strip() for w in mask.strip().split(",")]
    multiword = len(words) > 1
    cpus = []

    # The last word holds the least significant bits.
    for position, word in enumerate(reversed(words)):
        if word[:2].lower() == "0x":
            word = word[2:]
        if multiword and len(word) > HWLOC_WORD_HEX_DIGITS:
            raise ValueError(f"hwloc mask word '{word}' is wider than 32 bits: {mask}")
        try:
            value = int(word, 16) if word else 0
        except ValueError:
            raise ValueError(f"invalid hwloc mask: {mask}") from None

        bit = position * HWLOC_WORD_BITS
        while value:
            if value & 1:
                cpus.append(bit)
            value >>= 1
            bit += 1

    return sorted(cpus)


def format_cpulist(cpus) -> str:
    """
    Format CPU indices as a Linux cpulist string (e.g. "0-3,8,10-11").
    """
    ordered = sorted(set(cpus))
    if not ordered:
        return ""

    ranges = []
    start = prev = ordered[0]
    for cpu in ordered[1:]:
        if cpu == prev + 1:
            prev = cpu
            continue
        ranges.append((start, prev))
        start = prev = cpu
    ranges.append((start, prev))
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def hwloc_mask_to_cpulist(mask: str) -> str:
    """
    Convert an hwloc bitmap string to a Linux cpulist string.
    """
    return format_cpulist(parse_hwloc_mask(mask))
