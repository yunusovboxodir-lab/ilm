# ilm

Learn a book while you build.

You are building something with an AI assistant: a product, a codebase, a business. You also have a book you want to master and never find the time to read. Load it into ilm and keep working. At the moments where a real decision is being made (what to build first, which approach to take, why the same bug keeps coming back) the assistant brings in one idea from your book, with its page, applied to that exact decision. Over weeks you learn the book through your own project instead of reading it cover to cover.

Vibe coding through a book.

```
You:        The updated_at column is out of sync again in orders, fix it.

Assistant:  Fixed: the trigger was missing on orders; added it and backfilled 212 rows.

            One thing worth your decision: this is the third column of this kind
            patched this month. Your book calls this "shifting the burden" (p. 124):
            each quick fix relieves the symptom and makes the root fix feel less
            urgent. Want one migration that covers every table instead of a fourth patch?
```

ilm is a small local MCP server plus a set of rules for the assistant. It works with any assistant that speaks MCP: Claude Code, Codex, Cursor, Claude Desktop and others, in a coding agent or in a chat. All of them share one book and one record of your progress.

## What it does

- Reads one book at a time: PDF, EPUB, FB2, DOCX, TXT, MD, HTML, or a YouTube video with captions.
- Builds an idea map of the book, portion by portion: each concept, when it applies, where it lives, the author's own example.
- Speaks up only at decision points, with one idea, in the plan or the summary. It stays silent while code is being written, and never writes the book into your code, commits or files.
- Tracks every idea as new, met or applied, and asks later whether you got to try it.
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

Tell the assistant: `Load this book: /path/to/book.epub` (or paste a YouTube link). After that, just keep working. Ask "where am I in the book?" at any time.

## Your data

Everything is stored in one file on your computer: `~/.ilm/ilm.db` (set `ILM_DATA_DIR` to move it). ilm itself uploads nothing, and its only network requests go to youtube.com when you load a YouTube link; the passages the assistant reads are sent to your AI provider as part of your conversation, like any other text you give it. Ask the assistant to "delete my ilm data" to erase everything.

## Limits of this version

- Audio books are not supported yet.
- YouTube videos need existing captions; no audio is downloaded or transcribed, and YouTube rejects some requests.
- Scanned PDFs without a text layer cannot be read.
- The assistant cannot write to you first: the "did you try it?" question comes at the start of your next conversation.
- Search is keyword-based, without embeddings.
- Tested with Claude Code on Windows. Other clients are supported through the standard MCP protocol but have not been tested by the author yet.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
