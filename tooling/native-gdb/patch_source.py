"""Apply the redistribution's small UTF-8 Windows host patch, idempotently."""
from pathlib import Path


def patch(source: Path):
    path = source / 'bfd/bfdio.c'
    original = path.read_text(encoding='utf-8')
    old = '  const unsigned int cp = ___lc_codepage_func ();'
    new = ('  /* FxStudio: the executable activation manifest and MI client use UTF-8.\n'
           '     CRT setlocale may still report the legacy user code page; using\n'
           '     it here corrupts non-ASCII filenames when BFD reopens an ELF. */\n'
           '  const unsigned int cp = CP_UTF8;')
    if old in original:
        path.write_text(original.replace(old, new), encoding='utf-8', newline='\n')
    elif new not in original:
        raise RuntimeError('Unexpected BFD source: UTF-8 patch could not be applied')


if __name__ == '__main__':
    import sys
    patch(Path(sys.argv[1]))
