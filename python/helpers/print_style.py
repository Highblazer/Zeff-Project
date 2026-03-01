"""
Print Style - Formatted console output for Binary Rogue agents.
"""


class PrintStyle:
    """Styled console printer."""

    def __init__(self, font_color: str = "", padding: bool = False, bold: bool = False):
        self.font_color = font_color
        self.padding = padding
        self.bold = bold

    def print(self, text: str):
        """Print styled text to console."""
        prefix = ""
        suffix = ""

        # ANSI color mapping for common hex colors
        color_map = {
            "#00ff00": "\033[92m",   # green
            "#ff0000": "\033[91m",   # red
            "#ffff00": "\033[93m",   # yellow
            "#0000ff": "\033[94m",   # blue
            "#ff00ff": "\033[95m",   # magenta
            "#00ffff": "\033[96m",   # cyan
            "#ffffff": "\033[97m",   # white
        }

        color_code = color_map.get(self.font_color.lower(), "")
        reset = "\033[0m" if color_code else ""

        if self.bold:
            color_code = "\033[1m" + color_code

        if self.padding:
            prefix = "\n"
            suffix = "\n"

        print(f"{prefix}{color_code}{text}{reset}{suffix}")

    @staticmethod
    def error(text: str):
        PrintStyle(font_color="#ff0000", bold=True).print(f"ERROR: {text}")

    @staticmethod
    def success(text: str):
        PrintStyle(font_color="#00ff00").print(text)

    @staticmethod
    def warning(text: str):
        PrintStyle(font_color="#ffff00").print(f"WARNING: {text}")

    @staticmethod
    def info(text: str):
        PrintStyle(font_color="#00ffff").print(text)
