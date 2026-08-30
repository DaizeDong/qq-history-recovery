#!/usr/bin/env python3
"""Unit tests for the QQNT protobuf text extractor, on synthetic messages with no real data.

These build message blobs by hand with a tiny protobuf encoder, so the test proves the parser pulls a
message's own text and skips a reply's quoted original, without needing any real database.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qqnt_decode import message_text, TEXT_FIELD, QUOTE_FIELD


def _uvarint(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field_ld(field_num, payload):
    """Encode one length-delimited protobuf field (wire type 2)."""
    tag = (field_num << 3) | 2
    return _uvarint(tag) + _uvarint(len(payload)) + payload


def text_elem(s):
    return field_ld(TEXT_FIELD, s.encode("utf-8"))


def test_plain_text():
    blob = text_elem("合成测试消息")
    assert message_text(blob) == "合成测试消息", message_text(blob)
    print("[test] plain_text OK")


def test_multi_element():
    # a message whose text is split across two text elements
    blob = text_elem("前半段") + text_elem("后半段")
    assert message_text(blob) == "前半段 后半段", message_text(blob)
    print("[test] multi_element OK")


def test_reply_skips_quote():
    # a reply: the quoted original sits under field 47423, the reply's own text is a top text element
    quoted = field_ld(QUOTE_FIELD, text_elem("这是被引用的原始消息"))
    blob = quoted + text_elem("这是回复")
    got = message_text(blob)
    assert got == "这是回复", "quote leaked into text: %r" % got
    assert "被引用" not in got
    print("[test] reply_skips_quote OK")


def test_non_text_is_empty():
    # an element with no text field (say an image element under some other field) yields no text
    blob = field_ld(45002, _uvarint(1) + b"\x12\x08image.png")
    assert message_text(blob) == "", message_text(blob)
    print("[test] non_text_is_empty OK")


def main():
    fails = 0
    for fn in (test_plain_text, test_multi_element, test_reply_skips_quote, test_non_text_is_empty):
        try:
            fn()
        except AssertionError as e:
            print("[FAIL]", fn.__name__, e)
            fails += 1
    print("=== %s ===" % ("all passed" if fails == 0 else "%d failed" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
