"""Build dist/index.html for hosting as a claude.ai artifact.

The artifact host wraps the page in its own <html>/<head>/<body>, so this
strips those tags from index.html and adds the host's viewport/safe-area bits.
app.js, players.json and puzzles/ are published alongside it unchanged.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "index.html").read_text()

head = re.search(r"<head>(.*?)</head>", src, re.S).group(1)
body_tag = re.search(r"<body([^>]*)>", src).group(1)
body = re.search(r"<body[^>]*>(.*?)</body>", src, re.S).group(1)

head = re.sub(r"\s*<meta (charset|name=\"viewport\")[^>]*>", "", head)
head = head.replace("<title>StatLines — Daily Sports Trivia</title>",
                    '<title>StatLines</title>\n  <meta name="claude:viewport-fit-sides" content="cover">')
head = head.replace("</style>", """    :root { color-scheme: dark; }
    html, body { background-color: #0b0f17; }
    body > header.sticky { top: env(safe-area-inset-top, 0px); }
    body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 40; background: #0b0f17; }
    body > header > div, body > main { padding-left: max(16px, env(safe-area-inset-left, 0px)) !important; padding-right: max(16px, env(safe-area-inset-right, 0px)) !important; }
  </style>""", 1)
body = re.sub(r'src="app\.js\?v=\d+"', 'src="app.js"', body)

# Body classes move onto a script-applied class list, since we don't own <body>.
classes = re.search(r'class="([^"]*)"', body_tag).group(1)
out = f"{head.strip()}\n<script>document.body.className = {classes!r};</script>\n{body.strip()}\n"
(ROOT / "dist").mkdir(exist_ok=True)
(ROOT / "dist" / "index.html").write_text(out)
print("wrote dist/index.html")
