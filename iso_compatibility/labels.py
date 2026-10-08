"""Native label decoding shared with the existing loading-asset extractor."""
import struct


def unpack_bpe(data):
    """Gage byte-pair blocks, preceded by the native output/input lengths."""
    if len(data) < 8: raise ValueError('Truncated compressed header')
    expected, packed = struct.unpack_from('<II', data)
    if not 0 < expected <= 16*1024*1024 or not 0 < packed <= len(data)-8:
        raise ValueError('Invalid compressed lengths')
    data = data[:packed+8]; cursor=8; output=bytearray()
    def byte():
        nonlocal cursor
        if cursor >= len(data): raise ValueError('Truncated compressed block')
        value=data[cursor];cursor+=1;return value
    while len(output) < expected:
        left=list(range(256));right=[0]*256; code=0
        while code < 256:
            count=byte()
            if count > 127: code+=count-127;count=0
            if code >= 256: break
            for _ in range(count+1):
                if code >= 256: raise ValueError('Dictionary overrun')
                left[code]=byte()
                if left[code] != code:right[code]=byte()
                code+=1
        length=byte()*256+byte()
        if not length or cursor+length > len(data): raise ValueError('Invalid compressed block length')
        for value in data[cursor:cursor+length]:
            stack=[(value,0)]
            while stack:
                code,depth=stack.pop()
                if depth >= 256:raise ValueError('Cyclic byte-pair dictionary')
                if left[code] == code:
                    output.append(code)
                    if len(output) > expected:raise ValueError('Decompression overflow')
                else:stack.extend(((right[code],depth+1),(left[code],depth+1)))
        cursor+=length
    if cursor != len(data):raise ValueError('Unused compressed bytes')
    return bytes(output)


def english_label(data):
    if not data.startswith(b'\xff\xfe'):raise ValueError('Expected native UTF16 label')
    # Native fixed slots contain stale padding after the printable Latin label.
    # Stop at the first terminator/non-Latin padding code point.
    text=[]
    for pos in range(2,len(data)-1,2):
        code=struct.unpack_from('<H',data,pos)[0]
        if not (32 <= code <= 126 or code in (0xAA,0xB0,0xBA) or
                (192 <= code <= 255 and chr(code).isalpha())):break
        text.append(chr(code))
    return ''.join(text).strip()


def native_label(data):
    """The whole native UTF16 label up to its terminator (the Japanese disc's kanji/kana names, for reports)."""
    if not data.startswith(b'\xff\xfe'):raise ValueError('Expected native UTF16 label')
    text=[]
    for pos in range(2,len(data)-1,2):
        code=struct.unpack_from('<H',data,pos)[0]
        if code==0:break
        text.append(chr(code))
    return ''.join(text).strip()
