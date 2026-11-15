"""Small deterministic test fixtures, drawn here rather than taken from artwork."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from PIL import Image

assets = Path(__file__).resolve().parent/'assets'
assets.mkdir(exist_ok=True)
sprite = Image.new('RGBA', (16, 8), (0, 0, 0, 0))
for y in range(2, 6):
    for x in range(2, 14):
        sprite.putpixel((x, y), (0, 0, 0, 255) if (x//2+y//2)%2 == 0 else (255, 255, 255, 255))
sprite.save(assets/'sprite.png')
patterns = [
    '111101101101111', '010110010010111', '111001111100111',
    '111001111001111', '101101111001001', '111100111001111',
    '111100111101111', '111001001001001', '111101111101111', '111101111001111',
]
digits = Image.new('RGB', (30, 5), 'white')
for digit, pattern in enumerate(patterns):
    for n, bit in enumerate(pattern):
        if bit == '1': digits.putpixel((digit*3+n%3, n//3), (0, 0, 0))
digits.save(assets/'digits.png')
