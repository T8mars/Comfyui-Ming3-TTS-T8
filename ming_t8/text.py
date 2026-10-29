from __future__ import annotations
import re


def split_long_text(text, max_units=120):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请先填写要生成的文字")
    if not 20 <= max_units <= 2000:
        raise ValueError("分段长度必须在20到2000之间")
    paragraphs = re.split(r"\n\s*\n", text.strip())
    result = []
    for paragraph in paragraphs:
        units = re.findall(r"\[[^\]]+\]|[^。！？!?；;\n]+[。！？!?；;]?|[\n]", paragraph)
        current = ""
        for unit in units:
            if current and len(current) + len(unit) > max_units:
                result.append(current.strip())
                current = ""
            if len(unit) > max_units:
                # Preserve inline event tags and word boundaries when splitting a long clause.
                pieces = re.findall(r"\[[^\]]+\]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|\s+|.", unit)
                for piece in pieces:
                    if current and len(current) + len(piece) > max_units:
                        result.append(current.strip())
                        current = ""
                    current += piece
            else:
                current += unit
        if current.strip():
            result.append(current.strip())
    return [item for item in result if item]
