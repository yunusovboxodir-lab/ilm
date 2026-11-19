# ilm

A personal assistant that teaches you one book through your own everyday matters.

You have a book you read and forgot, or want to read and never find the time for. Load it into ilm and then simply talk to Claude about your own life and work: a talk with your manager, a week to plan, an argument at home. Claude helps with the matter itself and, where it truly fits, brings in one idea from your book, with its place in the book, applied to your exact situation. Over weeks you learn the book through your own life instead of reading it cover to cover.

ilm is a plugin for Claude Code: a skill with the assistant's rules and a small local MCP server that reads the book, searches it and keeps your progress.

## What it does

- Reads one book at a time: PDF, EPUB, FB2, DOCX, TXT, MD, HTML, or a YouTube video with captions.
- Builds an idea map of the book, portion by portion: each concept, where it lives, the author's own example.
- Uses the book only where it fits your situation. A question the book has nothing to say about gets a plain answer.
- Tracks every idea as new, met or applied, and asks later whether you managed to try it.
- Remembers lasting facts about you between conversations, so examples are personal.
- Lets you switch to another book and come back: progress on each book is kept.
- Works in any language Claude speaks; the book and the conversation may be in different languages.

## Install

Requirements: Claude Code and Python 3.9 or newer available as `python`.

Inside Claude Code (2.1.275 or later):

```
/plugin install ilm --marketplace yunusovboxodir-lab/ilm
```

Or from a local copy:

```bash
git clone https://github.com/yunusovboxodir-lab/ilm.git
```

```bash
claude --plugin-dir ./ilm
```

Optional packages, needed only for the matching source type:

```bash
pip install -U "pypdf>=6"
```

```bash
pip install youtube-transcript-api
```

On macOS and Linux, where the interpreter is usually called `python3`, change `"command": "python"` to `"python3"` in `.claude-plugin/plugin.json`.

## Use

Tell Claude: `Load this book: /path/to/book.epub` (or paste a YouTube link). After that, just talk about your own matters. Ask "where am I in the book?" at any time.

## Your data

Everything is stored in one file on your computer: `~/.ilm/ilm.db` (set `ILM_DATA_DIR` to move it). ilm itself uploads nothing, and its only network requests go to youtube.com when you load a YouTube link; the passages Claude reads are sent to Claude as part of your conversation, like any other text you give it. Ask Claude to "delete my ilm data" to erase everything.

## Limits of this version

- Audio books are not supported yet.
- YouTube videos need existing captions; no audio is downloaded or transcribed.
- Scanned PDFs without a text layer cannot be read.
- Claude cannot write to you first: the "did you try it?" question comes at the start of your next conversation.
- Search is keyword-based, without embeddings.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
