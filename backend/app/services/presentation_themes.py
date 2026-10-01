# Palette-driven deck themes. Colors = (r, g, b). Fonts reference installed family names.
# Tokens beyond colors drive chrome in pptx_renderer (bar style, footer, card surface).

_FONT = {'title_font': 'Vazirmatn', 'body_font': 'Vazirmatn'}

THEMES = {
    'polymind': {
        **_FONT,
        'bg': (248, 250, 253), 'surface': (255, 255, 255),
        'primary': (30, 71, 209), 'accent': (109, 94, 247),
        'text': (15, 23, 42), 'muted': (100, 116, 139),
        'bar_style': 'edge', 'footer': True,
    },
    'dark': {
        **_FONT,
        'bg': (15, 23, 42), 'surface': (30, 41, 59),
        'primary': (128, 167, 255), 'accent': (167, 139, 250),
        'text': (248, 250, 253), 'muted': (148, 163, 184),
        'bar_style': 'edge', 'footer': True,
    },
    'minimal': {
        **_FONT,
        'bg': (255, 255, 255), 'surface': (244, 244, 245),
        'primary': (24, 24, 27), 'accent': (113, 113, 122),
        'text': (24, 24, 27), 'muted': (113, 113, 122),
        'bar_style': 'top', 'footer': True,
    },
    'vibrant': {
        **_FONT,
        'bg': (255, 247, 237), 'surface': (255, 255, 255),
        'primary': (234, 88, 12), 'accent': (217, 70, 239),
        'text': (28, 25, 23), 'muted': (120, 113, 108),
        'bar_style': 'edge', 'footer': True,
    },
    'board': {
        **_FONT,
        'bg': (241, 245, 249), 'surface': (255, 255, 255),
        'primary': (15, 23, 42), 'accent': (30, 64, 175),
        'text': (15, 23, 42), 'muted': (71, 85, 105),
        'bar_style': 'top', 'footer': True,
    },
    'pitch': {
        **_FONT,
        'bg': (10, 10, 12), 'surface': (24, 24, 27),
        'primary': (250, 204, 21), 'accent': (255, 255, 255),
        'text': (250, 250, 250), 'muted': (161, 161, 170),
        'bar_style': 'none', 'footer': False,
    },
    'marketing': {
        **_FONT,
        'bg': (255, 255, 255), 'surface': (239, 246, 255),
        'primary': (37, 99, 235), 'accent': (236, 72, 153),
        'text': (15, 23, 42), 'muted': (100, 116, 139),
        'bar_style': 'edge', 'footer': True,
    },
    'mono': {
        **_FONT,
        'bg': (255, 255, 255), 'surface': (250, 250, 250),
        'primary': (0, 0, 0), 'accent': (82, 82, 82),
        'text': (23, 23, 23), 'muted': (115, 115, 115),
        'bar_style': 'top', 'footer': True,
    },
}

THEME_KEYS = tuple(THEMES.keys())


def get_theme(key):
    return THEMES.get(key, THEMES['polymind'])
