"""Channel-specific response formatters.

Each formatter takes the canonical-markdown summary from the SQL agent
and converts it to the target channel's formatting dialect.

Supported channels:
  - Slack  : to_slack_mrkdwn()
  - Web    : pass-through (marked.js renders on the frontend)
"""
import re


def to_slack_mrkdwn(text: str) -> str:
    """Convert canonical markdown to Slack mrkdwn.

    Conversions:
      **bold**        →  *bold*
      *italic*        →  _italic_
      # Heading       →  *Heading*
      - item / * item →  • item
      [text](url)     →  <url|text>
      ```code```      →  passed through unchanged
      `inline code`   →  passed through unchanged
    """
    protected: dict[str, str] = {}
    counter = 0

    def stash(m: re.Match) -> str:
        nonlocal counter
        key = f"\x00{counter}\x00"
        protected[key] = m.group(0)
        counter += 1
        return key

    # Protect fenced code blocks and inline code — Slack renders them natively
    text = re.sub(r"```[\s\S]*?```", stash, text)
    text = re.sub(r"`[^`\n]+`", stash, text)

    # Headings → bold line
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Stash **bold** before the italic/bullet steps to avoid double-conversion
    bold_map: dict[str, str] = {}
    b_idx = 0

    def stash_bold(m: re.Match) -> str:
        nonlocal b_idx
        key = f"\x01{b_idx}\x01"
        bold_map[key] = f"*{m.group(1)}*"
        b_idx += 1
        return key

    text = re.sub(r"\*\*(.+?)\*\*", stash_bold, text)

    # Bullet list items (- or * at line start) → Slack bullet
    text = re.sub(r"^[*-]\s+", "• ", text, flags=re.MULTILINE)

    # Remaining *italic* → _italic_
    text = re.sub(r"\*([^\*\n]+)\*", r"_\1_", text)

    # Restore bold
    for key, val in bold_map.items():
        text = text.replace(key, val)

    # Markdown links → Slack links
    text = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"<\2|\1>", text)

    # Restore protected code blocks
    for key, val in protected.items():
        text = text.replace(key, val)

    return text
