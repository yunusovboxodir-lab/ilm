# ilm

A book you know becomes the language you work in.

You read a book, it mattered, and a year later most of it is gone. Load it into ilm and keep working with your AI assistant as usual. From then on the assistant speaks the book's language: when one of its concepts names what is happening in your project, it uses that word, right inside the sentence you were going to read anyway. You meet the book's ideas again and again in your own situations, and that is how a book read once turns into a way of thinking.

```
You:        The updated_at column is out of sync again in orders, fix it.

Assistant:  Fixed: the trigger was missing on orders; added it and backfilled
            212 rows, tests pass. This is the third patch of this kind this
            month - a shifting of the burden: each quick fix removes the symptom
            and makes the root fix feel less urgent. Do you want one migration
            for all tables instead of a fourth patch?
```

No lecture, no separate "idea of the day", nothing extra to read. The first time a term appears it comes with a few words of explanation; after that the assistant uses it the way a colleague who read the same book would. Ask "tell me more about that" and you get the passage, the page and the author's own example.

It also works for a book you have not read yet: you pick up its vocabulary on your own cases first, and know which chapters are worth opening.

ilm is a small local MCP server plus a set of rules for the assistant. It works with any assistant that speaks MCP: Claude Code, Codex, Cursor, Claude Desktop and others, in a coding agent or in a chat. All of them share one book and one record of your progress.

## Lenses: the no-install way

For ten widely read books there are ready-made lenses in [`lenses/`](lenses/README.md): one text file each, about 20 concepts with a plain gloss and a project example, eight speaking rules, a project map and five check questions. Paste a lens into your assistant's standing instructions (a Claude or ChatGPT project, `CLAUDE.md`, `AGENTS.md`) and it explains your project in that book's terms. No server, no book file, no mapping cost. The lenses are in Russian.

Systems thinking (Senge), theory of constraints (Goldratt), lean startup (Ries), fast and slow thinking (Kahneman), atomic habits (Clear), seven habits (Covey), good to great (Collins), antifragility (Taleb), deep work (Newport), winning people over (Carnegie).

Use the server described below when your book is not on that list or is your company's own material.

## What it does

- Reads one book at a time: PDF, EPUB, FB2, DOCX, TXT, MD, HTML, or a YouTube video with captions.
- Builds the book's vocabulary once, right after loading: each concept, a short gloss, when it applies, where it lives, the author's own example.
- Hands the assistant that vocabulary at the start of every conversation, so speaking the book's language costs no extra searches and no waiting.
- Keeps the terms in the conversation only. They never go into your code, commits or files.
- Tracks every term as new, met or applied.
- Remembers lasting facts about you and your project between conversations.
- Lets you switch to another book and come back: progress on each book is kept.
- Works in any language the assistant speaks; the book and the conversation may be in different languages.

## Install

Requirement: Python 3.9 or newer available as `python`. Optional packages, needed only for the matching source type:

```bash
pip install -U "pypdf>=6"
```

```bash
pip install youtube-transcript-api
```

### Claude Code

Inside Claude Code (2.1.275 or later):

```
/plugin install ilm --marketplace yunusovboxodir-lab/ilm
```

To update later, in a regular terminal:

```bash
claude plugin marketplace update ilm
```

```bash
claude plugin update ilm@ilm
```

### Any other MCP client

Get a local copy first:

```bash
git clone https://github.com/yunusovboxodir-lab/ilm.git
```

Then register the server, replacing `/path/to/ilm` with the folder you cloned into.

**Codex** (CLI, IDE extension and the ChatGPT desktop app share this setting):

```bash
codex mcp add ilm -- python /path/to/ilm/server/ilm_server.py
```

**Cursor, Claude Desktop and other clients with a JSON config** (`.cursor/mcp.json`, `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ilm": {
      "command": "python",
      "args": ["/path/to/ilm/server/ilm_server.py"]
    }
  }
}
```

On macOS and Linux, where the interpreter is usually called `python3`, use `python3` as the command (in Claude Code: change it in `.claude-plugin/plugin.json`).

The rules travel with the server: it sends short instructions when it connects and serves the full rules through its `ilm_guide` tool, so no extra setup is needed. If your assistant does not pick the book up on its own, add one line to its standing instructions file (`AGENTS.md`, project rules or similar):

```
At the start of each conversation call the ilm_status tool and follow the rules from ilm_guide.
```

Web chat apps that cannot start local programs (for example ChatGPT in the browser) cannot connect to ilm.

## Use

Tell the assistant: `Load this book: /path/to/book.epub` (or paste a YouTube link).

The assistant then reads the whole book once to build its vocabulary. This is the one costly step: for a 400-page book in Russian it took about 600 thousand tokens and some fifteen minutes in the author's test (the text itself is about half of that; the rest is the back-and-forth of reading it in portions). It tells you the size first, and you can say "later" to start with the opening chapters only.

After that, just keep working. Ask "where am I in the book?" or "tell me more about <term>" at any time.

## Your data

Everything is stored in one file on your computer: `~/.ilm/ilm.db` (set `ILM_DATA_DIR` to move it). ilm itself uploads nothing, and its only network requests go to youtube.com when you load a YouTube link; the passages the assistant reads are sent to your AI provider as part of your conversation, like any other text you give it. Ask the assistant to "delete my ilm data" to erase everything.

## Limits of this version

- Audio books are not supported yet.
- YouTube videos need existing captions; no audio is downloaded or transcribed, and YouTube rejects some requests.
- Scanned PDFs without a text layer cannot be read.
- The vocabulary is sent to the assistant at the start of each conversation: about 7-8 thousand tokens for a book of 75 terms.
- Search is keyword-based, without embeddings.
- Tested with Claude Code on Windows. Other clients are supported through the standard MCP protocol but have not been tested by the author yet.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
